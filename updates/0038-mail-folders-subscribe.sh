#!/bin/bash
# 0038-mail-folders-subscribe.sh
#
# Hace que los clientes de correo (Thunderbird, Apple Mail…) muestren todas las
# carpetas especiales (Enviados/Borradores/Spam/Papelera), no solo Bandeja de
# Entrada y Papelera. Dos partes:
#   1) Drop-in 99-svqpanel-mailboxes.conf con auto=subscribe + special_use →
#      Dovecot crea y suscribe esas carpetas en los buzones NUEVOS.
#   2) fix_mail_folders suscribe las carpetas en los buzones YA existentes
#      (que nacieron con auto=no) y unifica la carpeta de spam a "Junk".
#
# Idempotente y no interactivo.

set -euo pipefail

echo "→ 0038: carpetas de correo visibles en Thunderbird…"

[ -d /etc/dovecot/conf.d ] || { echo "  Dovecot no instalado — nada que hacer."; exit 0; }

# 1) Drop-in para buzones nuevos (auto-crear + auto-suscribir).
cat > /etc/dovecot/conf.d/99-svqpanel-mailboxes.conf << 'DOVEMBOXEOF'
# SVQPanel: carpetas especiales auto-creadas y auto-suscritas (Thunderbird et al)
namespace inbox {
  mailbox Drafts {
    auto = subscribe
    special_use = \Drafts
  }
  mailbox Sent {
    auto = subscribe
    special_use = \Sent
  }
  mailbox Junk {
    auto = subscribe
    special_use = \Junk
  }
  mailbox Trash {
    auto = subscribe
    special_use = \Trash
  }
}
DOVEMBOXEOF

if doveconf -n >/dev/null 2>&1; then
    systemctl reload-or-restart dovecot || true
else
    echo "  ⚠ doveconf falló; revisar el drop-in (no se recargó dovecot)."
    exit 1
fi

# 2) Suscribir carpetas en los buzones existentes (invoca el código del panel).
PYBIN=/opt/svqpanel/venv/bin/python
if [ -x "$PYBIN" ]; then
    cd /opt/svqpanel
    "$PYBIN" -m api.cli fix_mail_folders || \
        echo "  ⚠ fix_mail_folders con incidencias (no crítico)."
fi

echo "✓ 0038: carpetas de correo suscritas"
exit 0
