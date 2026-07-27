#!/bin/bash
# 0127-fail2ban-limit-req-error-log.sh
#
# La jail nginx-limit-req de fail2ban NO ha baneado NUNCA a nadie (Total
# banned: 0 desde que se activó en el update 0088): su logpath apuntaba a los
# ACCESS logs, pero el filtro nginx-limit-req solo casa con el mensaje
# "limiting requests, excess: ... client: <HOST>" que nginx escribe en el
# ERROR log. Resultado real: en el ataque a corosantamaria.org (jul 2026) nginx
# devolvió 218 respuestas 429 y escribió 202 líneas "limiting requests", pero
# fail2ban baneó 0 IPs y el atacante hizo 1.743 POST a wp-login.php desde 612
# IPs hasta acertar la contraseña.
#
# Este update reescribe SOLO el bloque [nginx-limit-req] de jail.local para que
# lea los error logs (por dominio + global). No toca svqpanel-scanner, que usa
# los access logs legítimamente (su filtro sí es de access log).
#
# Se aplica con `fail2ban-client reload` (NUNCA restart: restart pierde los
# baneos activos; reload los conserva y además re-expande los globos del
# logpath, con lo que también entran a vigilarse los sitios creados después del
# último arranque de fail2ban).
#
# El install.sh ya genera el bloque corregido para servidores nuevos, y
# domain_manager.create_domain() hace reload de fail2ban al dar de alta cada
# dominio (llega con el git pull, no necesita update).
#
# Idempotente y no interactivo.

set -u

echo "→ 0127: jail nginx-limit-req → leer el ERROR log de nginx…"

JAIL=/etc/fail2ban/jail.local

if [ ! -f "$JAIL" ] || ! grep -q '^\[nginx-limit-req\]' "$JAIL"; then
    echo "  · $JAIL sin sección [nginx-limit-req]; nada que corregir"
    exit 0
fi

# Idempotencia: si el bloque ya apunta al error log, no tocar nada.
if awk '/^\[nginx-limit-req\]/{in_block=1; next} /^\[/{in_block=0} in_block' "$JAIL" \
        | grep -q 'nginx\.error\.log'; then
    echo "  · la jail ya lee los error logs; nada que hacer"
    exit 0
fi

# Reemplazar el bloque completo [nginx-limit-req] … hasta la siguiente sección.
awk '
    /^\[nginx-limit-req\]/ {
        print "[nginx-limit-req]"
        print "enabled  = true"
        print "port     = http,https"
        print "filter   = nginx-limit-req"
        print "logpath  = /home/*/web/*/logs/nginx.error.log"
        print "           /var/log/nginx/error.log"
        print "backend  = auto"
        print "maxretry = 10"
        print "findtime = 120"
        print "bantime  = 86400"
        print ""
        skip=1; next
    }
    skip && /^\[/ { skip=0 }   # llegó la siguiente sección: dejar de saltar
    !skip { print }
' "$JAIL" > "$JAIL.tmp" && mv "$JAIL.tmp" "$JAIL"

echo "  ✓ logpath corregido a nginx.error.log"

# Reload (conserva baneos y re-expande los globos). Best-effort: si falla, la
# config ya está escrita y se aplicará en el próximo arranque de fail2ban.
if command -v fail2ban-client >/dev/null 2>&1; then
    if fail2ban-client reload >/dev/null 2>&1; then
        echo "  ✓ fail2ban recargado (baneos activos conservados)"
    else
        echo "  ⚠ fail2ban-client reload falló; la config quedará aplicada en el próximo arranque"
    fi
else
    echo "  · fail2ban-client no disponible; config escrita igualmente"
fi

echo "✓ 0127: jail nginx-limit-req operativa (error log)"
exit 0
