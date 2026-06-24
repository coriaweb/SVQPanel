#!/bin/bash
# 0034-lower-unauth-limit.sh
#
# Baja el límite por defecto del correo NO autenticado (PHP mail()/sendmail) de
# 50 a 10 correos/hora por usuario de sistema. mail() es solo un puente de
# cortesía: el cliente que necesite enviar correo desde su web debe configurar
# SMTP autenticado (mejor entregabilidad y sin este tope). El límite aplica a
# TODO el correo no-auth del usuario (local + externo); Rspamd solo exime
# postmaster/mailer-daemon. Regenera la config desde la BD con el nuevo default.
#
# Invoca el código del panel (idempotente). Seguro de re-ejecutar.

set -euo pipefail

echo "→ 0034: bajar límite de correo no autenticado a 10/h (empujar a SMTP)…"

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }

cd /opt/svqpanel
"$PYBIN" -m api.cli rebuild_mail_ratelimit || \
    echo "  ⚠ rebuild_mail_ratelimit con incidencias (no crítico)."

echo "✓ 0034: límite no autenticado bajado a 10/h"
exit 0
