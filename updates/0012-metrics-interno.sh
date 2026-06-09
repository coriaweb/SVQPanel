#!/bin/bash
# 0012-metrics-interno.sh
#
# El muestreo de métricas lo hacía un timer systemd cada 5 min que arrancaba un
# proceso Python entero (~1.4s CPU) 288 veces/día → ruido en el log
# (Starting/Finished/Consumed + "metrics sample: ..." cada vez). Ahora lo hace
# un hilo de fondo dentro del panel (scripts/metrics_scheduler.py), como el
# backup scheduler. Este update retira el timer y reinicia el panel para que
# arranque el hilo. Idempotente.

set -euo pipefail

echo "→ 0012: Métricas al hilo interno (sin timer cada 5 min)..."

systemctl disable --now svqpanel-metrics.timer 2>/dev/null || true
systemctl stop svqpanel-metrics.service 2>/dev/null || true
rm -f /etc/systemd/system/svqpanel-metrics.timer \
      /etc/systemd/system/svqpanel-metrics.service 2>/dev/null || true
systemctl daemon-reload 2>/dev/null || true

systemctl restart svqpanel
sleep 2
if systemctl is-active --quiet svqpanel; then
    echo "  ✓ Panel reiniciado; métricas como hilo interno"
else
    echo "  ✗ El panel no arrancó — revisa: journalctl -u svqpanel -n 50"
    exit 1
fi

echo "✓ 0012: Muestreo de métricas interno (timer retirado)"
exit 0
