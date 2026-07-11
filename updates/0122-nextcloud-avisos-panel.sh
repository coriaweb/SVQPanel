#!/bin/bash
# 0122-nextcloud-avisos-panel.sh
#
# BUG: un Nextcloud instalado/alojado en SVQPanel salia con la pagina "Avisos de
# seguridad y configuracion" llena de errores que son culpa del PANEL, no del cliente:
#   - "Su servidor no esta configurado correctamente para resolver /.well-known/caldav"
#     (y carddav): faltaban los redirects de service discovery en el vhost nginx.
#   - "occ" / cron.php de Nextcloud petaban con "Memcache OC\Memcache\APCu not
#     available for local cache" porque apc.enable_cli venia a 0 en PHP CLI.
#
# FIX:
#   1) apc.enable_cli = 1 en el CLI de todas las versiones de PHP (Nextcloud usa APCu
#      como cache local y su occ/cron son CLI).
#   2) Regenerar los vhosts para que recojan los nuevos redirects .well-known
#      (carddav/caldav/webfinger/nodeinfo) que ahora genera scripts/utils.py.
#
# El resto de avisos (Redis/memcache, trusted_proxies, region, ventana de
# mantenimiento) los deja bien el autoinstalador de Nextcloud del panel a partir de
# ahora; en instancias YA instaladas se ajustan desde el propio Nextcloud.
#
# Idempotente y no interactivo.

set -u

echo "-> 0122: quitar los avisos de Nextcloud que dependian del panel..."

# ── 1. apc.enable_cli en todas las versiones de PHP ───────────────────────────
CHANGED=0
for d in /etc/php/*/cli/conf.d; do
    [ -d "$d" ] || continue
    VER="$(echo "$d" | sed -E 's|/etc/php/([^/]+)/.*|\1|')"
    INI="$d/99-apcu-cli.ini"
    if [ ! -f "$INI" ] || ! grep -qE '^\s*apc\.enable_cli\s*=\s*1' "$INI" 2>/dev/null; then
        echo "apc.enable_cli = 1" > "$INI"
        echo "  . PHP $VER: apc.enable_cli = 1 (occ/cron.php de Nextcloud)"
        CHANGED=1
    fi
done
[ "$CHANGED" = "0" ] && echo "  . apc.enable_cli ya estaba en todas las versiones."

# ── 1b. Codecs extra de ImageMagick (soporte SVG en imagick) ──────────────────
# Sin ellos Nextcloud avisa: "El módulo PHP imagick no tiene soporte para SVG".
# El nombre del paquete lleva la version de ImageMagick (Debian 13 = 7): lo buscamos.
if command -v php >/dev/null 2>&1 || ls /etc/php >/dev/null 2>&1; then
    IMAGICK_EXTRA="$(apt-cache search --names-only '^libmagickcore-[0-9].*-extra$' 2>/dev/null \
        | awk '{print $1}' | grep -v hdri | head -1)"
    if [ -n "$IMAGICK_EXTRA" ] && ! dpkg -l "$IMAGICK_EXTRA" 2>/dev/null | grep -q '^ii'; then
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$IMAGICK_EXTRA" >/dev/null 2>&1 \
            && echo "  . $IMAGICK_EXTRA instalado (soporte SVG en imagick)" \
            || echo "  . no se pudo instalar $IMAGICK_EXTRA (no critico)"
        for v in /etc/php/*/fpm; do
            VER="$(echo "$v" | sed -E 's|/etc/php/([^/]+)/.*|\1|')"
            systemctl reload "php${VER}-fpm" >/dev/null 2>&1 || true
        done
    fi
fi

# ── 2. Regenerar vhosts (recogen los redirects .well-known) ───────────────────
if [ -x /opt/svqpanel/venv/bin/python ]; then
    cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli regenerate_all_vhosts \
        && echo "  . vhosts regenerados (.well-known caldav/carddav)" \
        || echo "  . aviso: la regeneracion de vhosts devolvio error (revisar)"
    if command -v nginx >/dev/null 2>&1 && nginx -t >/dev/null 2>&1; then
        systemctl reload nginx >/dev/null 2>&1 && echo "  . nginx recargado"
    fi
else
    echo "  . venv no encontrado; no se regeneran vhosts"
fi

echo "OK 0122: avisos de Nextcloud (well-known + APCu CLI) corregidos."
exit 0
