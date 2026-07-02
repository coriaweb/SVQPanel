#!/bin/bash
# 0099-mail-ipv6-salida-con-ptr.sh
#
# BUG: smtp_bind_address6 (IPv6 de salida del correo del servidor) se detectaba
# con `ip -6 route get` en install_mail.sh, que en un /64 con muchas IPv6 elige
# una CUALQUIERA — normalmente SIN PTR (rDNS). Gmail/Outlook rechazan entonces
# el correo con "550 5.7.25 ... does not have a PTR record".
#
# Fix: fijar smtp_bind_address6 a la IPv6 del HOSTNAME (la que el proveedor
# configuró con PTR y a la que apunta el AAAA), si está asignada a la interfaz y
# su PTR resuelve. Solo actúa si la IPv6 actual NO tiene PTR (no pisa una config
# ya correcta o personalizada). Idempotente.

set -u

echo "→ 0099: fijar IPv6 de salida del correo a la que tiene PTR…"

command -v postconf >/dev/null 2>&1 || { echo "✓ 0099: postfix no instalado; nada que hacer"; exit 0; }

CUR="$(postconf -h smtp_bind_address6 2>/dev/null)"
if [ -z "$CUR" ]; then
    echo "✓ 0099: no hay smtp_bind_address6 (sin IPv6 de salida); nada que hacer"
    exit 0
fi

# ¿La IPv6 actual ya tiene PTR? Si sí, no tocamos nada.
if dig +short -x "$CUR" @1.1.1.1 2>/dev/null | grep -q '.'; then
    echo "✓ 0099: la IPv6 de salida ($CUR) ya tiene PTR; nada que cambiar"
    exit 0
fi

echo "  · IPv6 de salida actual SIN PTR: $CUR"

# IPv6 del hostname (la que debería tener PTR).
HN="$(hostname -f 2>/dev/null || hostname)"
NEW="$(getent ahostsv6 "$HN" 2>/dev/null | awk '{print $1; exit}')"

if [ -z "$NEW" ]; then
    echo "  ⚠ no pude resolver la IPv6 del hostname ($HN); revisa manualmente el PTR"
    exit 0
fi
# Debe estar asignada a la interfaz.
if ! ip -6 addr show scope global | grep -q "${NEW}/"; then
    echo "  ⚠ la IPv6 del hostname ($NEW) no está en la interfaz; revisa manualmente"
    exit 0
fi
# Debe tener PTR (si no, no ganamos nada).
if ! dig +short -x "$NEW" @1.1.1.1 2>/dev/null | grep -q '.'; then
    echo "  ⚠ la IPv6 del hostname ($NEW) tampoco tiene PTR; configura el rDNS con el proveedor"
    exit 0
fi

postconf -e "smtp_bind_address6 = $NEW"
echo "  ✓ smtp_bind_address6: $CUR → $NEW (con PTR)"

# Reaplicar la IP de salida POR DOMINIO: con el fix, un dominio con pref=ipv4 ya
# NO declara su IPv6 dedicada en master.cf (evita rebotes por IPv6 sin PTR). Solo
# los que eligieron ipv6 explícitamente la usan. Reutiliza el código del panel.
cd /opt/svqpanel 2>/dev/null && {
    VENV_PY=/opt/svqpanel/venv/bin/python
    [ -x "$VENV_PY" ] || VENV_PY=$(command -v python3)
    "$VENV_PY" -m api.cli migrate_mail_out_ip 2>&1 | tail -3 || \
        echo "  ⚠ migrate_mail_out_ip devolvió error (revisa el log)"
}

systemctl reload postfix 2>/dev/null || systemctl restart postfix 2>/dev/null || true

echo "✓ 0099: completado"
exit 0
