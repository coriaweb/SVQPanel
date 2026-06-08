#!/bin/bash
# 0007-terminal-jail-hidepid.sh
#
# Seguridad: la jaula del terminal montaba /proc sin hidepid, así que un cliente
# podía ver con `ps aux` TODOS los procesos del servidor (de otros clientes y del
# sistema), incluyendo a veces credenciales en los argumentos. Ahora /proc se
# monta con hidepid=2: cada cliente solo ve SUS propios procesos.
#
# Desmonta los /proc de las jaulas de usuario para que se remonten con hidepid en
# la próxima sesión, y reinstala el launcher. Idempotente.

set -euo pipefail

PANEL_DIR="/opt/svqpanel"
PY="$PANEL_DIR/venv/bin/python"

echo "→ 0007: Terminal web — /proc con hidepid (ocultar procesos de otros)..."

if [[ ! -x /usr/local/bin/ttyd ]]; then
    echo "  ttyd no instalado — nada que hacer."
    exit 0
fi

# Remontar los /proc existentes de las jaulas de usuario con hidepid=2
if [[ -d /var/lib/svqpanel/jails ]]; then
    grep -oE '/var/lib/svqpanel/jails/[^ ]*/proc' /proc/mounts | while read -r mp; do
        umount "$mp" 2>/dev/null || umount -l "$mp" 2>/dev/null || true
        mount -t proc proc "$mp" -o hidepid=2 2>/dev/null || true
        echo "  remontado $mp con hidepid=2"
    done
fi

cd "$PANEL_DIR"
"$PY" -c "from scripts import terminal_manager as tm; tm.install()" >/dev/null || {
    echo "  ✗ No se pudo reinstalar el terminal"; exit 1; }

echo "✓ 0007: /proc de las jaulas con hidepid aplicado"
exit 0
