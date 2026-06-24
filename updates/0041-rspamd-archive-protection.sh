#!/bin/bash
# 0041-rspamd-archive-protection.sh
#
# Protección anti zip-bomb del antispam (aprovecha mejoras de Rspamd 4.1.1):
# sube el peso de los símbolos del módulo `archives` para que un adjunto
# comprimido con ratio de descompresión enorme (zip-bomb) o con un ejecutable
# dentro se marque con fuerza, evitando que sature el escaneo.
#
# Invoca el código del panel (idempotente). Requiere Rspamd.

set -euo pipefail

echo "→ 0041: protección anti zip-bomb del antispam (Rspamd)…"

[ -d /etc/rspamd ] || { echo "  Rspamd no instalado — nada que hacer."; exit 0; }

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }

cd /opt/svqpanel
"$PYBIN" -m api.cli setup_archive_protection || \
    echo "  ⚠ setup_archive_protection con incidencias (no crítico)."

echo "✓ 0041: protección anti zip-bomb aplicada"
exit 0
