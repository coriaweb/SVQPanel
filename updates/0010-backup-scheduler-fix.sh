#!/bin/bash
# 0010-backup-scheduler-fix.sh
#
# Dos fallos del planificador de backups:
#  1) El hilo del scheduler moría en su primera query con
#     InvalidRequestError('CronJob' failed to locate a name) porque no llamaba a
#     load_all_models() → NINGÚN backup programado se ejecutaba.
#  2) El cron se evaluaba en UTC, ignorando la zona horaria del panel
#     (settings.timezone, p. ej. Europe/Madrid) → los backups se disparaban con
#     el desfase horario.
#
# El fix está en el código (git pull lo trae). Este update solo reinicia el panel
# para que el hilo arranque con la corrección. Idempotente.

set -euo pipefail

echo "→ 0010: Arreglo del planificador de backups (load_all_models + zona horaria)..."

systemctl restart svqpanel
sleep 3
if systemctl is-active --quiet svqpanel; then
    echo "  ✓ Panel reiniciado; el scheduler ya respeta la zona horaria y no muere"
else
    echo "  ✗ El panel no arrancó — revisa: journalctl -u svqpanel -n 50"
    exit 1
fi

echo "✓ 0010: Planificador de backups corregido"
exit 0
