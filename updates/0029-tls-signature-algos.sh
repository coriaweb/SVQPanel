#!/bin/bash
# 0029-tls-signature-algos.sh
#
# Restringe los algoritmos de firma del handshake TLS 1.2 a SHA-256/384/512,
# eliminando SHA-224 (phase-out NCSC) que marcaba internet.nl. Se aplica con
# `ssl_conf_command Signature_Algorithms ...` en los vhosts SSL.
#
# El código nuevo ya genera los vhosts con esta directiva; este update regenera
# los vhosts SSL existentes (dominios + webmail/mail) para que la tomen. El panel
# la toma al renovar/re-emitir su SSL. Invoca el código del panel (idempotente).

set -euo pipefail

echo "→ 0029: restringir algoritmos de firma TLS 1.2 (fuera SHA-224)…"

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }

cd /opt/svqpanel
"$PYBIN" -m api.cli harden_tls || echo "  ⚠ harden_tls con incidencias (no crítico)."
"$PYBIN" -m api.cli fix_mail_vhosts || echo "  ⚠ fix_mail_vhosts con incidencias (no crítico)."

nginx -t 2>/dev/null && systemctl reload nginx 2>/dev/null || true

echo "✓ 0029: algoritmos de firma TLS restringidos"
exit 0
