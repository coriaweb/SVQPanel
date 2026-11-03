#!/bin/bash
# 0171-panel-vhost-limite-subida.sh
#
# Al emitir el SSL del panel, panel_ssl_manager reescribia el vhost del puerto
# del panel desde una plantilla SIN client_max_body_size (install.sh ponia 6g,
# pero se perdia). nginx aplicaba su 1 MB por defecto: phpMyAdmin rechazaba con
# 413 cualquier import de mas de 1 MB, igual que el gestor de archivos y los
# .tar de migracion. Tambien se perdian las cabeceras de seguridad, y /pma no
# tenia fastcgi_read_timeout (corta a los 60s en imports largos).
#
# Fix: las plantillas ya lo incluyen; aqui se parchea in situ el vhost existente
# (sin regenerarlo: conserva lo puesto a mano), con nginx -t y vuelta atras si
# falla. Respeta un client_max_body_size que ya exista. Idempotente.

set -u

if [ -x /opt/svqpanel/venv/bin/python ] && [ -f /etc/nginx/sites-available/svqpanel ]; then
    cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli fix_panel_vhost \
      && echo "✓ 0171: vhost del panel con limite de subida" \
      || echo "⚠ 0171: no se pudo parchear el vhost del panel"
fi
exit 0
