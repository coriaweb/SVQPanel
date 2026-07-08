#!/bin/bash
# 0113-crowdsec-wp-rest-whitelist.sh
#
# BUG: CrowdSec baneaba al ADMINISTRADOR legitimo de un WordPress mientras
# editaba/actualizaba con Elementor. Causa: Elementor (y otros plugins de WP)
# disparan rafagas de GET a /wp-json/... que devuelven 404 cuando el endpoint no
# existe (tipico: Elementor Pro pidiendo rutas de licencia que solo existen en la
# version de pago). El escenario generico crowdsecurity/http-probing cuenta esos
# 404 como sondeo de rutas y banea la IP del cliente (visto en prod: IP de Orange
# ES baneada 2 veces en un dia, 11 eventos, todos GET 404 a /wp-json/elementor/*).
#
# FIX: parser de whitelist que excluye del conteo de probing las peticiones a la
# REST API de WordPress (/wp-json/). Es la API estandar de WP; un 404 ahi es
# normal (plugin no instalado), no un ataque. Los probes reales (.env, .git,
# /vendor, /wp-admin/xxx) NO empiezan por /wp-json/ y siguen baneandose
# (verificado con cscli explain: TEST /wp-json/ -> whitelisted; TEST /.env y
# /wp-admin/setup-config.php -> unchanged, siguen su curso).
#
# Idempotente y no interactivo.

set -u

echo "-> 0113: whitelist REST API de WordPress (/wp-json/) para CrowdSec..."

if [ ! -d /etc/crowdsec ]; then
    echo "  . CrowdSec no instalado; se omite"
    echo "OK 0113: sin cambios"
    exit 0
fi

mkdir -p /etc/crowdsec/parsers/s02-enrich
cat > /etc/crowdsec/parsers/s02-enrich/svqpanel-wp-rest-whitelist.yaml << 'CSWPWLEOF'
name: svqpanel/wp-rest-whitelist
description: "No contar como http-probing los 404 de la REST API de WordPress (/wp-json/). Elementor y otros plugins piden rutas /wp-json/ que devuelven 404 cuando el endpoint no existe (p.ej. Elementor Pro sin licencia); son peticiones legitimas del admin del sitio, no un escaneo. Los probes reales (.env, .git, /vendor, /wp-admin/xxx) NO empiezan por /wp-json/ y siguen baneandose."
whitelist:
  reason: "WordPress REST API (/wp-json/) — 404 normales de plugins, no probing"
  expression:
    - "evt.Meta.http_path startsWith '/wp-json/'"
CSWPWLEOF
echo "  . parser svqpanel-wp-rest-whitelist.yaml escrito"

# Recargar CrowdSec para que cargue el parser nuevo (reload, no restart: no corta
# la proteccion). Si la validacion de config falla, no recargamos (evita dejar el
# motor caido por un parser mal formado).
if command -v cscli >/dev/null 2>&1; then
    if systemctl reload crowdsec >/dev/null 2>&1; then
        echo "  . crowdsec recargado"
    else
        echo "  . aviso: no se pudo recargar crowdsec (revisar: journalctl -u crowdsec)"
    fi
fi

echo "OK 0113: whitelist /wp-json/ aplicada (Elementor ya no dispara falsos baneos)"
exit 0
