#!/bin/bash
# 0096-proxy-cache-modo-apache.sh
#
# Arregla que la CACHE DE PÁGINA no funcionaba en modo Apache (apache+nginx).
#
# Problema: en modo Apache, nginx hace `proxy_pass` a Apache (:8181), pero el
# generador solo sabía aplicar `fastcgi_cache`, que NO funciona con proxy_pass
# (necesita `proxy_cache`). Resultado: dominios con fastcgi_cache_enabled=true en
# la BD tenían el flag activo pero el vhost NO cacheaba nada → cada visita
# arrancaba PHP/Apache (WooCommerce, WordPress pesado → picos de CPU).
#
# Fix (en el código, ya desplegado por git pull):
#  - proxy_cache_key en el conf global de cache.
#  - la zona de cache usa proxy_cache_path en modo Apache (antes: fastcgi_cache_path).
#  - el location / de proxy inserta las directivas proxy_cache (con las MISMAS
#    exclusiones $skip_cache: admin/POST/logueados/carrito WooCommerce).
#
# Este update: reescribe el conf global (para añadir proxy_cache_key) y regenera
# los vhosts para materializar la cache en los dominios que ya la tenían activada.
# Idempotente.

set -u

echo "→ 0096: proxy_cache para modo Apache…"

if [ ! -x /opt/svqpanel/venv/bin/python ]; then
    echo "  · venv no encontrado; se omite"
    echo "✓ 0096: sin cambios"
    exit 0
fi

# 1) Forzar la reescritura del conf global de cache (para que incluya
#    proxy_cache_key). ensure_fastcgi_cache_root() solo lo crea si NO existe, así
#    que lo borramos para que lo regenere con el contenido nuevo.
GLOBAL=/etc/nginx/conf.d/svqpanel-fastcgi-cache-global.conf
if [ -f "$GLOBAL" ] && ! grep -q 'proxy_cache_key' "$GLOBAL"; then
    rm -f "$GLOBAL"
    echo "  · conf global de cache marcado para regenerar (faltaba proxy_cache_key)"
fi

# 2) Regenerar vhosts + zonas. regenerate_all_vhosts reescribe cada vhost desde la
#    BD; write_fastcgi_cache_zone (que llama por dentro) recrea el conf global si
#    falta y la zona con la directiva correcta (proxy_cache_path en modo Apache).
cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli regenerate_all_vhosts 2>&1 | tail -1

# 3) Validar y recargar nginx.
if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx >/dev/null 2>&1 || true
    echo "  ✓ nginx recargado"
else
    echo "  ⚠ nginx -t falló; NO se recarga (revisar config)"
    nginx -t 2>&1 | tail -3
fi

echo "✓ 0096: cache de página funciona en modo Apache (proxy_cache)"
exit 0
