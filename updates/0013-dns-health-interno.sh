#!/bin/bash
# 0013-dns-health-interno.sh
#
# El chequeo de salud del cluster DNS lo hacía un timer systemd cada 10 min que
# arrancaba un proceso Python entero, incluso cuando NO hay cluster configurado
# (logueaba "Sin cluster DNS configurado; nada que comprobar" cada 10 min).
# Ahora lo hace el hilo interno del panel (scripts/metrics_scheduler.py), que
# salta en silencio si no hay cluster. Este update retira el timer. Idempotente.

set -euo pipefail

echo "→ 0013: Salud del cluster DNS al hilo interno (sin timer cada 10 min)..."

systemctl disable --now svqpanel-dns-cluster-health.timer 2>/dev/null || true
systemctl stop svqpanel-dns-cluster-health.service 2>/dev/null || true
rm -f /etc/systemd/system/svqpanel-dns-cluster-health.timer \
      /etc/systemd/system/svqpanel-dns-cluster-health.service 2>/dev/null || true
systemctl daemon-reload 2>/dev/null || true

systemctl restart svqpanel
sleep 2
if systemctl is-active --quiet svqpanel; then
    echo "  ✓ Panel reiniciado; salud DNS como hilo interno"
else
    echo "  ✗ El panel no arrancó — revisa: journalctl -u svqpanel -n 50"
    exit 1
fi

echo "✓ 0013: Salud del cluster DNS interna (timer retirado)"
exit 0
