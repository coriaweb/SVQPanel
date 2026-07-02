#!/bin/bash
# 0101-spf-ip6-correcta-recorregir.sh
#
# FIX del 0100: aquel backfill metió en el SPF la IPv6 DEDICADA del dominio (que
# no tiene PTR y por la que NO sale el correo), en vez de la IPv6 GLOBAL del
# servidor (por la que sí sale, con PTR). Resultado: SPF fail en Gmail para los
# dominios con IPv6 dedicada.
#
# Corrección (ya en el código): el SPF declara la IPv6 por la que SALE el correo
# (global por defecto; dedicada solo si mail_out_ip_pref=ipv6). Este update
# re-ejecuta el backfill corregido para arreglar las zonas ya afectadas.
#
# Idempotente.

set -u

echo "→ 0101: recorregir el SPF (ip6 = IP de salida del correo, no la IPv6 web)…"

cd /opt/svqpanel 2>/dev/null || { echo "✓ 0101: /opt/svqpanel no existe; nada que hacer"; exit 0; }
VENV_PY=/opt/svqpanel/venv/bin/python
[ -x "$VENV_PY" ] || VENV_PY=$(command -v python3)

"$VENV_PY" -m api.cli backfill_dns_ipv6 2>&1 | tail -5 || \
    echo "  ⚠ backfill_dns_ipv6 devolvió error (revisa el log)"

echo "✓ 0101: completado"
exit 0
