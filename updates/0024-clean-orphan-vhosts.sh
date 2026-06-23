#!/bin/bash
# 0024-clean-orphan-vhosts.sh
#
# Sanea vhosts huérfanos de nginx/Apache acumulados por borrados de dominios o
# usuarios anteriores (cuando el borrado no limpiaba el vhost). Esos ficheros
# apuntan a rutas /home/.../web/<dominio> que ya no existen y hacían fallar
# `nginx -t` / `apache2ctl configtest`, bloqueando la recarga del webserver y,
# por tanto, el alta de CUALQUIER dominio nuevo.
#
# Invoca el código del panel (idempotente: solo borra vhosts cuyo root/logs NO
# existen; nunca toca el vhost del propio panel). Seguro de re-ejecutar.

set -euo pipefail

echo "→ 0024: limpiar vhosts huérfanos de nginx/Apache…"

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }

cd /opt/svqpanel
"$PYBIN" -m api.cli clean_orphan_vhosts --yes || {
    echo "  ⚠ clean_orphan_vhosts devolvió error (no crítico)."
    exit 0
}

echo "✓ 0024: vhosts huérfanos saneados"
exit 0
