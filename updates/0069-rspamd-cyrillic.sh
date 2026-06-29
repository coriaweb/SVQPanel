#!/bin/bash
# 0069-rspamd-cyrillic.sh
#
# Marca como spam (→ Junk) el correo cuyo cuerpo está en alfabeto cirílico. Pensado
# sobre todo para el spam de formularios de contacto de webs españolas (un bot
# rellena el formulario con texto ruso y la web genera un aviso por email) y para
# spam directo en ruso/ucraniano. Un negocio español nunca recibe correo legítimo
# así. Peso 6 → va a Junk (no rechazo: si llegara algo legítimo, es recuperable).
#
# Invoca el código del panel (idempotente): escribe la regla Lua en lua.local.d.

set -u

echo "→ 0069: penalización de correo en cirílico (Rspamd)…"

PYBIN=/opt/svqpanel/venv/bin/python
if [ ! -x "$PYBIN" ] || ! command -v rspamadm >/dev/null 2>&1; then
    echo "✓ 0069: Rspamd/panel no disponible; nada que hacer"
    exit 0
fi

cd /opt/svqpanel
"$PYBIN" -m api.cli setup_cyrillic_protection || echo "  ⚠ con incidencias (no crítico)"

echo "✓ 0069: penalización de cirílico aplicada"
exit 0
