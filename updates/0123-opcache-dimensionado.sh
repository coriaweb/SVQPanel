#!/bin/bash
# 0123-opcache-dimensionado.sh
#
# BUG: el OPcache se quedaba con los defaults de Debian, que son cortos para
# cualquier aplicacion PHP seria alojada en el panel:
#
#   opcache.memory_consumption      = 128    (WordPress+plugins / Nextcloud no caben)
#   opcache.interned_strings_buffer = 8      (Nextcloud AVISA explicitamente: pide > 8)
#   opcache.max_accelerated_files   = 10000  (Nextcloud solo trae ~15k ficheros PHP)
#
# Cuando se desbordan, el OPcache empieza a desalojar clases en caliente o
# directamente deja de cachear ficheros nuevos EN SILENCIO: el sitio sigue
# funcionando, pero mucho mas lento y sin que nadie se entere. En Nextcloud
# ademas sale el aviso "El modulo PHP OPcache no esta configurado correctamente"
# en la pagina de "Avisos de seguridad y configuracion".
#
# FIX: drop-in propio (99-svqpanel-opcache.ini) en el conf.d de FPM de cada
# version de PHP, con valores dimensionados para apps reales. Es un drop-in
# aparte: no toca el 10-opcache.ini de Debian, y se revierte borrandolo.
#
# NOTA: save_comments = 1 es OBLIGATORIO. Las anotaciones de Doctrine (Nextcloud)
# y de varios frameworks se leen en runtime; ponerlo a 0 los rompe.
#
# Reflejado tambien en install.sh (los servidores nuevos nacen con esto).
# Idempotente y no interactivo.

set -u

echo "-> 0123: dimensionar el OPcache para apps reales (Nextcloud/WordPress/Laravel)..."

CHANGED=0

for d in /etc/php/*/fpm/conf.d; do
    [ -d "$d" ] || continue
    VER="$(echo "$d" | sed -E 's|/etc/php/([^/]+)/.*|\1|')"
    INI="$d/99-svqpanel-opcache.ini"

    # Idempotencia: si ya esta escrito con el valor bueno, no tocar ni recargar.
    if [ -f "$INI" ] && grep -qE '^\s*opcache\.interned_strings_buffer\s*=\s*16' "$INI" 2>/dev/null; then
        continue
    fi

    cat > "$INI" << 'OPCACHEEOF'
; SVQPanel: OPcache dimensionado para apps reales (Nextcloud, WordPress, Laravel).
; Los defaults de Debian (128M / 8 / 10000) se quedan cortos y el OPcache empieza
; a desalojar clases en caliente, o directamente deja de cachear.
opcache.enable = 1
opcache.memory_consumption = 256
opcache.interned_strings_buffer = 16
opcache.max_accelerated_files = 20000
opcache.revalidate_freq = 2
opcache.save_comments = 1
OPCACHEEOF

    echo "  . PHP $VER: OPcache 256M / interned 16 / 20000 ficheros"
    CHANGED=1
done

if [ "$CHANGED" = "0" ]; then
    echo "  . el OPcache ya estaba dimensionado en todas las versiones."
    echo "OK 0123: sin cambios."
    exit 0
fi

# Recargar los FPM para que cojan el drop-in. reload (no restart): no cortamos
# las peticiones en vuelo de los sitios alojados.
for d in /etc/php/*/fpm; do
    [ -d "$d" ] || continue
    VER="$(echo "$d" | sed -E 's|/etc/php/([^/]+)/.*|\1|')"
    if systemctl is-active --quiet "php${VER}-fpm" 2>/dev/null; then
        systemctl reload "php${VER}-fpm" >/dev/null 2>&1 \
            && echo "  . php${VER}-fpm recargado" \
            || echo "  . aviso: no se pudo recargar php${VER}-fpm"
    fi
done

echo "OK 0123: OPcache dimensionado."
exit 0
