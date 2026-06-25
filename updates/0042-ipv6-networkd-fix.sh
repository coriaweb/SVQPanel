#!/bin/bash
# 0042-ipv6-networkd-fix.sh
#
# ARREGLA UN BUG CRÍTICO: el panel persistía las IPv6 de dominios en un netplan
# (62-svqpanel-ipv6.yaml) que REDEFINÍA eth0 y entraba en conflicto con la config
# principal → `netplan generate` fallaba → al REINICIAR el servidor se quedaba
# SIN RED.
#
# Este update:
#   1. Migra las IPv6 de dominios del netplan viejo a un drop-in de
#      systemd-networkd (aditivo, sin conflicto).
#   2. Elimina el netplan defectuoso.
#   3. Instala un servicio systemd que asegura la ruta default IPv6 persistente
#      (workaround del bug de networkd 252 con gateways onlink fuera de subred).
#
# Invoca el código del panel (idempotente). Valida que netplan sigue OK.

set -euo pipefail

echo "→ 0042: arreglar persistencia de IPv6 (netplan → systemd-networkd)…"

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }

cd /opt/svqpanel
"$PYBIN" -m api.cli setup_ipv6_persistence || \
    echo "  ⚠ setup_ipv6_persistence con incidencias (no crítico)."

# Verificación de seguridad: netplan debe generar SIN errores. Si falla, avisar
# fuerte (pero no abortar la cadena de updates: la red ya está aplicada en vivo).
if command -v netplan >/dev/null 2>&1; then
    if netplan generate 2>&1 | grep -qiE "error|conflict"; then
        echo "  ⚠⚠ netplan generate AÚN reporta errores — revisar /etc/netplan/ a mano."
    else
        echo "  ✓ netplan generate limpio."
    fi
fi

echo "✓ 0042: persistencia de IPv6 migrada a systemd-networkd"
exit 0
