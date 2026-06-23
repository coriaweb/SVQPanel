#!/bin/bash
# 0031-mail-out-ipv6.sh
#
# IP de salida SMTP por dominio con soporte IPv6. El sistema ya enviaba por la
# IPv4 asignada al dominio (sender_dependent transport + smtp_bind_address);
# ahora soporta también IPv6 y una preferencia por dominio (ipv4/ipv6).
#
# Cambia el naming del transporte (smtp_X_X_X_X → svqout_<dominio>) y añade un
# mapa de config (ipv4|ipv6|pref). Este update reaplica la IP de salida de todos
# los dominios con el formato nuevo y deja master.cf coherente (sin transportes
# huérfanos del formato viejo). Invoca el código del panel (idempotente).

set -euo pipefail

echo "→ 0031: IP de salida SMTP por dominio con IPv6…"

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }

cd /opt/svqpanel
"$PYBIN" -m api.cli migrate_mail_out_ip || {
    echo "  ⚠ migrate_mail_out_ip devolvió error (no crítico)."
    exit 0
}

echo "✓ 0031: IP de salida SMTP migrada"
exit 0
