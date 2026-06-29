#!/bin/bash
# 0068-fail2ban-postfix-unit.sh
#
# BUG: las jails de correo de fail2ban (postfix-sasl, svqpanel-postfix-relay y
# postfix) usaban journalmatch '_SYSTEMD_UNIT=postfix@-.service'. Eso era correcto
# en Debian 12, pero tras el upgrade a Debian 13 la unit pasa a ser
# 'postfix.service' → el journalmatch no casa NADA y las jails quedan CIEGAS
# (Total failed: 0 pese a cientos de ataques). Resultado: bots de relay y de
# login SMTP no se baneaban.
#
# Fix: detectar la unit de Postfix activa y corregir el journalmatch en jail.local
# (y quitarlo de los filtros, donde es redundante). Idempotente.

set -u

echo "→ 0068: corregir journalmatch de Postfix en fail2ban (D12/D13)…"

JAIL=/etc/fail2ban/jail.local
if [ ! -f "$JAIL" ] || ! command -v fail2ban-client >/dev/null 2>&1; then
    echo "✓ 0068: fail2ban no gestionado por el panel; nada que hacer"
    exit 0
fi

# Detectar la unit ACTIVA de Postfix. OJO: ambas units pueden EXISTIR a la vez
# (una inactiva); hay que mirar cuál está activa. En D12 es postfix@-.service,
# en D13 postfix.service.
if systemctl is-active --quiet postfix@-.service 2>/dev/null; then
    PF_UNIT="postfix@-.service"
else
    PF_UNIT="postfix.service"
fi
echo "  unit de Postfix activa: $PF_UNIT"

# Corregir el journalmatch en jail.local a la unit correcta (cualquiera de las
# dos variantes anteriores → la actual). Idempotente.
sed -i -E "s|_SYSTEMD_UNIT=postfix(@-)?\.service|_SYSTEMD_UNIT=$PF_UNIT|g" "$JAIL"

# Quitar journalmatch redundante de nuestros filtros (debe ir en la jail, no en
# el filtro; ahí no se actualizaba).
for flt in /etc/fail2ban/filter.d/svqpanel-postfix-sasl.conf \
           /etc/fail2ban/filter.d/svqpanel-postfix-relay.conf; do
    [ -f "$flt" ] && sed -i "/^journalmatch *= *_SYSTEMD_UNIT=postfix/d" "$flt"
done

# Recargar fail2ban (validando antes).
if fail2ban-client -d >/dev/null 2>&1; then
    systemctl restart fail2ban >/dev/null 2>&1 || true
    echo "  ✓ fail2ban recargado"
else
    echo "  ⚠ config fail2ban inválida; revisar"
fi

echo "✓ 0068: journalmatch de Postfix corregido ($PF_UNIT)"
exit 0
