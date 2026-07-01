#!/bin/bash
# 0095-nft-flush-selectivo-crowdsec.sh
#
# Arregla un fallo GRAVE y silencioso: /etc/nftables.conf empezaba con
# `flush ruleset`, que borra TODAS las tablas de nftables — incluidas las que
# crea el firewall-bouncer de CrowdSec (ip crowdsec / ip6 crowdsec6). Cada vez que
# se recargaba nftables (al abrir/cerrar un puerto, etc.), el flush destruía la
# tabla del bouncer, que entraba en bucle de error ("netlink receive: no such
# file") y DEJABA DE APLICAR los baneos al firewall. Resultado: CrowdSec detectaba
# y "baneaba" (en su BD) pero el atacante seguía pasando (nftables no lo bloqueaba).
#
# Fix: sustituir `flush ruleset` por el patrón idempotente que recrea SOLO la
# tabla del panel sin tocar las de crowdsec:
#     table inet svqpanel {}      (crea vacía si no existe → el delete no falla)
#     delete table inet svqpanel  (la borra, ahora existe seguro)
# Y reiniciar el bouncer para que recree su tabla y re-aplique todas las decisiones.
#
# Idempotente: si ya está el patrón nuevo, no reescribe. Valida con `nft -c` antes
# de recargar (si la validación falla, NO toca el firewall en producción).

set -u

echo "→ 0095: flush selectivo de nftables (no pisar CrowdSec)…"

NFT=/etc/nftables.conf

if [ ! -f "$NFT" ]; then
    echo "  · $NFT no existe; nada que hacer"
    echo "✓ 0095: sin cambios"
    exit 0
fi

if ! grep -qE '^\s*flush ruleset' "$NFT"; then
    echo "  · $NFT ya no usa 'flush ruleset' (patrón nuevo o personalizado)"
else
    cp -a "$NFT" "$NFT.bak-0095"
    # Reemplaza la línea 'flush ruleset' por el bloque idempotente.
    # Usamos un marcador para insertar varias líneas con sed.
    sed -i 's|^\s*flush ruleset\s*$|table inet svqpanel {}\ndelete table inet svqpanel|' "$NFT"

    # Validar ANTES de recargar. Si falla, revertir y no tocar el firewall.
    if nft -c -f "$NFT" >/dev/null 2>&1; then
        if systemctl reload nftables >/dev/null 2>&1 || nft -f "$NFT" >/dev/null 2>&1; then
            echo "  ✓ nftables.conf con flush selectivo aplicado"
            rm -f "$NFT.bak-0095"
        else
            echo "  ⚠ recarga de nftables falló; restaurando backup"
            mv "$NFT.bak-0095" "$NFT"
            nft -f "$NFT" >/dev/null 2>&1 || true
        fi
    else
        echo "  ⚠ validación nft -c falló; restaurando backup (firewall intacto)"
        mv "$NFT.bak-0095" "$NFT"
    fi
fi

# Reiniciar el bouncer para recrear su tabla y re-aplicar las decisiones (aunque
# el conf ya estuviera bien, esto lo deja sano si venía roto de antes).
if systemctl is-active crowdsec-firewall-bouncer >/dev/null 2>&1; then
    systemctl restart crowdsec-firewall-bouncer >/dev/null 2>&1 \
        && echo "  ✓ firewall-bouncer reiniciado (tabla nft + decisiones re-aplicadas)" \
        || echo "  ⚠ no se pudo reiniciar el bouncer (revisar: journalctl -u crowdsec-firewall-bouncer)"
fi

echo "✓ 0095: CrowdSec vuelve a aplicar los baneos al firewall"
exit 0
