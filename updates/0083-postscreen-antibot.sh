#!/bin/bash
# 0083-postscreen-antibot.sh
#
# Activa postscreen (portero anti-bot) en el puerto 25 de Postfix. Corta bots
# que hablan antes de tiempo (pregreet), pipelinean o mandan comandos basura,
# ANTES de que sondeen buzones (los ataques de enumeración tipo 550 User unknown).
#
# Juzga por COMPORTAMIENTO SMTP, no por RBL — así pilla IPs "limpias" de un solo
# uso (OVH/Scaleway) que las listas negras aún no tienen. Las RBL las sigue
# haciendo Rspamd vía unbound (no se tocan).
#
# ⚠️ CORRECCIÓN (updates 0145 y 0152): la frase original decía que "los grandes
# respetan el protocolo → no les afecta". ERA FALSA. En enforce, postscreen
# rechaza la 1ª conexión de CUALQUIER IP fuera de su caché, pase o no las
# pruebas, y los deep protocol tests obligan a reintentar por diseño. Costó
# correo perdido de PayPal, OVH, Netflix, Openbank y el Ayto. de Sevilla. Por eso
# TODAS las acciones van hoy en "ignore": los tests se siguen haciendo y
# cacheando, pero sin cortar la conexión.
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
# ⚠️ ignore, NUNCA enforce. Con enforce, postscreen rechaza (450 4.3.2) la primera
# conexion de toda IP que no tenga en cache, PASE O NO las pruebas: el veredicto se
# registra DESPUES del rechazo. Medido en produccion durante un mes: 930 "PASS NEW"
# y 953 rechazos — uno por uno, cada IP paga un peaje al entrar. Y como la cache
# caduca a los 7d, quien escribe cada 8 dias lo paga SIEMPRE (la misma IP de PayPal:
# rechazada el 5-sep, aceptada el 9-sep). Se perdio correo real de PayPal, OVH,
# Openbank, Netflix, MailChannels y el Ayto. de Sevilla, con CERO entregas en un mes.
# ignore NO desactiva la prueba: se sigue haciendo y cacheando, solo deja de
# rechazar por no conocer la IP. Es el default de Postfix y lo que hacen cPanel,
# Plesk, Mail-in-a-Box e iRedMail. Ver update 0145 para el historial completo.
postscreen_greet_action = ignore
# 2s en vez del default ${stress?{2}:{6}}s: menos latencia por conexion (ver 0138).
postscreen_greet_wait = 2s
# Los tres tests de abajo son DEEP PROTOCOL TESTS: para ejecutarlos hay que
# CORTAR la sesion SMTP en curso, lo que obliga al cliente a reintentar. Van en
# enable = no, no basta con action = ignore:
#   *_action = ignore  -> que hacer con el RESULTADO de la prueba
#   *_enable = no      -> si la prueba SE HACE siquiera
# Con enable = yes el corte se produce igual, antes de que action opine. Medido
# en produccion con los dos servidores en paralelo (2h): el que los tenia en "no"
# hizo 93 conexiones con 0 rechazos; el que los tenia en "yes" (con action=ignore)
# hizo 51 conexiones y rechazo 10, entre ellas 4 intentos de HubSpot a un buzon
# de cliente que nunca llegaron. Ver updates 0152 y 0153.
# El pregreet NO es deep test (se resuelve en la misma sesion) y sigue activo: es
# el que caza bots de verdad, 5 en esas mismas 2 horas.
postscreen_pipelining_enable = no
postscreen_pipelining_action = ignore
postscreen_non_smtp_command_enable = no
postscreen_non_smtp_command_action = ignore
postscreen_bare_newline_enable = no
postscreen_bare_newline_action = ignore
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
