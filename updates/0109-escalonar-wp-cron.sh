#!/bin/bash
# 0109-escalonar-wp-cron.sh
#
# Los wp-cron de la flota se crearon todos con minuto '*/5' -> los N WordPress
# arrancan su wp-cron EN EL MISMO MINUTO (0,5,10,15...) y despiertan decenas de
# procesos PHP a la vez -> pico de load sincronizado (thundering herd), visto
# subiendo a >5 en un servidor de 4 nucleos.
#
# Fix: cada dominio pasa a un minuto ESCALONADO por su id (cada 10 min, repartido
# a lo largo del reloj), en vez de '*/5' fijo. Misma frecuencia efectiva por
# dominio pero los arranques se reparten -> sin pico. Sube el intervalo de 5 a 10
# min (mas margen de CPU; el retraso es imperceptible salvo emails/posts muy al
# minuto). Reescribe tanto el CronJob del panel como el crontab del usuario.
#
# Invoca el CLI del panel (misma logica que el codigo). Idempotente: los que ya
# esten en su minuto correcto no se tocan.

set -u

echo "-> 0109: escalonar wp-cron de la flota (evitar pico de load)..."

if [ ! -x /opt/svqpanel/venv/bin/python ]; then
    echo "  . venv no encontrado; se omite"
    echo "OK 0109: sin cambios"
    exit 0
fi

cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli restagger_wp_cron 2>&1 | tail -2

echo "OK 0109: wp-cron escalonado en la flota"
exit 0
