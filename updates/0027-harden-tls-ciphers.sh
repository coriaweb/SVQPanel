#!/bin/bash
# 0027-harden-tls-ciphers.sh
#
# Endurece la política TLS de los vhosts: cifrados AEAD modernos (ECDHE + GCM/
# CHACHA20) y `ssl_prefer_server_ciphers on`, eliminando los cifrados débiles/
# obsoletos (CBC, Camellia, ARIA, CCM_8) que marcaban tests como internet.nl /
# NCSC-NL. El código nuevo ya genera los vhosts así; este update REGENERA los
# vhosts SSL de los dominios ya existentes para que tomen la política nueva.
#
# Invoca el código del panel (idempotente, preserva el resto del estado del
# dominio). El correo/webmail/panel toman la política al regenerarse o renovar
# su SSL. Seguro de re-ejecutar.

set -euo pipefail

echo "→ 0027: endurecer cifrados TLS de los vhosts SSL…"

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }

cd /opt/svqpanel
"$PYBIN" -m api.cli harden_tls || {
    echo "  ⚠ harden_tls devolvió error (no crítico)."
    exit 0
}

# Recargar nginx para aplicar (el regenerador ya valida, pero por si acaso).
nginx -t 2>/dev/null && systemctl reload nginx 2>/dev/null || true

echo "✓ 0027: cifrados TLS endurecidos"
exit 0
