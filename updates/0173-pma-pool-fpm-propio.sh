#!/bin/bash
# 0173-pma-pool-fpm-propio.sh
#
# phpMyAdmin usaba el pool `www` compartido y el ajuste de webmail
# (conf.d/zz-svqpanel-webmail.ini, global a esa version de PHP) le bajaba la
# subida a 35 MB: importar un .sql de 80 MB fallaba con "Probablemente intento
# cargar un archivo demasiado grande" (Oskarbi, api-prod, 4-nov-2026).
#
# Fix: pool propio `svqpanel-pma` (www-data, ondemand, 1G de subida, 600s) en
# /run/php/svqpanel-pma.sock y el location /pma del vhost del panel apuntando a
# el. Todo con el codigo del panel (scripts/pma_fpm.py + fix_panel_vhost):
# valida php-fpm -t y nginx -t y vuelve atras si fallan. Sin phpMyAdmin no hace
# nada. install.sh lo aplica al ejecutar los updates. Idempotente.

set -u

if [ -x /opt/svqpanel/venv/bin/python ] && [ -d /var/www/pma ]; then
    cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli pma_fpm \
      && echo "✓ 0173: phpMyAdmin con pool PHP-FPM propio" \
      || echo "⚠ 0173: no se pudo crear el pool de phpMyAdmin (sigue en el compartido)"
fi
exit 0
