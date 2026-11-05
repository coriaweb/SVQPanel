#!/bin/bash
# 0176-bienvenida-sin-cuelgue.sh
#
# La página de bienvenida (default_server del 80 y del 443) usaba
# `try_files $uri $uri/ =200;`: cualquier ruta que no existiera se quedaba
# colgada hasta el timeout. Lo típico: https://hostname-del-panel/login sin el
# puerto del panel (visto en .71).
#
# Fix (código del panel, `api.cli fix_panel_vhost` → patch_welcome_fallback):
# el hostname del panel por HTTPS redirige a su puerto y lo demás da 404.
# Parchea /etc/nginx/sites-available/svqpanel y svqpanel-welcome, valida con
# nginx -t y restaura si falla. Reflejado en install.sh y en la plantilla del
# SSL del panel. Idempotente.

set -u

if [ -x /opt/svqpanel/venv/bin/python ] && command -v nginx >/dev/null 2>&1; then
    cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli fix_panel_vhost \
      && echo "✓ 0176: la bienvenida ya no deja colgadas las rutas inexistentes" \
      || echo "⚠ 0176: no se pudo parchear la bienvenida (sigue como estaba)"
fi
exit 0
