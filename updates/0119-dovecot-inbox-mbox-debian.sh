#!/bin/bash
# 0119-dovecot-inbox-mbox-debian.sh
#
# BUG: en Debian 13 (Dovecot 2.4) el webmail/IMAP daba error SOLO en la BANDEJA DE
# ENTRADA ("Failed to autocreate mailbox: Permission denied" / "Internal error" en
# Roundcube), mientras que Enviados/Archive/etc. si funcionaban. Causa: el paquete
# de Dovecot 2.4 en Debian trae en 10-mail.conf su config MBOX por defecto ACTIVA:
#   mail_driver = mbox
#   mail_path = %{home}/mail
#   mail_inbox_path = /var/mail/%{user}
# Esa config CONVIVE con la de SVQPanel (mail_driver=maildir, mail_path=~/) que se
# anade al final del fichero. Las subcarpetas se leen bien de ~/, pero el INBOX se
# busca en /var/mail/ (que no existe) -> Dovecot intenta autocrearlo y falla.
#
# FIX: comentar la config mbox de Debian (mail_driver=mbox, mail_inbox_path=/var/mail,
# mail_path=%{home}/mail) en 10-mail.conf, dejando solo la de SVQPanel. Solo aplica
# en Debian 13+ (Dovecot 2.4); en Debian 12 (2.3) no existe ese problema.
#
# Idempotente y no interactivo.

set -u

CONF=/etc/dovecot/conf.d/10-mail.conf
echo "-> 0119: fix INBOX de Dovecot (mbox de Debian conviviendo con maildir)..."

if [ ! -f "$CONF" ]; then
    echo "  . $CONF no existe (sin correo instalado); nada que hacer."
    exit 0
fi

# Solo Dovecot >= 2.4 tiene este problema (Debian 13+).
if command -v dovecot >/dev/null 2>&1; then
    VER="$(dovecot --version 2>/dev/null | grep -oE '^[0-9]+\.[0-9]+' | head -1)"
    MAJOR="${VER%%.*}"; MINOR="${VER##*.}"
    if [ "${MAJOR:-0}" -lt 2 ] || { [ "${MAJOR:-0}" -eq 2 ] && [ "${MINOR:-0}" -lt 4 ]; }; then
        echo "  . Dovecot $VER (<2.4): no aplica."
        exit 0
    fi
fi

# ¿Esta activa la config mbox de Debian?
if ! grep -qE '^[[:space:]]*(mail_driver[[:space:]]*=[[:space:]]*mbox|mail_inbox_path[[:space:]]*=[[:space:]]*/var/mail)' "$CONF"; then
    echo "  . La config mbox de Debian ya no esta activa; nada que hacer."
    exit 0
fi

cp -a "$CONF" "${CONF}.bak-0119"

sed -i 's|^[[:space:]]*mail_driver[[:space:]]*=[[:space:]]*mbox|# (mbox de Debian desactivado — SVQPanel usa maildir)|' "$CONF"
sed -i 's|^[[:space:]]*mail_inbox_path[[:space:]]*=[[:space:]]*/var/mail|# mail_inbox_path (mbox de Debian desactivado)|' "$CONF"
sed -i 's|^[[:space:]]*mail_path[[:space:]]*=[[:space:]]*%{home}/mail|# mail_path (mbox de Debian desactivado)|' "$CONF"

# Validar antes de recargar; si algo va mal, restaurar el backup.
if doveconf -n >/dev/null 2>/tmp/svq-0119-dcerr; then
    systemctl reload dovecot 2>/dev/null || systemctl restart dovecot 2>/dev/null || true
    echo "  . config mbox de Debian desactivada; Dovecot recargado."
    echo "OK 0119: INBOX de Dovecot corregido."
else
    echo "  ! doveconf fallo tras el cambio; restaurando backup."
    cp -a "${CONF}.bak-0119" "$CONF"
    head -3 /tmp/svq-0119-dcerr 2>/dev/null
    exit 1
fi

exit 0
