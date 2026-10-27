#!/bin/bash
# 0167 — Las zonas que crea el importador de Hestia nacían con el SOA apuntando
#        al placeholder ns1.svqpanel.local en vez de al NS real del panel.
#
# Bug: import_dns creaba la DnsZone sin soa_ns y la columna tenía como default
# 'ns1.svqpanel.local'. Los registros NS sí eran los buenos (el dominio
# resuelve), pero el MNAME del SOA apuntaba a un host inexistente y los
# comprobadores de DNS (intoDNS…) lo marcaban.
#
# El código ya está arreglado (hestia_import.import_dns + default NULL en la
# columna); esto repara las zonas importadas antes del fix con el mismo CLI del
# 0136, que también corrige soa_ns. Idempotente; si el panel no tiene NS reales
# configurados, se abstiene.
set -e

PANEL_DIR="/opt/svqpanel"
VENV_PY="${PANEL_DIR}/venv/bin/python"

[ -x "$VENV_PY" ] || { echo "0167: sin venv en $VENV_PY, se omite"; exit 0; }

cd "$PANEL_DIR"
"$VENV_PY" -m api.cli fix_placeholder_ns || {
    echo "0167: la reparación del SOA falló (no bloquea la cadena)"
    exit 0
}

exit 0
