#!/bin/bash
# 0174-nft-persistir-puertos.sh
#
# Los puertos cerrados en Seguridad → Puertos del sistema se reabrían solos:
# el panel los guardaba en /etc/nftables/svqpanel-ports.nft, pero
# /etc/nftables.conf no incluía ese archivo, así que cada `nft -f` (arranque,
# botón «Aplicar» y la recarga DIARIA del timer de listas IP) devolvía los
# puertos de fábrica. Lo mismo pasaba con la allowlist de MySQL remoto (set y
# regla del 3306 solo en vivo). Y las reglas custom / listas IP iban al final
# de `input`, detrás del accept de los puertos base: un deny sobre 22/80/443/
# correo no hacía nada (visto en .65 y .97, 0.273.0).
#
# Fix (código del panel, `api.cli migrate_nft_conf`): añade los includes, el
# set mysql_remote_allow y las cadenas svq_pre (reglas custom) y svq_lists
# (listas IP / bloqueo por país, con el SMTP 25 exento), ambas antes de los
# puertos base, y mueve allí las reglas ya generadas. Copia .bak-0174, `nft -c`
# y vuelta atrás si no valida. Al recargar se aplican los puertos que se
# cerraron por última vez desde el panel y el bloqueo por país pasa a cortar de
# verdad web/SSH/panel/IMAP/POP/DNS. Reflejado en install.sh. Idempotente.

set -u

command -v nft >/dev/null 2>&1 || exit 0
[ -f /etc/nftables.conf ] || exit 0

if [ -x /opt/svqpanel/venv/bin/python ]; then
    cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli migrate_nft_conf \
      && echo "✓ 0174: puertos cerrados y reglas del firewall persistentes" \
      || echo "⚠ 0174: no se pudo migrar nftables.conf (revisar a mano)"
fi
exit 0
