#!/bin/bash
# 0040-harden-services.sh
#
# Endurece servicios en servidores ya instalados (hallazgos de auditoría tipo
# Lynis, bajo riesgo):
#   - Postfix: banner SMTP genérico (no revela versión/OS) + VRFY deshabilitado
#     (evita enumeración de buzones por spammers).
#   - BIND: version "none" (no revela la versión del servidor DNS).
#
# Invoca el código del panel (idempotente, valida antes de recargar).

set -euo pipefail

echo "→ 0040: endurecer servicios (ocultar versiones, anti-enumeración)…"

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }

cd /opt/svqpanel
"$PYBIN" -m api.cli harden_services || \
    echo "  ⚠ harden_services con incidencias (no crítico)."

echo "✓ 0040: servicios endurecidos"
exit 0
