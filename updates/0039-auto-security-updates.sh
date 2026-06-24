#!/bin/bash
# 0039-auto-security-updates.sh
#
# Activa las actualizaciones automáticas de SEGURIDAD del SO (unattended-upgrades)
# en servidores ya instalados: solo parches del repo de seguridad, sin reinicio
# automático (lo decide el admin). Gestionable desde Seguridad → Auto-actualiz.
#
# Invoca el código del panel (idempotente). Solo Debian.

set -euo pipefail

echo "→ 0039: actualizaciones automáticas de seguridad del SO…"

[ -f /etc/debian_version ] || { echo "  No es Debian — nada que hacer."; exit 0; }

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }

cd /opt/svqpanel
"$PYBIN" -m api.cli setup_auto_updates || \
    echo "  ⚠ setup_auto_updates con incidencias (no crítico)."

echo "✓ 0039: auto-actualizaciones de seguridad activadas"
exit 0
