#!/bin/bash
# 0023-sync-panel-ssl.sh
#
# Repara el estado del SSL del panel en la BD. En instalaciones donde el cert se
# emitió correctamente (install) pero settings quedó con ssl_panel_enabled=false,
# la UI mostraba "Sin SSL" pese a servirse por HTTPS, y el panel no podía avisar
# de la caducidad. Este update refleja en la BD el cert real.
#
# Invoca el código del panel (idempotente y seguro: NO emite ni renueva, solo
# sincroniza el estado). Si no hay cert, no hace nada.

set -euo pipefail

echo "→ 0023: sincronizar estado SSL del panel en la BD…"

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }

cd /opt/svqpanel
"$PYBIN" -m api.cli sync_panel_ssl || {
    echo "  ⚠ sync_panel_ssl devolvió error (no crítico)."
    exit 0
}

echo "✓ 0023: estado SSL del panel sincronizado"
exit 0
