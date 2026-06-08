#!/bin/bash
# 0006-terminal-jail-prompt.sh
#
# Cosmético: la terminal enjaulada mostraba el prompt feo 'bash-5.2$' porque la
# jaula no tenía /etc/profile. Ahora cada jaula de usuario lleva un profile con
# PS1 con color (usuario@svqpanel:~$), aliases (ll, la) y una bienvenida.
#
# Las jaulas de usuario se regeneran solas en la próxima sesión (prepare_user
# reescribe /etc en cada apertura), así que basta con actualizar el código (ya
# viene en el git pull) y reinstalar el launcher por consistencia. Idempotente.

set -euo pipefail

PANEL_DIR="/opt/svqpanel"
PY="$PANEL_DIR/venv/bin/python"

echo "→ 0006: Terminal web — prompt y bienvenida..."

if [[ ! -x /usr/local/bin/ttyd ]]; then
    echo "  ttyd no instalado — nada que hacer."
    exit 0
fi

cd "$PANEL_DIR"
"$PY" -c "from scripts import terminal_manager as tm; tm.install()" || {
    echo "  ✗ No se pudo reinstalar el terminal"; exit 1; }

echo "✓ 0006: Prompt de la terminal enjaulada aplicado"
exit 0
