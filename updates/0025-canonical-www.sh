#!/bin/bash
# 0025-canonical-www.sh
#
# Aplica el "dominio canónico" a los dominios ya existentes. A partir de esta
# versión el panel fuerza por defecto www (dominio.com → www.dominio.com) en los
# dominios NUEVOS. Este update propaga ese comportamiento a los EXISTENTES, pero
# de forma DEFENSIVA: forzar www solo es seguro si 'www.<dominio>' resuelve en
# DNS; si no resuelve, el dominio se deja en 'none' (sirve ambas, sin redirigir)
# para no tumbar la web.
#
# La columna canonical_domain la crea el ALTER TABLE de api/main.py al arrancar
# (default 'www'); aquí solo regeneramos los vhosts en disco con la decisión
# defensiva. Invoca el código del panel (idempotente). Seguro de re-ejecutar.

set -euo pipefail

echo "→ 0025: aplicar dominio canónico (forzar www) a dominios existentes…"

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }

cd /opt/svqpanel
"$PYBIN" -m api.cli migrate_canonical_domain || {
    echo "  ⚠ migrate_canonical_domain devolvió error (no crítico)."
    exit 0
}

echo "✓ 0025: dominio canónico aplicado"
exit 0
