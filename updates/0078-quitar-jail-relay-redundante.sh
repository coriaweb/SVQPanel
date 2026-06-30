#!/bin/bash
# 0078-quitar-jail-relay-redundante.sh
#
# Quita la jail fail2ban [svqpanel-postfix-relay] (updates 0065/0068). Era
# redundante e inútil:
#   - El "Relay access denied" es spam DISTRIBUIDO (muchas IPs, 1-2 intentos c/u),
#     contra lo que fail2ban no puede (banea por IP que repite N veces).
#   - CrowdSec YA lo cubre (escenario crowdsecurity/postfix-relay-denied), que
#     banea por reputación y comparte inteligencia comunitaria.
#   - La jail postfix[aggressive] también captura ese patrón para las pocas IPs
#     que sí repiten.
#   - El servidor ya rechaza todo el relay (cero riesgo); la jail solo daba 0/0
#     y confundía en el panel.
#
# Idempotente.

set -u

echo "→ 0078: quitar jail fail2ban relay redundante (lo cubre CrowdSec)…"

JAIL=/etc/fail2ban/jail.local
if [ ! -f "$JAIL" ] || ! command -v fail2ban-client >/dev/null 2>&1; then
    echo "✓ 0078: fail2ban no gestionado por el panel; nada que hacer"
    exit 0
fi

if grep -q "^\[svqpanel-postfix-relay\]" "$JAIL"; then
    python3 - "$JAIL" <<'PYEOF'
import re, sys
p = sys.argv[1]
s = open(p).read()
s2 = re.sub(r"\n\[svqpanel-postfix-relay\].*?(?=\n\[|\Z)", "\n", s, flags=re.DOTALL)
open(p, "w").write(s2)
PYEOF
    echo "  ✓ bloque [svqpanel-postfix-relay] eliminado de jail.local"
else
    echo "  · ya no estaba en jail.local"
fi

# Borrar el filtro propio (ya no lo usa nadie).
rm -f /etc/fail2ban/filter.d/svqpanel-postfix-relay.conf 2>/dev/null || true

# Recargar fail2ban (validando antes).
if fail2ban-client -d >/dev/null 2>&1; then
    systemctl restart fail2ban >/dev/null 2>&1 || true
    echo "  ✓ fail2ban recargado"
fi

echo "✓ 0078: jail relay redundante eliminada"
exit 0
