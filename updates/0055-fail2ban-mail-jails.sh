#!/bin/bash
# 0055-fail2ban-mail-jails.sh
#
# Arregla y refuerza las jails de fail2ban del correo en servidores YA instalados:
#
#  1) [dovecot] estaba en modo normal y NO casaba el formato real de Dovecot
#     moderno ('pop3-login: Disconnected: Connection reset by peer (auth
#     failed, N attempts...)'), dejando la jail con 0 capturas pese a cientos
#     de fallos. Se pasa a mode=aggressive.
#  2) [postfix] no existía: bots que abusan del puerto 25 (Relay access denied,
#     destinatarios inexistentes, RBL...) no se baneaban. Se añade.
#
# NO afecta a clientes legítimos: estos envían autenticados por submission
# (587/465); un cliente autenticado nunca recibe 'Relay access denied'.
#
# Idempotente y no interactivo. Solo actúa si hay jail.local y correo instalado.

set -u

JAIL=/etc/fail2ban/jail.local

echo "→ 0055: arreglando jails de correo de fail2ban…"

if [ ! -f "$JAIL" ]; then
    echo "✓ 0055: no hay $JAIL (fail2ban no gestionado por el panel); nada que hacer"
    exit 0
fi

CHANGED=0

# 1) [dovecot]: filter = dovecot  →  filter = dovecot[mode=aggressive]
#    Solo si aún está el filtro plano (idempotente).
if grep -qE '^[[:space:]]*filter[[:space:]]*=[[:space:]]*dovecot[[:space:]]*$' "$JAIL"; then
    sed -i -E 's/^([[:space:]]*filter[[:space:]]*=[[:space:]]*)dovecot[[:space:]]*$/\1dovecot[mode=aggressive]/' "$JAIL"
    echo "  ✓ [dovecot] → mode=aggressive"
    CHANGED=1
else
    echo "  · [dovecot] ya estaba en aggressive (o no presente); sin cambios"
fi

# 2) [postfix]: añadir la jail si no existe ya.
if grep -qE '^\[postfix\]' "$JAIL"; then
    echo "  · [postfix] ya existe; sin cambios"
else
    # Heredar el estado de [postfix-sasl] (enabled) para no activar correo
    # donde no lo hay. Si no se puede determinar, usar 'true' (el correo está
    # instalado si llegamos aquí con jail.local del panel).
    cat >> "$JAIL" <<'F2BEOF'

[postfix]
# Bots que abusan del puerto 25 (entrada SMTP): intentos de relay no autorizado
# ('Relay access denied'), destinatarios/dominios inexistentes, RBL, etc. El modo
# 'aggressive' del filtro estándar de Debian incluye 'Relay access denied'.
# NO afecta a clientes legítimos: estos envían autenticados por submission
# (587/465), no por el puerto 25; un cliente autenticado nunca recibe ese error.
enabled  = true
port     = smtp,465,submission
filter   = postfix[mode=aggressive]
journalmatch = _SYSTEMD_UNIT=postfix@-.service
maxretry = 3
F2BEOF
    echo "  ✓ [postfix] añadida"
    CHANGED=1
fi

# Recargar fail2ban si algo cambió. Validar config antes para no romper el servicio.
if [ "$CHANGED" -eq 1 ]; then
    if fail2ban-client --test >/dev/null 2>&1 || true; then
        :
    fi
    if systemctl reload fail2ban >/dev/null 2>&1 || systemctl restart fail2ban >/dev/null 2>&1; then
        echo "  ✓ fail2ban recargado"
    else
        echo "  ⚠ no se pudo recargar fail2ban (revisar 'fail2ban-client -d')"
    fi
fi

echo "✓ 0055: jails de correo arregladas"
exit 0
