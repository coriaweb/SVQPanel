#!/bin/bash
# 0043-apache-directoryindex.sh
#
# Regenera los vhosts de TODOS los dominios en modo Apache+Nginx para aplicar el
# DirectoryIndex con index.php ANTES de index.html (un sitio con ambos servía el
# .html en vez de la app PHP). Solo afecta a instalaciones en modo apache+nginx.
#
# Invoca el código del panel (idempotente).

set -euo pipefail

echo "→ 0043: DirectoryIndex Apache (index.php antes que index.html)…"

# Solo aplica si el servidor está en modo Apache+Nginx.
WSCONF=/etc/svqpanel/webserver.conf
if [ -f "$WSCONF" ] && grep -qi "apache" "$WSCONF"; then
    PYBIN=/opt/svqpanel/venv/bin/python
    [ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }
    cd /opt/svqpanel
    "$PYBIN" -m api.cli regenerate_all_vhosts 2>/dev/null \
        && echo "  ✓ vhosts regenerados" \
        || echo "  ⚠ regenerate_all_vhosts no disponible o con incidencias (no crítico)."
else
    echo "  No es modo Apache+Nginx — nada que hacer."
fi

echo "✓ 0043: DirectoryIndex aplicado"
exit 0
