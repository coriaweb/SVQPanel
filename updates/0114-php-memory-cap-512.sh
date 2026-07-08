#!/bin/bash
# 0114-php-memory-cap-512.sh
#
# Sube el techo global de memory_limit de PHP de 256M a 512M en todas las
# versiones de PHP-FPM (y CLI) instaladas. Ese valor es el CAP: el maximo que el
# panel permite pedir a un dominio via override por dominio (php_ini_manager
# valida contra el php.ini global). Cada pool sigue naciendo con 128M; esto solo
# eleva el techo para quien lo necesite.
#
# Motivo: editores pesados como Elementor recomiendan >=256M y agotan los 128M
# por defecto al abrir el editor (PHP Fatal error: Allowed memory size exhausted
# -> error 500 en admin-ajax.php). Con el cap en 256M no se podia subir un dominio
# por encima de eso. 512M da margen a Elementor/WooCommerce con muchos plugins.
#
# NO baja el limite si el admin ya lo tenia mas alto. Idempotente y no interactivo.

set -u

echo "-> 0114: techo global de memory_limit de PHP -> 512M..."

CHANGED=0
for f in /etc/php/*/fpm/php.ini /etc/php/*/cli/php.ini; do
    [ -f "$f" ] || continue
    CUR="$(grep -E '^\s*memory_limit\s*=' "$f" | head -1 | sed -E 's/.*=\s*//; s/\s//g')"
    # Normalizar a MB para comparar (solo soporta sufijo M o G; -1 = ilimitado).
    case "$CUR" in
        -1) echo "  . $f: memory_limit=-1 (ilimitado), se respeta"; continue ;;
        *G|*g) echo "  . $f: memory_limit=$CUR (>=1G), se respeta"; continue ;;
        *M|*m)
            NUM="${CUR%[Mm]}"
            if [ "$NUM" -ge 512 ] 2>/dev/null; then
                echo "  . $f: memory_limit=$CUR (>=512M), se respeta"
                continue
            fi
            ;;
    esac
    sed -i -E 's/^\s*memory_limit\s*=.*/memory_limit = 512M/' "$f"
    echo "  . $f: memory_limit $CUR -> 512M"
    CHANGED=1
done

if [ "$CHANGED" = "1" ]; then
    for v in 7.3 7.4 8.0 8.1 8.2 8.3 8.4 8.5; do
        systemctl reload "php${v}-fpm" >/dev/null 2>&1 && echo "  . php${v}-fpm recargado"
    done
fi

echo "OK 0114: techo de memory_limit de PHP en 512M"
exit 0
