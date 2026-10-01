#!/bin/bash
# 0155-apache-well-known.sh
#
# Deja de denegar /.well-known/* en los vhosts Apache (modo Apache+Nginx).
#
# El FilesMatch de ficheros ocultos (^\.) del vhost Apache denegaba con 403
# cualquier ruta virtual bajo /.well-known/: si la ruta no existe en disco,
# Apache evalúa el FilesMatch contra "public_html/.well-known" ANTES de aplicar
# el rewrite del .htaccess, así que la petición nunca llegaba a index.php.
# Visto en oct 2026 (gruposerbrillin.es): el plugin WordPress emcp-tools sirve
# /.well-known/oauth-authorization-server y oauth-protected-resource vía
# parse_request y su OAuth no funcionaba.
#
# El fix está en el código (generate_apache_vhost, ya traído por git pull):
# el patrón pasa a ^\.(?!well-known$). Siguen denegados .env, .git, .htaccess,
# los ocultos DENTRO de .well-known y las extensiones sensibles. Este update
# regenera los vhosts existentes. Idempotente.

set -u

echo "-> 0155: permitir /.well-known/ en los vhosts Apache..."

if [ ! -x /opt/svqpanel/venv/bin/python ]; then
    echo "  . venv no encontrado; se omite"
    echo "OK 0155: sin cambios"
    exit 0
fi

cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli regenerate_all_vhosts 2>&1 | tail -1

if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx >/dev/null 2>&1 || true
    echo "  OK nginx recargado"
else
    echo "  WARN nginx -t fallo; NO se recarga (revisar config)"
    nginx -t 2>&1 | tail -3
fi

if systemctl is-active apache2 >/dev/null 2>&1; then
    if apache2ctl configtest >/dev/null 2>&1; then
        systemctl reload apache2 >/dev/null 2>&1 || true
        echo "  OK apache recargado"
    else
        echo "  WARN apache configtest fallo; NO se recarga"
        apache2ctl configtest 2>&1 | tail -3
    fi
fi

echo "OK 0155: /.well-known/ ya llega a la aplicación en modo Apache"
exit 0
