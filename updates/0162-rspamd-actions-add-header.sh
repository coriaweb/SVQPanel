#!/bin/bash
# 0162-rspamd-actions-add-header.sh
#
# Reescribe /etc/rspamd/local.d/actions.conf con la clave `add_header` en vez
# de "add header", CONSERVANDO los umbrales que haya (del panel o del admin).
#
# Por qué: el actions.conf de fábrica de Rspamd usa `add_header = 6`; el nuestro
# escribía "add header" = 4. Rspamd aplicaba el nuestro (4), pero veía las dos
# claves y en cada arranque avisaba "invalid actions thresholds order:
# add_header (6) must have lower score than reject (6)". Solo es ruido, pero
# tapa avisos de verdad. Invoca el código del panel (rspamd_tuning), que valida
# con configtest y revierte si algo falla.
#
# Idempotente y no interactivo.

set -euo pipefail

echo "→ 0162: actions.conf de Rspamd con add_header…"

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }
command -v rspamadm >/dev/null 2>&1 || { echo "  Sin Rspamd — nada que hacer."; exit 0; }

cd /opt/svqpanel
"$PYBIN" -m api.cli normalize_antispam_actions || \
    echo "  ⚠ normalize_antispam_actions con incidencias (no crítico)."

echo "✓ 0162: hecho"
exit 0
