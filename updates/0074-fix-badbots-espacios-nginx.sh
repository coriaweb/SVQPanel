#!/bin/bash
# 0074-fix-badbots-espacios-nginx.sh
#
# El update 0073 activó "Silvy X Ran", pero el generador de bad-bots.conf no
# entrecomillaba los patrones. En un bloque `map` de nginx los espacios separan
# parámetros, así que `~*Silvy X Ran 1;` da "invalid number of the map
# parameters" → nginx -t falla y NO recarga (queda con la config vieja: el
# bloqueo de bots nuevo no llegó a aplicarse).
#
# El código ya está corregido (entrecomilla: `"~*Silvy X Ran" 1;`). Este update
# REESCRIBE el bad-bots.conf con el generador nuevo y recarga nginx. Reactiva
# explícitamente los bots del catálogo afectados para no depender de parsear el
# .conf roto. Idempotente.

set -u

echo "→ 0074: arreglar bad-bots.conf (patrones con espacios rompían nginx)…"

cd /opt/svqpanel || { echo "✓ 0074: /opt/svqpanel no existe; nada que hacer"; exit 0; }
VENV_PY=/opt/svqpanel/venv/bin/python
[ -x "$VENV_PY" ] || VENV_PY=$(command -v python3)

"$VENV_PY" - <<'PY'
import sys
sys.path.insert(0, "/opt/svqpanel")
try:
    from scripts.bad_bots_manager import ensure_catalog_bots_blocked
except Exception as e:
    print(f"  · no se pudo importar el panel ({e}); revísalo desde la UI")
    sys.exit(0)

# Reactiva los bots del 0073 con el generador corregido (reescribe el .conf y
# recarga nginx). Los demás bots/custom ya activos se preservan.
NUEVOS = ["silvy_x_ran", "leakix", "leakix_ua", "censys", "internetmeasure", "expanse"]
try:
    res = ensure_catalog_bots_blocked(NUEVOS)
    print(f"  ✓ bad-bots.conf regenerado (total bloqueados: {res['blocked_count']})")
except Exception as e:
    print(f"  ✗ no se pudo regenerar/recargar nginx: {e}")
    sys.exit(1)
PY

rc=$?

# Verificación dura: si nginx -t sigue fallando, no dar por bueno el update.
if ! nginx -t 2>/dev/null; then
    echo "  ✗ nginx -t sigue fallando tras regenerar bad-bots.conf"
    nginx -t 2>&1 | sed 's/^/    /'
    exit 1
fi
echo "  ✓ nginx -t OK"

echo "✓ 0074: completado"
exit $rc
