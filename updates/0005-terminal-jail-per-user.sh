#!/bin/bash
# 0005-terminal-jail-per-user.sh
#
# La jaula del terminal era COMPARTIDA: los homes de los clientes que abrían
# terminal quedaban bind-montados en /var/lib/svqpanel/jail/home/, así que un
# cliente veía los NOMBRES de los demás en /home (fuga de información, aunque no
# pudiera entrar). Ahora cada usuario tiene su PROPIA jaula
# (/var/lib/svqpanel/jails/<user>) que solo contiene su home.
#
# Este update desmonta y elimina la jaula compartida antigua, reconstruye la
# plantilla y reinstala el launcher (que ya usa el módulo por-usuario).
# Idempotente. Solo actúa si ttyd está instalado.

set -euo pipefail

PANEL_DIR="/opt/svqpanel"
PY="$PANEL_DIR/venv/bin/python"

echo "→ 0005: Terminal web — jaula por usuario..."

if [[ ! -x /usr/local/bin/ttyd ]]; then
    echo "  ttyd no instalado — nada que hacer."
    exit 0
fi

# Desmontar todo lo que cuelgue de la jaula compartida antigua y eliminarla.
if [[ -d /var/lib/svqpanel/jail ]]; then
    echo "  Limpiando jaula compartida antigua..."
    # Desmontar en orden inverso de profundidad para evitar 'target is busy'
    grep -oE '/var/lib/svqpanel/jail[^ ]*' /proc/mounts | sort -r | while read -r mp; do
        umount "$mp" 2>/dev/null || umount -l "$mp" 2>/dev/null || true
    done
    rm -rf /var/lib/svqpanel/jail/home/* 2>/dev/null || true
fi

cd "$PANEL_DIR"

# Reconstruir la plantilla (solo binarios) + reinstalar launcher
"$PY" -c "from scripts import terminal_jail as tj; print(tj.build_jail())" || {
    echo "  ✗ No se pudo reconstruir la plantilla de la jaula"; exit 1; }
"$PY" -c "from scripts import terminal_manager as tm; tm.install()" || {
    echo "  ✗ No se pudo reinstalar el terminal"; exit 1; }

echo "✓ 0005: Terminal web con jaula por usuario aplicado"
exit 0
