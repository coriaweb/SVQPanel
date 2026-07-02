#!/bin/bash
# 0100-spf-ipv6-global-servidor.sh
#
# BUG: el SPF de las zonas DNS solo listaba la IPv6 DEDICADA del dominio (o
# ninguna si no tenía). Pero el correo del servidor sale por la IPv6 GLOBAL
# (smtp_bind_address6, la del hostname con PTR). Si el correo sale por IPv6 y el
# SPF no la lista → SPF fail → Gmail/Outlook marcan como spam o rechazan.
#
# Fix (ya en el código): las plantillas DNS meten la IPv6 global del servidor en
# el SPF. Este update aplica lo mismo a las zonas YA existentes: añade
# ip6:<global> al registro SPF de cada zona que no la tenga (solo dominios sin
# IPv6 dedicada; los que tienen dedicada ya la llevan). Idempotente.

set -u

echo "→ 0100: añadir la IPv6 global del servidor al SPF de las zonas existentes…"

cd /opt/svqpanel 2>/dev/null || { echo "✓ 0100: /opt/svqpanel no existe; nada que hacer"; exit 0; }
VENV_PY=/opt/svqpanel/venv/bin/python
[ -x "$VENV_PY" ] || VENV_PY=$(command -v python3)

# Reutiliza el backfill del panel (ya hace ip_address + AAAA + SPF ip6 global).
"$VENV_PY" -m api.cli backfill_dns_ipv6 2>&1 | tail -5 || \
    echo "  ⚠ backfill_dns_ipv6 devolvió error (revisa el log)"

echo "✓ 0100: completado"
exit 0
