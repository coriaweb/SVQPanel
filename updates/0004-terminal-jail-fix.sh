#!/bin/bash
# 0004-terminal-jail-fix.sh
#
# Corrige la terminal web enjaulada de clientes:
#  - faltaban binarios básicos en la jaula (whoami, id, find, head, tail…),
#  - faltaba /dev/pts + /proc + /dev/ptmx → la shell interactiva de ttyd se
#    cerraba al instante ("Press Enter to Reconnect"),
#  - jk_chrootlaunch no conectaba bien el pseudo-terminal → se sustituye por
#    `chroot --userspec` directo (lo hace terminal_jail con el código nuevo).
#
# Reconstruye la jaula y reinstala el launcher. Idempotente. Solo actúa si ttyd
# está instalado.

set -euo pipefail

PANEL_DIR="/opt/svqpanel"
PY="$PANEL_DIR/venv/bin/python"

echo "→ 0004: Arreglo de la terminal web enjaulada..."

if [[ ! -x /usr/local/bin/ttyd ]]; then
    echo "  ttyd no instalado — nada que hacer."
    exit 0
fi

command -v jk_init >/dev/null 2>&1 || {
    echo "  Instalando jailkit..."
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq jailkit 2>&1 | tail -1 || true
}

cd "$PANEL_DIR"

# Reconstruir la jaula (añade binarios que faltaban + /dev/pts + /proc + ptmx)
"$PY" -c "from scripts import terminal_jail as tj; print(tj.build_jail())" || {
    echo "  ✗ No se pudo reconstruir la jaula"; exit 1; }

# Reinstalar el launcher (usa chroot directo en vez de jk_chrootlaunch)
"$PY" -c "from scripts import terminal_manager as tm; tm.install()" || {
    echo "  ✗ No se pudo reinstalar el terminal"; exit 1; }

if [[ -x /var/lib/svqpanel/jail/bin/bash ]]; then
    echo "  ✓ Jaula reconstruida y launcher actualizado"
fi

echo "✓ 0004: Terminal web enjaulada corregida"
exit 0
