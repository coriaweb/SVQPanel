#!/bin/bash
# 0008-backup-scheduler-interno.sh
#
# Los backups programados los lanzaba un timer systemd cada minuto, que arrancaba
# un proceso Python ENTERO (carga FastAPI + SQLAlchemy, ~1s CPU) 1440 veces/día
# para comprobar si tocaba algún backup — casi siempre "0 jobs". Eso saturaba el
# log (Starting/Finished/Deactivated cada minuto) y gastaba CPU.
#
# Ahora lo gestiona un hilo de fondo DENTRO del panel (api/main.py startup →
# scripts/backup_scheduler.py), sin arrancar nada nuevo. La fuga de memoria que
# motivó el timer ya está resuelta (imports a nivel de módulo). Este update
# retira el timer y reinicia el panel para que arranque el hilo. Idempotente.

set -euo pipefail

echo "→ 0008: Backups programados al hilo interno (sin timer cada minuto)..."

# Retirar el timer + servicio systemd antiguos
systemctl disable --now svqpanel-backup-scheduler.timer 2>/dev/null || true
systemctl stop svqpanel-backup-scheduler.service 2>/dev/null || true
rm -f /etc/systemd/system/svqpanel-backup-scheduler.timer \
      /etc/systemd/system/svqpanel-backup-scheduler.service 2>/dev/null || true
systemctl daemon-reload 2>/dev/null || true

# Reiniciar el panel para que arranque el hilo interno del scheduler
systemctl restart svqpanel
sleep 2
if systemctl is-active --quiet svqpanel; then
    echo "  ✓ Panel reiniciado; backup scheduler corre como hilo interno"
else
    echo "  ✗ El panel no arrancó — revisa: journalctl -u svqpanel -n 50"
    exit 1
fi

echo "✓ 0008: Backup scheduler interno aplicado (timer retirado)"
exit 0
