#!/bin/bash
# 0136 — Repara las zonas DNS que quedaron con el nameserver PLACEHOLDER
#        (ns1/ns2.svqpanel.local) en vez de los NS reales del panel.
#
# Bug: al crear un dominio con DNS desde /api/domains, la zona se generaba sin
# pasar ns1/ns2, así que caía al placeholder histórico de dns_manager. La zona
# se declaraba autoritativa para un TLD .local inexistente mientras el
# registrador delegaba en los NS de verdad → el dominio NO propagaba.
# (El endpoint /api/dns/zones sí lo hacía bien: solo afectaba al alta de dominio.)
#
# El código ya está arreglado (api/routes/domains.py); esto repara las zonas
# creadas antes del fix. Idempotente: si no hay zonas con placeholder, no toca
# nada. Si el panel aún no tiene NS reales configurados, se abstiene.
set -e

PANEL_DIR="/opt/svqpanel"
VENV_PY="${PANEL_DIR}/venv/bin/python"

[ -x "$VENV_PY" ] || { echo "0136: sin venv en $VENV_PY, se omite"; exit 0; }

cd "$PANEL_DIR"
"$VENV_PY" -m api.cli fix_placeholder_ns || {
    echo "0136: la reparación de NS falló (no bloquea la cadena)"
    exit 0
}

exit 0
