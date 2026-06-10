#!/bin/bash
# 0022-nginx-docs-api.sh
#
# Expone la documentación interactiva de la API (Swagger /docs, ReDoc /redoc y
# /openapi.json) a través del puerto del panel. El backend FastAPI ya las sirve
# en :8001, pero el vhost del panel solo proxeaba /api/, así que /docs caía en
# la SPA de Vue (página en blanco). install.sh ya genera estas locations en
# instalaciones nuevas; este update las inyecta en servidores ya instalados.
#
# Idempotente: no duplica si ya están. Valida con `nginx -t` y revierte si falla.

set -euo pipefail

echo "→ 0022: exponer /docs, /redoc y /openapi.json de la API..."

VHOST=/etc/nginx/sites-available/svqpanel
[ -f "$VHOST" ] || { echo "  Sin $VHOST (¿sin panel?) — nada que hacer."; exit 0; }

if grep -qE 'location\s*=?\s*/openapi\.json' "$VHOST"; then
    echo "  /docs ya expuesto — nada que hacer."
    exit 0
fi

# Anclar en la location del API y añadir las de docs justo antes (las locations
# de nginx son independientes del orden). Detectamos el puerto del backend del
# propio vhost para no hardcodear (proxy_pass a 8001 o al upstream nombrado).
BACKEND=$(grep -oE 'proxy_pass http://[^;]+' "$VHOST" | grep -E '8001|svqpanel_backend' | head -1 | sed 's#proxy_pass ##')
[ -n "$BACKEND" ] || BACKEND="http://127.0.0.1:8001"
# Normalizar: quitar posible /ruta final para componer las rutas de docs
BACKEND="${BACKEND%/}"

cp -a "$VHOST" "${VHOST}.bak-0022"

# Bloque a insertar (Swagger + ReDoc + OpenAPI), proxeado al backend.
read -r -d '' DOCS_BLOCK <<EOF || true
    # Documentación interactiva de la API (añadido por update 0022)
    location /docs {
        proxy_pass ${BACKEND}/docs;
        proxy_set_header Host \$host;
    }
    location /redoc {
        proxy_pass ${BACKEND}/redoc;
        proxy_set_header Host \$host;
    }
    location /openapi.json {
        proxy_pass ${BACKEND}/openapi.json;
        proxy_set_header Host \$host;
    }

EOF

# Insertar el bloque justo antes de la línea 'location /api/ {'
awk -v block="$DOCS_BLOCK" '
    /location \/api\/ \{/ && !done { print block; done=1 }
    { print }
' "$VHOST" > "${VHOST}.tmp" && mv "${VHOST}.tmp" "$VHOST"

if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx
    rm -f "${VHOST}.bak-0022"
    echo "  ✓ /docs, /redoc y /openapi.json expuestos (backend ${BACKEND}) y nginx recargado"
else
    mv "${VHOST}.bak-0022" "$VHOST"
    echo "  ✗ nginx -t falló; revertido. Revisa: nginx -t"
    exit 1
fi

echo "✓ 0022: documentación de la API expuesta"
exit 0
