#!/bin/bash
# 0164-plantillas-web-con-valor.sh
#
# Plantillas web rehechas (v0.250.0): solo aportan lo propio de cada aplicación
# y nada que ya haga el panel o que choque con él. Antes varias no podían ni
# aplicarse (duplicate location "/", client_max_body_size y .well-known
# duplicados, $blogid inexistente) y otras anulaban protecciones (location
# exacto de wp-login.php se saltaba el rate-limit; fastcgi_pass directo se
# saltaba Apache en modo Apache+Nginx).
#
# Los dominios con una plantilla aplicada guardan su COPIA de las reglas: este
# update se las pasa a la versión nueva (solo reglas nginx y docroot; su PHP no
# se toca) y regenera su vhost, revirtiendo si nginx -t / configtest falla.
# Invoca el código del panel (api.cli resync_builtin_templates).
#
# Idempotente y no interactivo.

set -euo pipefail

echo "→ 0164: plantillas web con valor (reglas nuevas en los dominios que las usan)…"

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }

cd /opt/svqpanel
"$PYBIN" -m api.cli resync_builtin_templates || \
    echo "  ⚠ resync_builtin_templates con incidencias (no crítico, revisa el log)."

echo "✓ 0164: hecho"
exit 0
