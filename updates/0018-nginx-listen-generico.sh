#!/bin/bash
# 0018-nginx-listen-generico.sh
#
# Los vhosts nginx ataban el listen a la IP del dominio (listen 185.x.x.x:80)
# cuando tenía ipv4 asignada. En un servidor de una sola IP eso hace que ESE
# vhost capture TODO el tráfico de la IP (listen con IP es más específico que el
# genérico) y rompe el enrutado por server_name → un dominio respondía por otro,
# y el acceso por IPv6 daba 404.
#
# El código nuevo genera siempre 'listen 80' / 'listen [::]:80' genérico. Este
# update REGENERA todos los vhosts existentes aplicando esa lógica, vía el código
# del panel (migrate_php_pools --force, que reescribe cada vhost preservando su
# estado). Idempotente.

set -euo pipefail

echo "→ 0018: Regenerar vhosts nginx con listen genérico..."

cd /opt/svqpanel || { echo "  /opt/svqpanel no existe"; exit 1; }

# Regenera pools + vhosts de todos los dominios con el código actual.
if /opt/svqpanel/venv/bin/python -m api.cli migrate_php_pools --force 2>&1 | tail -3; then
    echo "  vhosts regenerados"
else
    echo "  ⚠ migrate_php_pools devolvió error (revisa el log), continúo igual"
fi

# Validar y recargar nginx
if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx
    echo "  ✓ nginx recargado con la nueva configuración"
else
    echo "  ✗ nginx -t falló tras regenerar; NO recargo. Revisa: nginx -t"
    exit 1
fi

echo "✓ 0018: vhosts con listen genérico aplicado"
exit 0
