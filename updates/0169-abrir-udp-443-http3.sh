#!/bin/bash
# 0169-abrir-udp-443-http3.sh
#
# Abre el UDP 443 en el firewall del panel (set base_udp_ports).
#
# Por qué: los dominios con HTTP/3 activado escuchan QUIC en el 443/udp y
# anuncian `Alt-Svc: h3=":443"` al navegador, pero install.sh solo abría por
# UDP el 53 (DNS) y el puerto del panel: el QUIC de las webs nunca llegaba a
# nginx (ampaconecta.com).
#
# Cómo: lo añade en vivo al set y en /etc/nftables.conf (para que sobreviva
# a reinicios), con copia previa y validación `nft -c`. Idempotente.

CONF=/etc/nftables.conf

command -v nft >/dev/null 2>&1 || exit 0
nft list set inet svqpanel base_udp_ports >/dev/null 2>&1 || exit 0

nft add element inet svqpanel base_udp_ports '{ 443 }' 2>/dev/null || true

if [ -f "$CONF" ] && grep -q "set base_udp_ports" "$CONF" \
   && ! sed -n '/set base_udp_ports {/,/}/p' "$CONF" | grep -qE 'elements = \{[^}]*\b443\b'; then
    cp -a "$CONF" "$CONF.bak-0169"
    sed -i '/set base_udp_ports {/,/}/ s/elements = { /elements = { 443, /' "$CONF"
    if ! nft -c -f "$CONF" >/dev/null 2>&1; then
        echo "⚠ 0169: nftables.conf no valida tras el cambio; se restaura la copia"
        cp -a "$CONF.bak-0169" "$CONF"
    fi
fi

echo "✓ 0169: UDP 443 (HTTP/3) abierto"
exit 0
