#!/bin/bash
# 0170-cron-wrapper-sin-solapes.sh
#
# El wrapper svq-cron-run no impedia que una ejecucion de un cron arrancara
# mientras la anterior seguia viva. En un servidor que empieza a tirar de swap,
# cada wp-cron tarda mas que su intervalo, se solapan tandas y cada una pide mas
# RAM: bola de nieve (svq-beyuri1, 29-oct: 118 wp-cron vivos, swap al 100 %,
# load 200 y el OOM matando MariaDB/ClamAV/el panel).
#
# Fix: el wrapper toma un cerrojo por cron (flock no bloqueante en
# ~/.svq-cron, o /tmp si el home no es escribible); si esta cogido, esa
# ejecucion se omite y queda anotada en el historial. Reinstala el wrapper con
# el codigo del panel (install.sh lo instala aplicando los updates). Idempotente.

set -u

if [ -x /opt/svqpanel/venv/bin/python ]; then
    cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -c \
      "from scripts.cron_manager import install_cron_wrapper; install_cron_wrapper()" \
      && echo "✓ 0170: wrapper svq-cron-run con cerrojo por cron" \
      || echo "⚠ 0170: no se pudo reinstalar el wrapper"
fi
exit 0
