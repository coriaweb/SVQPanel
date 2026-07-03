#!/bin/bash
# 0103-wp-uploads-no-php.sh
#
# Bloquea la ejecucion de PHP en wp-content/uploads en TODOS los vhosts
# (anti-webshell WordPress). Un fichero .php subido a /uploads (tras una subida
# maliciosa por un plugin vulnerable) es el vector tipico de webshell; jamas debe
# ejecutarse. Se pone en el vhost (nginx Y Apache), NO en un .htaccess (que nginx
# puro ignora), igual que el bloqueo de .env/.git. Aplica a todos los dominios
# por defecto, sin depender de que el cliente lo active.
#
# El fix esta en el codigo (ya desplegado por git pull): generate_nginx_config y
# generate_apache_vhost. Este update regenera los vhosts existentes. Idempotente.

set -u

echo "-> 0103: bloquear PHP en wp-content/uploads (anti-webshell)..."

if [ ! -x /opt/svqpanel/venv/bin/python ]; then
    echo "  . venv no encontrado; se omite"
    echo "OK 0103: sin cambios"
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
    fi
fi

echo "OK 0103: PHP bloqueado en /uploads en todos los vhosts"
exit 0
