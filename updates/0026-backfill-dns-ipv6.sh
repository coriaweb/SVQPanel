#!/bin/bash
# 0026-backfill-dns-ipv6.sh
#
# Backfill de zonas DNS ya existentes tras la mejora de IPv6:
#   1) Rellena DnsZone.ip_address cuando estaba NULL (la lista de zonas mostraba
#      "—" en la columna IP).
#   2) Para dominios que YA tenían IPv6 asignada antes de esta versión: asegura
#      sus registros AAAA y añade ip6:<ipv6> al SPF (antes solo llevaba ip4).
#
# Invoca el código del panel (idempotente). Seguro de re-ejecutar.

set -euo pipefail

echo "→ 0026: backfill DNS (ip_address + AAAA/SPF para dominios con IPv6)…"

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }

cd /opt/svqpanel
"$PYBIN" -m api.cli backfill_dns_ipv6 || {
    echo "  ⚠ backfill_dns_ipv6 devolvió error (no crítico)."
    exit 0
}

echo "✓ 0026: backfill DNS completado"
exit 0
