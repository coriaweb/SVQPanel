#!/bin/bash
# 0044-suspend-page-ipv6.sh
#
# Regenera el vhost de la página de suspensión de los dominios ya SUSPENDIDOS
# para que escuche también en IPv6 (listen [::]). Sin esto, un dominio suspendido
# con AAAA presentaba un certificado ajeno por IPv6 → ERR_CERT_COMMON_NAME_INVALID
# en el navegador. Idempotente.

set -euo pipefail

echo "→ 0044: página de suspensión escuchando también en IPv6…"

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }

cd /opt/svqpanel
"$PYBIN" -m api.cli refresh_suspended_vhosts \
    && echo "  ✓ vhosts de suspensión regenerados" \
    || echo "  ⚠ refresh_suspended_vhosts con incidencias (no crítico)."

echo "✓ 0044: suspensión IPv6 aplicada"
exit 0
