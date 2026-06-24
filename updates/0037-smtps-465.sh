#!/bin/bash
# 0037-smtps-465.sh
#
# Activa el puerto 465 (SMTPS, SSL/TLS directo) en Postfix, además del 587
# (STARTTLS) que ya existía. Los clientes de correo modernos (Thunderbird,
# Apple Mail, Outlook) prefieren SSL directo en 465; ofrecerlo hace que el
# autoconfig muestre "SSL/TLS" en el saliente (como cPanel/Hestia). Ambos
# cifran igual; el 587 se mantiene para compatibilidad.
#
# Idempotente. Solo en servidores con Postfix instalado.

set -euo pipefail

echo "→ 0037: activar SMTPS (puerto 465, SSL/TLS directo)…"

MASTER=/etc/postfix/master.cf
[ -f "$MASTER" ] || { echo "  Postfix no instalado — nada que hacer."; exit 0; }

if grep -qE "^smtps|^465" "$MASTER"; then
    echo "  Ya estaba activado el 465, nada que hacer."
    exit 0
fi

cat >> "$MASTER" << 'MASTEREOF'

smtps     inet  n       -       y       -       -       smtpd
  -o syslog_name=postfix/smtps
  -o smtpd_tls_wrappermode=yes
  -o smtpd_tls_security_level=encrypt
  -o smtpd_sasl_auth_enable=yes
  -o smtpd_reject_unlisted_recipient=no
  -o smtpd_recipient_restrictions=permit_sasl_authenticated,reject
  -o milter_macro_daemon_name=ORIGINATING
MASTEREOF

# El firewall ya abre el 465 (install.sh). Recargar Postfix para que escuche.
if postfix check 2>/dev/null; then
    systemctl reload postfix || systemctl restart postfix
    echo "✓ 0037: SMTPS (465) activado"
else
    echo "  ⚠ postfix check falló; revisar master.cf (no se recargó)."
    exit 1
fi

exit 0
