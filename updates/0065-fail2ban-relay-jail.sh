#!/bin/bash
# 0065-fail2ban-relay-jail.sh
#
# Añade una jail de fail2ban para bots "lentos" que intentan usar el servidor
# como relay (mandar a dominios que NO alojamos → "Relay access denied"). Mandan
# pocos intentos por hora, esquivando la jail [postfix] normal (5 en 10 min).
# Esta jail usa ventana LARGA (6h) para cazarlos. Es seguro: un cliente legítimo
# nunca recibe "Relay access denied" repetido (envía autenticado por submission).
#
# Idempotente y no interactivo. Solo actúa si fail2ban está gestionado por el panel.

set -u

echo "→ 0065: jail fail2ban para bots de relay…"

JAIL=/etc/fail2ban/jail.local
if [ ! -f "$JAIL" ]; then
    echo "✓ 0065: no hay $JAIL (fail2ban no gestionado por el panel); nada que hacer"
    exit 0
fi
if ! command -v fail2ban-client >/dev/null 2>&1; then
    echo "✓ 0065: fail2ban no instalado; nada que hacer"
    exit 0
fi

# 1) Filtro propio (idempotente: se reescribe siempre, es la fuente de verdad).
cat > /etc/fail2ban/filter.d/svqpanel-postfix-relay.conf <<'EOF'
[Definition]
failregex = ^(\S+/?\S*smtpd\[\d+\]: )?NOQUEUE: reject: RCPT from \S+\[<HOST>\]: 454 4\.7\.1 .*Relay access denied
ignoreregex =
journalmatch = _SYSTEMD_UNIT=postfix@-.service
EOF

# 2) Añadir la jail si no existe.
if ! grep -q "^\[svqpanel-postfix-relay\]" "$JAIL"; then
cat >> "$JAIL" <<'EOF'

[svqpanel-postfix-relay]
# Bots "lentos" de relay (pocos intentos/hora). Ventana larga (6h) para cazarlos.
# Seguro: un cliente legítimo nunca recibe "Relay access denied" repetido.
enabled  = true
port     = smtp,465,submission
filter   = svqpanel-postfix-relay
journalmatch = _SYSTEMD_UNIT=postfix@-.service
maxretry = 5
findtime = 6h
bantime  = 24h
EOF
    echo "  ✓ jail [svqpanel-postfix-relay] añadida"
else
    echo "  · jail ya existía"
fi

# 3) Recargar fail2ban (validando antes que la config es correcta).
if fail2ban-client -d >/dev/null 2>&1; then
    systemctl reload fail2ban >/dev/null 2>&1 || systemctl restart fail2ban >/dev/null 2>&1
    echo "  ✓ fail2ban recargado"
else
    echo "  ⚠ config fail2ban inválida; revisar (jail no aplicada)"
fi

echo "✓ 0065: jail de relay configurada"
exit 0
