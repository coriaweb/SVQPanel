#!/bin/bash
# 0172-pma-redireccion-sin-cache.sh
#
# phpMyAdmin fija session_cache_limiter('private'): su redireccion al login
# (sesion caducada) sale con "Cache-Control: private, max-age=10800" y el
# navegador la guardaba 3 horas. Aunque se volviera a entrar bien desde el
# panel, pulsar «Importar» seguia saltando al login sin llegar al servidor
# (Oskarbi, api-prod, 4-nov-2026).
#
# Fix: en el location PHP de /pma nginx quita Cache-Control/Expires de PHP y
# pone no-store (repitiendo las cabeceras de seguridad, que un add_header en el
# location anula). Las plantillas ya lo llevan; aqui se parchea in situ el
# vhost existente con el mismo `api.cli fix_panel_vhost` del 0171 (nginx -t y
# vuelta atras si falla). Idempotente.

set -u

if [ -x /opt/svqpanel/venv/bin/python ] && [ -f /etc/nginx/sites-available/svqpanel ]; then
    cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli fix_panel_vhost \
      && echo "✓ 0172: /pma sin cache en las redirecciones" \
      || echo "⚠ 0172: no se pudo parchear el vhost del panel"
fi
exit 0
