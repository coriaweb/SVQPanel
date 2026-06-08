#!/bin/bash
# 0003-terminal-jail.sh
#
# Si el terminal web (ttyd) está instalado, regenera su launcher y construye la
# jaula chroot (jailkit) para las sesiones de cliente. Sin esto, tras actualizar
# a la versión con jaula, el launcher en /usr/local/bin seguía siendo el viejo
# (su - sin enjaular) y el cliente podía recorrer todo el árbol del servidor.
#
# Idempotente: terminal_manager.install() reescribe launcher/servicio/jaula; si
# ttyd no está instalado, no hace nada.

set -euo pipefail

PANEL_DIR="/opt/svqpanel"
PY="$PANEL_DIR/venv/bin/python"

echo "→ 0003: Terminal web — jaula chroot para clientes..."

if [[ ! -x /usr/local/bin/ttyd ]]; then
    echo "  ttyd no instalado — nada que hacer."
    exit 0
fi

# jailkit es necesario para la jaula chroot
if ! command -v jk_init >/dev/null 2>&1; then
    echo "  Instalando jailkit..."
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq jailkit 2>&1 | tail -2 || true
fi

# Reinstalar el terminal: reescribe el launcher (con jaula), el servicio systemd
# y construye/actualiza la jaula compartida.
cd "$PANEL_DIR"
"$PY" -c "from scripts import terminal_manager as tm; print(tm.install())" || {
    echo "  ✗ No se pudo reinstalar el terminal web"
    exit 1
}

# Verificar que la jaula quedó lista
if [[ -x /var/lib/svqpanel/jail/bin/bash ]]; then
    echo "  ✓ Jaula chroot construida en /var/lib/svqpanel/jail"
else
    echo "  ⚠ La jaula no se construyó (revisar jailkit)"
fi

echo "✓ 0003: Terminal web con jaula chroot aplicado"
exit 0
