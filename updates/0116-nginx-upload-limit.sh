#!/bin/bash
# 0116-nginx-upload-limit.sh
#
# BUG: subir un archivo de mas de 1 MB por la biblioteca de medios de WordPress
# (o cualquier POST grande) fallaba con "Respuesta inesperada del servidor". Causa:
# los vhosts nginx generados por el panel NO ponian client_max_body_size, asi que
# nginx aplicaba su DEFAULT de 1 MB y cortaba la subida con un 413 (Payload Too
# Large) ANTES de llegar a PHP/Apache. El 413 no es JSON -> WordPress mostraba ese
# mensaje confuso. Ademas el upload_max_filesize/post_max_size global de PHP estaba
# en el default de fabrica (2M/8M), tambien insuficiente. En Hestia no pasaba
# porque Hestia si pone client_max_body_size en sus vhosts.
#
# FIX (dos capas):
#   1. PHP: subir upload_max_filesize/post_max_size global a 64M (todas las
#      versiones FPM). Es el techo; el panel puede ajustarlo por dominio.
#   2. nginx: el generador de vhosts (scripts/utils.py) ya inyecta
#      client_max_body_size 64m en cada server{}. Regeneramos TODOS los vhosts
#      existentes para que lo recojan (via el CLI del panel, idempotente).
#
# Idempotente y no interactivo.

set -u

echo "-> 0116: limite de subida (nginx client_max_body_size + PHP upload)..."

# ── 1. PHP: subir upload_max_filesize / post_max_size a 64M ───────────────────
PHP_CHANGED=0
for f in /etc/php/*/fpm/php.ini; do
    [ -f "$f" ] || continue
    for KEY in upload_max_filesize post_max_size; do
        CUR="$(grep -E "^\s*${KEY}\s*=" "$f" | head -1 | sed -E 's/.*=\s*//; s/\s//g')"
        # Normalizar: si ya es >=64M (o 0 en post_max_size = ilimitado), se respeta.
        case "$CUR" in
            0) [ "$KEY" = "post_max_size" ] && { echo "  . $f [$KEY]=0 (ilimitado), se respeta"; continue; } ;;
            *G|*g) echo "  . $f [$KEY]=$CUR (>=1G), se respeta"; continue ;;
            *M|*m)
                NUM="${CUR%[Mm]}"
                if [ "$NUM" -ge 64 ] 2>/dev/null; then
                    echo "  . $f [$KEY]=$CUR (>=64M), se respeta"
                    continue
                fi
                ;;
        esac
        sed -i -E "s/^\s*${KEY}\s*=.*/${KEY} = 64M/" "$f"
        echo "  . $f [$KEY] $CUR -> 64M"
        PHP_CHANGED=1
    done
done

if [ "$PHP_CHANGED" = "1" ]; then
    for v in 7.3 7.4 8.0 8.1 8.2 8.3 8.4 8.5; do
        systemctl reload "php${v}-fpm" >/dev/null 2>&1 && echo "  . php${v}-fpm recargado"
    done
fi

# ── 2. nginx: regenerar todos los vhosts (recogen client_max_body_size) ───────
if [ -x /opt/svqpanel/venv/bin/python ]; then
    cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli regenerate_all_vhosts \
        && echo "  . vhosts regenerados (client_max_body_size aplicado)" \
        || echo "  . aviso: la regeneracion de vhosts devolvio error (revisar)"
    # El CLI ya recarga; por si acaso, un reload final si la config valida.
    if command -v nginx >/dev/null 2>&1 && nginx -t >/dev/null 2>&1; then
        systemctl reload nginx >/dev/null 2>&1 && echo "  . nginx recargado"
    fi
else
    echo "  . venv no encontrado; no se regeneran vhosts (revisar manualmente)"
fi

echo "OK 0116: limite de subida corregido (nginx 64m + PHP 64M)"
exit 0
