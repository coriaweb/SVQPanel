#!/bin/bash
# 0017-named-ipv4-only.sh
#
# Si el servidor NO tiene IPv6 saliente, named intenta resolver los NS por IPv6,
# falla con "network unreachable" e inunda el log (notable desde que Rspamd usa
# este BIND para las DNSBL). Resuelve igual por IPv4, solo ensucia. Con la opción
# -4, named ni lo intenta.
#
# INTELIGENTE Y REVERSIBLE: solo añade -4 si NO hay IPv6 saliente; y si el
# servidor SÍ tiene IPv6, RETIRA el -4 (por si se habilitó IPv6 después). Así
# este update se auto-corrige en cada ejecución según el estado real de la red.

set -euo pipefail

echo "→ 0017: named modo IPv4 si no hay IPv6 saliente..."

DEF=/etc/default/named
[ -f "$DEF" ] || { echo "  Sin /etc/default/named (¿sin BIND?) — nada que hacer."; exit 0; }

# ¿Hay IPv6 saliente? (ping a un DNS público IPv6)
if ping6 -c1 -W2 2606:4700:4700::1111 >/dev/null 2>&1; then
    HAS_IPV6=1
else
    HAS_IPV6=0
fi

CHANGED=0
if [ "$HAS_IPV6" = "0" ]; then
    # Sin IPv6 → añadir -4 si no está
    if ! grep -q '\-4' "$DEF"; then
        sed -i 's/^OPTIONS="\(.*\)"/OPTIONS="\1 -4"/' "$DEF"
        echo "  Sin IPv6 saliente → named en modo IPv4 (-4)"
        CHANGED=1
    else
        echo "  Sin IPv6 saliente → named ya estaba en -4."
    fi
else
    # Con IPv6 → quitar -4 si lo pusimos antes (que vuelva a usar IPv6)
    if grep -q '\-4' "$DEF"; then
        sed -i 's/ -4"/"/; s/-4 //' "$DEF"
        echo "  Hay IPv6 saliente → retirado -4 (named usará IPv4+IPv6)"
        CHANGED=1
    else
        echo "  Hay IPv6 saliente → named ya usa IPv4+IPv6."
    fi
fi

if [ "$CHANGED" = "1" ]; then
    systemctl restart named 2>/dev/null || true
    sleep 2
    if systemctl is-active --quiet named; then
        echo "  ✓ named reiniciado"
    else
        echo "  ✗ named no arrancó — revisa: journalctl -u named -n 30"
        exit 1
    fi
fi

echo "✓ 0017: configuración IPv4/IPv6 de named ajustada"
exit 0
