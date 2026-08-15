#!/bin/bash
# 0137 — El reto ACME queda EXENTO de las redirecciones del vhost.
#
# Bug: con el dominio canónico activado (www / non-www) el vhost hace
#   if ($host = dominio.com) { return 301 $scheme://www.dominio.com$request_uri; }
# que redirige TAMBIÉN el reto de Let's Encrypt. Certbot valida cada
# identificador en su propio nombre, así que el reto de la variante NO canónica
# aterrizaba en la canónica, donde ese token no existe → 404 y la emisión de SSL
# fallaba ("Invalid response … /.well-known/acme-challenge/…: 404").
# El mismo problema afectaba al bloque force_https (return 301 https://$host),
# que mandaba el reto a HTTPS y rompía las RENOVACIONES automáticas.
#
# Fix: un map global define $canonical_redirect = "" durante el reto ACME (y
# $host en el resto), de modo que el `if` del canónico no entra durante la
# validación. Hace falta un map y no un `location` porque en nginx los `if` de
# la fase rewrite se evalúan ANTES que cualquier location.
#
# Idempotente: crea el map si falta y regenera los vhosts desde la BD.
set -e

PANEL_DIR="/opt/svqpanel"
VENV_PY="${PANEL_DIR}/venv/bin/python"
ACME_CONF="/etc/nginx/conf.d/svqpanel-acme-exempt.conf"

command -v nginx >/dev/null 2>&1 || { echo "0137: nginx no instalado, se omite"; exit 0; }

# 1) El map global. DEBE existir antes de regenerar los vhosts: si un vhost
#    referencia $canonical_redirect y el map no está, nginx NO arranca y se
#    quedarían caídos TODOS los dominios.
if [[ ! -f "$ACME_CONF" ]]; then
    mkdir -p /etc/nginx/conf.d
    cat > "$ACME_CONF" << 'NGINXACMEEOF'
# SVQPanel — exime el reto ACME de las redirecciones (nivel http)
# $canonical_redirect = "" durante /.well-known/acme-challenge/, si no = $host.
# Lo usan los vhosts para no redirigir la validación de Let's Encrypt: un 301
# del reto rompe la emisión (404 del token) y la renovación automática.
map $request_uri $canonical_redirect {
    ~^/\.well-known/acme-challenge/  "";
    default                          $host;
}
NGINXACMEEOF
    echo "  ✓ map \$canonical_redirect creado"

    # Si el map deja nginx en mal estado, revertir: es preferible quedarse sin
    # el fix que dejar el webserver sin arrancar.
    if ! nginx -t >/dev/null 2>&1; then
        rm -f "$ACME_CONF"
        echo "0137: nginx -t falló con el map; revertido y se omite"
        exit 0
    fi
else
    echo "  Ya existía el map, nada que crear."
fi

# 2) Regenerar los vhosts para que usen la exención. Sin esto los dominios ya
#    creados seguirían con el `if ($host = …)` viejo que redirige el reto.
if [[ -x "$VENV_PY" ]]; then
    cd "$PANEL_DIR"
    "$VENV_PY" -m api.cli regenerate_all_vhosts || \
        echo "  ⚠ no se pudieron regenerar todos los vhosts"
fi

# 3) Recargar solo si la config es válida.
if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx 2>/dev/null || true
    echo "  ✓ nginx recargado"
else
    echo "  ⚠ nginx -t falla tras regenerar: NO se recarga (revisar a mano)"
fi

exit 0
