#!/bin/bash
# 0104-optimize-wp-cron-flota.sh
#
# Optimiza el wp-cron de TODOS los WordPress de la flota que no lo tengan ya.
# Por defecto WordPress dispara el wp-cron EN CADA VISITA; con plugins de tareas
# frecuentes (WP Rocket, Action Scheduler, Jetpack...) eso causa picos de CPU
# aunque el trafico sea bajo. Se pasa a DISABLE_WP_CRON + cron de sistema cada
# 5 min. Idempotente: salta los que ya estan optimizados y los que no son WP.
#
# Invoca el CLI del panel (misma logica que el boton por dominio).

set -u

echo "-> 0104: optimizar wp-cron de todos los WordPress..."

if [ ! -x /opt/svqpanel/venv/bin/python ]; then
    echo "  . venv no encontrado; se omite"
    echo "OK 0104: sin cambios"
    exit 0
fi

cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli optimize_all_wp_cron 2>&1 | tail -1

echo "OK 0104: wp-cron optimizado en la flota"
exit 0
