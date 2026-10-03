#!/bin/bash
# 0158-quota-sync-arranque.sh
#
# Las cuentas creadas antes del primer reinicio quedaban SIN límite de disco.
#
# Las cuotas ext4 (user+group+project, modo interno) se activan en el PRIMER
# REINICIO tras el install (hook del initramfs; el feature project solo se
# activa con el FS desmontado). Las cuentas creadas antes de ese reinicio
# guardaban su límite en BD, pero setquota no podía aplicarlo y nadie lo
# reaplicaba después: quedaban ilimitadas hasta pulsar "aplicar cuota" una a
# una. Visto en el install limpio de svq-beyuri1 (oct 2026): el panel decía
# "las cuotas del sistema no están activas" y tras reiniciar el cliente seguía
# sin límite.
#
# Instala svqpanel-quota-sync.service (oneshot en cada arranque → api.cli
# sync_quotas: reaplica todas las cuotas y marca el correo con su project id)
# y lo ejecuta una vez ahora. Reflejado en install.sh. Idempotente.

set -u

echo "-> 0158: sincronizar cuotas de disco en cada arranque..."

if [ ! -x /opt/svqpanel/venv/bin/python ]; then
    echo "  . venv no encontrado; se omite"
    echo "OK 0158: sin cambios"
    exit 0
fi

cat > /etc/systemd/system/svqpanel-quota-sync.service << 'QSYNCEOF'
[Unit]
Description=SVQPanel — reaplica las cuotas de disco de todas las cuentas
After=local-fs.target postgresql.service
Wants=postgresql.service

[Service]
Type=oneshot
User=root
WorkingDirectory=/opt/svqpanel
ExecStart=/opt/svqpanel/venv/bin/python -m api.cli sync_quotas
TimeoutStartSec=600

[Install]
WantedBy=multi-user.target
QSYNCEOF

systemctl daemon-reload
systemctl enable svqpanel-quota-sync.service >/dev/null 2>&1 || true
echo "  OK svqpanel-quota-sync.service instalado y habilitado"

# Pasada inmediata (no esperar al próximo reinicio). Si falla alguna cuenta
# NO se aborta la cadena de updates: se informa y el arranque lo reintentará.
cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli sync_quotas 2>&1 \
    | grep -v -i warning | sed 's/^/  /' || true

echo "OK 0158: cuotas sincronizadas"
exit 0
