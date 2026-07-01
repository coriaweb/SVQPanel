#!/bin/bash
# 0083-postscreen-antibot.sh
#
# Activa postscreen (portero anti-bot) en el puerto 25 de Postfix. Corta bots
# que hablan antes de tiempo (pregreet), pipelinean o mandan comandos basura,
# ANTES de que sondeen buzones (los ataques de enumeración tipo 550 User unknown).
#
# Juzga por COMPORTAMIENTO SMTP, no por RBL — así pilla IPs "limpias" de un solo
# uso (OVH/Scaleway) que las listas negras aún no tienen. Las RBL las sigue
# haciendo Rspamd vía unbound (no se tocan). Los grandes (Gmail/Outlook) respetan
# el protocolo → no les afecta; solo mete ~6s la 1ª vez a un remitente nuevo.
#
# Idempotente, con validación (postfix check) y auto-reversión si algo falla.

set -u

echo "→ 0083: activar postscreen (portero anti-bot en SMTP 25)…"

command -v postfix >/dev/null 2>&1 || { echo "  · postfix no instalado; nada que hacer"; exit 0; }

MASTER=/etc/postfix/master.cf
MAIN=/etc/postfix/main.cf
BK=".bak-0083"

# ¿Ya activo? (idempotencia)
if grep -qE '^smtp      inet  n       -       y       -       1       postscreen' "$MASTER" \
   && grep -q '^postscreen_greet_action' "$MAIN"; then
    echo "  · postscreen ya estaba activo; nada que hacer"
    exit 0
fi

cp -a "$MASTER" "${MASTER}${BK}"
cp -a "$MAIN"   "${MAIN}${BK}"

# 1) master.cf: smtp inet → postscreen (+ helpers smtpd pass, dnsblog, tlsproxy).
#    Debian trae esas líneas comentadas justo debajo; las activamos.
if grep -qE '^smtp      inet  n       -       y       -       -       smtpd' "$MASTER"; then
    sed -i 's/^smtp      inet  n       -       y       -       -       smtpd/#smtp      inet  n       -       y       -       -       smtpd/' "$MASTER"
    sed -i 's/^#smtp      inet  n       -       y       -       1       postscreen/smtp      inet  n       -       y       -       1       postscreen/' "$MASTER"
    sed -i 's/^#smtpd     pass  -       -       y       -       -       smtpd/smtpd     pass  -       -       y       -       -       smtpd/' "$MASTER"
    sed -i 's/^#dnsblog   unix  -       -       y       -       0       dnsblog/dnsblog   unix  -       -       y       -       0       dnsblog/' "$MASTER"
    sed -i 's/^#tlsproxy  unix  -       -       y       -       0       tlsproxy/tlsproxy  unix  -       -       y       -       0       tlsproxy/' "$MASTER"
fi

# 2) main.cf: config de postscreen (tests de protocolo enforce; sin DNSBL).
if ! grep -q '^postscreen_greet_action' "$MAIN"; then
    cat >> "$MAIN" << 'PSEOF'

# ── SVQPanel: postscreen (portero anti-bot, tests de protocolo) ──
postscreen_greet_action = enforce
postscreen_pipelining_enable = yes
postscreen_pipelining_action = enforce
postscreen_non_smtp_command_enable = yes
postscreen_non_smtp_command_action = enforce
postscreen_bare_newline_enable = yes
postscreen_bare_newline_action = enforce
postscreen_dnsbl_action = ignore
postscreen_dnsbl_sites =
postscreen_access_list = permit_mynetworks
PSEOF
fi

# 3) Validar antes de recargar; si falla, revertir (no dejar el correo caído).
if postfix check 2>/dev/null; then
    systemctl reload postfix 2>/dev/null || systemctl restart postfix 2>/dev/null
    # Comprobar que el 25 sigue escuchando tras el reload
    sleep 1
    if ss -lnt 2>/dev/null | grep -q ':25 '; then
        echo "  ✓ postscreen activo (SMTP 25 sigue escuchando)"
    else
        echo "  ✗ el 25 no escucha tras activar; revirtiendo"
        mv -f "${MASTER}${BK}" "$MASTER"; mv -f "${MAIN}${BK}" "$MAIN"
        systemctl restart postfix 2>/dev/null
        exit 1
    fi
else
    echo "  ✗ postfix check falló; revirtiendo"
    mv -f "${MASTER}${BK}" "$MASTER"; mv -f "${MAIN}${BK}" "$MAIN"
    exit 1
fi

echo "✓ 0083: postscreen activado"
exit 0
