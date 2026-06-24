#!/bin/bash
# 0036-spam-learn-flag.sh
#
# Amplía el aprendizaje de spam para que funcione también cuando el cliente
# marca un correo con el FLAG Junk SIN moverlo (botón "Basura" de Thunderbird en
# algunas configuraciones). Antes solo se capturaba el movimiento a la carpeta
# Junk (Roundcube "marcar spam", arrastrar en Thunderbird). Ahora ambos hábitos
# entrenan el filtro.
#
# Reaplica la config (sieve nuevo learn-flag + IMAPSieve). Invoca el código del
# panel (idempotente). Seguro de re-ejecutar.

set -euo pipefail

echo "→ 0036: aprendizaje de spam también por flag Junk (Thunderbird)…"

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }

cd /opt/svqpanel
"$PYBIN" -m api.cli setup_spam_learning || \
    echo "  ⚠ setup_spam_learning con incidencias (no crítico)."

echo "✓ 0036: aprendizaje por flag activado"
exit 0
