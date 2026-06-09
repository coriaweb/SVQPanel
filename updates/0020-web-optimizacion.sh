#!/bin/bash
# 0020-web-optimizacion.sh
#
# Optimización de velocidad de las webs:
#  1. gzip GLOBAL en nginx (venía comentado por defecto → las webs NO se
#     comprimían). Acelera HTML/CSS/JS/JSON ~65%.
#  2. Regenera los vhosts para añadir cache de navegador (expires 30d) en los
#     estáticos (CSS/JS/imágenes/fuentes), vía migrate_php_pools --force.
# Idempotente.

set -euo pipefail

echo "→ 0020: Optimización web (gzip global + cache de estáticos)..."

[ -d /etc/nginx/conf.d ] || { echo "  Sin nginx — nada que hacer."; exit 0; }

# 1) gzip global
if [ ! -f /etc/nginx/conf.d/svqpanel-gzip.conf ]; then
    cat > /etc/nginx/conf.d/svqpanel-gzip.conf << 'EOF'
# SVQPanel — compresión gzip global (todas las webs)
gzip on;
gzip_vary on;
gzip_proxied any;
gzip_comp_level 5;
gzip_min_length 256;
gzip_types
    text/plain text/css text/xml text/javascript
    application/javascript application/x-javascript application/json
    application/xml application/xml+rss application/rss+xml
    application/atom+xml application/vnd.ms-fontobject
    application/x-font-ttf font/opentype image/svg+xml image/x-icon;
EOF
    echo "  gzip global activado"
else
    echo "  gzip ya estaba configurado"
fi

# 2) Si hay Apache (modo dual), activar mod_expires para la cache de estáticos.
if command -v a2enmod >/dev/null 2>&1; then
    a2enmod expires >/dev/null 2>&1 && systemctl reload apache2 2>/dev/null || true
    echo "  mod_expires activado en Apache (modo dual)"
fi

# 3) Regenerar vhosts (añade el bloque de cache de estáticos del código nuevo,
#    tanto en nginx-puro como en Apache+nginx).
cd /opt/svqpanel || exit 1
/opt/svqpanel/venv/bin/python -m api.cli migrate_php_pools --force 2>&1 | tail -2 || \
    echo "  ⚠ migrate_php_pools devolvió error (revisa el log), continúo"

# 3) Validar y recargar
if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx
    echo "  ✓ nginx recargado (gzip + cache de estáticos activos)"
else
    echo "  ✗ nginx -t falló; NO recargo. Revisa: nginx -t"
    exit 1
fi

echo "✓ 0020: optimización web aplicada"
exit 0
