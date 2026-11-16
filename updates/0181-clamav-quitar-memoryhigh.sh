#!/bin/bash
# 0181-clamav-quitar-memoryhigh.sh
#
# El drop-in de memoria de clamd (0126 / install.sh) ponia MemoryHigh=700M +
# MemoryMax=900M. La idea era que systemd lo matara y reiniciara si se
# descontrolaba, pero MemoryHigh NO mata: ESTRANGULA. Y la base de firmas ha
# crecido (3,6 M de firmas): clamd necesita ~1,3 GB solo para estar en reposo.
#
# Resultado, visto en produccion (.71, 8 GB de RAM y casi 3 GB libres):
#   - clamd permanentemente por encima de MemoryHigh -> el kernel lo frena sin
#     parar: 88% del tiempo parado esperando memoria, medio GB empujado a swap.
#   - 2 hilos de clamd fijos en estado D, que Linux cuenta como carga: load
#     base de 2-3 con la CPU libre -> alertas de "Carga alta" con cualquier pico.
#   - El antivirus inservible: escanear un fichero de pocos bytes no respondia
#     en 3 minutos.
#
# FIX: fuera MemoryHigh. Queda solo un techo duro MemoryMax=2G (holgado sobre lo
# que clamd usa de verdad; solo salta si se desboca) + Restart=on-failure.
#
# Reflejado tambien en install.sh. Idempotente y no interactivo.

set -u

echo "-> 0181: ClamAV sin MemoryHigh (estrangulaba a clamd)..."

DROPIN=/etc/systemd/system/clamav-daemon.service.d/99-svqpanel-memory.conf

command -v clamd >/dev/null 2>&1 || dpkg -l clamav-daemon 2>/dev/null | grep -q '^ii' || {
    echo "  . ClamAV no instalado; nada que hacer."
    exit 0
}

if [ -f "$DROPIN" ] && ! grep -q '^MemoryHigh' "$DROPIN" && grep -q '^MemoryMax=2G$' "$DROPIN"; then
    echo "  . el drop-in ya estaba corregido."
    exit 0
fi

mkdir -p "$(dirname "$DROPIN")"
cat > "$DROPIN" << 'EOF'
# SVQPanel: techo de RAM y reinicio automático de clamd.
# clamd carga sus firmas en RAM (~1,3 GB). La unit de Debian trae Restart=no: si
# el OOM killer lo mata se queda MUERTO sin avisar y el correo deja de escanearse.
# OJO: NO poner MemoryHigh. No mata, estrangula: por debajo de lo que clamd
# necesita lo deja parado esperando memoria e infla la carga del servidor (0181).
[Service]
# Techo duro: si lo supera, lo mata systemd (que sí lo reinicia), no el OOM del kernel.
MemoryMax=2G
Restart=on-failure
RestartSec=30s
EOF
systemctl daemon-reload
echo "  . drop-in reescrito: MemoryMax=2G, sin MemoryHigh"

# Reiniciar solo si estaba en marcha (no arrancar un antivirus que el admin paró).
if systemctl is-active --quiet clamav-daemon; then
    systemctl restart clamav-daemon >/dev/null 2>&1 || true
    echo "  . clamav-daemon reiniciado (tarda 1-2 min en cargar las firmas)"
fi

echo "OK 0181: clamd ya no queda estrangulado por MemoryHigh."
exit 0
