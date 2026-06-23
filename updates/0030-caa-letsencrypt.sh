#!/bin/bash
# 0030-caa-letsencrypt.sh
#
# Añade registros CAA (issue + issuewild "letsencrypt.org") a las zonas DNS ya
# existentes que no los tengan. CAA restringe qué autoridad de certificación
# puede emitir certs para el dominio; el panel emite todo con Let's Encrypt, así
# que esto no rompe renovaciones y bloquea emisiones de otras CAs (test NCSC CAA).
#
# Las zonas nuevas ya nacen con CAA (plantilla). Invoca el código del panel
# (idempotente: no duplica si la zona ya tiene CAA). Seguro de re-ejecutar.

set -euo pipefail

echo "→ 0030: añadir CAA (Let's Encrypt) a zonas DNS existentes…"

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }

cd /opt/svqpanel
"$PYBIN" -m api.cli backfill_caa || {
    echo "  ⚠ backfill_caa devolvió error (no crítico)."
    exit 0
}

echo "✓ 0030: CAA añadido a las zonas"
exit 0
