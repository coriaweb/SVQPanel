#!/bin/bash
# 0014-fail2ban-postfix-sasl.sh
#
# El jail postfix-sasl de Fail2ban estaba mal configurado y NO se cargaba:
#   - filter = postfix-sasl  → ese filtro no existe en Debian 12 (es 'postfix'
#     con mode=auth).
#   - sin journalmatch → leía postfix.service en vez de postfix@-.service.
# Resultado: los bots que fallan el login SMTP (SASL LOGIN failed) no se baneaban.
#
# Este update corrige el jail en jail.local y recarga Fail2ban. Idempotente.
# Solo actúa si existe el jail postfix-sasl (instalaciones con correo).

set -euo pipefail

JL="/etc/fail2ban/jail.local"

echo "→ 0014: Arreglo del jail Fail2ban postfix-sasl..."

if [[ ! -f "$JL" ]] || ! grep -q '\[postfix-sasl\]' "$JL"; then
    echo "  Sin jail postfix-sasl (sin correo) — nada que hacer."
    exit 0
fi

# Crear el filtro propio que banea TODOS los fallos SASL (incluido 'Invalid
# authentication mechanism', que el filtro estándar 'postfix' excluye).
cat > /etc/fail2ban/filter.d/svqpanel-postfix-sasl.conf << 'PSASLEOF'
[Definition]
failregex = warning: [^[]*\[<HOST>\]: SASL (?:(?i)LOGIN|PLAIN|CRAM-MD5|DIGEST-MD5) authentication failed
ignoreregex =
journalmatch = _SYSTEMD_UNIT=postfix@-.service
PSASLEOF

# Apuntar el jail al filtro propio (cubre tanto 'postfix-sasl' como
# 'postfix[mode=auth]' de versiones anteriores de este update).
sed -i -E 's|^filter   = (postfix-sasl\|postfix\[mode=auth\])$|filter   = svqpanel-postfix-sasl|' "$JL"

# Añadir journalmatch al unit correcto si falta (justo bajo el filter del jail)
if ! awk '/\[postfix-sasl\]/{f=1} f&&/journalmatch/{print;exit}' "$JL" | grep -q journalmatch; then
    python3 - "$JL" << 'PYEOF'
import sys
f = sys.argv[1]
lines = open(f).read().split("\n")
out = []; injail = False
for l in lines:
    out.append(l)
    if l.strip() == "[postfix-sasl]":
        injail = True
    elif injail and l.strip().startswith("filter"):
        out.append("journalmatch = _SYSTEMD_UNIT=postfix@-.service")
        injail = False
open(f, "w").write("\n".join(out))
PYEOF
fi

systemctl reload fail2ban 2>/dev/null || systemctl restart fail2ban 2>/dev/null || true
sleep 2
if fail2ban-client status postfix-sasl >/dev/null 2>&1; then
    echo "  ✓ Jail postfix-sasl activo y vigilando intentos de login SMTP"
else
    echo "  ⚠ El jail postfix-sasl no cargó (revisa fail2ban-client status)"
fi

echo "✓ 0014: Jail Fail2ban postfix-sasl corregido"
exit 0
