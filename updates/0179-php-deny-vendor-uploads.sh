#!/bin/bash
# 0179-php-deny-vendor-uploads.sh
#
# Vhosts: nunca ejecutar por URL el PHP de vendor/ ni el de wp-content/uploads.
#
# 1) El anti-webshell de wp-content/uploads (`location ~* /wp-content/uploads/
#    .*\.php$ { deny all; }`) iba al FINAL del server de nginx, detrás del
#    `location ~ \.php$` de PHP-FPM. nginx usa el PRIMER regex que casa, así que
#    en modo solo-nginx un .php subido a uploads SE EJECUTABA: el deny no hacía
#    nada. Ahora va antes que cualquier bloque de PHP (PHP_DENY_BLOCK en
#    scripts/utils.py).
# 2) Nuevo: tampoco se ejecuta PHP de /vendor/ (a cualquier profundidad, p. ej.
#    el de un plugin). Las librerías Composer se cargan con require, nunca por
#    URL; llamarlas por URL es el vector clásico (phpunit eval-stdin.php,
#    CVE-2017-9841). El panel ya deja usar Composer en public_html/, así que
#    esto cierra ese vendor/ por defecto. Mismo bloqueo en Apache (LocationMatch).
#
# El fix está en el código del panel (traído por git pull); este update solo
# regenera los vhosts existentes. Un servidor nuevo nace con él (sin cambio en
# install.sh). Idempotente.

set -u

echo "-> 0179: denegar PHP en vendor/ y wp-content/uploads en los vhosts..."

if [ ! -x /opt/svqpanel/venv/bin/python ]; then
    echo "  . venv no encontrado; se omite"
    echo "OK 0179: sin cambios"
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

echo "OK 0179: PHP de vendor/ y uploads denegado por URL"
exit 0
