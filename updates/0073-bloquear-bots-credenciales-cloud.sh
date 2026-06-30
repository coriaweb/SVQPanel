#!/bin/bash
# 0073-bloquear-bots-credenciales-cloud.sh
#
# Añade al catálogo de "bad bots" (Seguridad → Bloqueo de bots) varios escáneres
# muy frecuentes que el geo-bloqueo NO para (rotan por clouds de medio mundo):
#   - "Silvy X Ran": roba credenciales cloud (.env, gcloud/AWS/firebase/vultr...)
#   - LeakIX (l9scan / LEAKIX), Censys, InternetMeasurement, Expanse
# Se identifican en el User-Agent, así que nginx los corta (return 444) en
# cuanto se activan, vengan del país/cloud que vengan.
#
# Activa SOLO estos bots nuevos, respetando la selección que el admin ya tuviera
# (otros bots del catálogo y patrones custom se conservan). Idempotente: si ya
# están activos, no hace nada.
#
# Invoca el código del panel (bad_bots_manager) en vez de tocar el .conf a mano,
# así escribe el bad-bots.conf y recarga nginx con la misma lógica que la UI.

set -u

echo "→ 0073: bloquear bots de robo de credenciales cloud / escáneres…"

cd /opt/svqpanel || { echo "✓ 0073: /opt/svqpanel no existe; nada que hacer"; exit 0; }
VENV_PY=/opt/svqpanel/venv/bin/python
[ -x "$VENV_PY" ] || VENV_PY=$(command -v python3)

"$VENV_PY" - <<'PY'
import sys
sys.path.insert(0, "/opt/svqpanel")
try:
    from scripts.bad_bots_manager import ensure_catalog_bots_blocked
except Exception as e:
    print(f"  · no se pudo importar el panel ({e}); se podrá activar desde la UI")
    sys.exit(0)

NUEVOS = [
    "silvy_x_ran", "leakix", "leakix_ua",
    "censys", "internetmeasure", "expanse",
]
try:
    res = ensure_catalog_bots_blocked(NUEVOS)
except Exception as e:
    # Si nginx no está (servidor solo-Apache) o falla el reload, no romper la
    # cadena de updates: el admin puede activarlo desde la UI.
    print(f"  · no se pudo aplicar ahora ({e}); actívalo desde Seguridad → Bloqueo de bots")
    sys.exit(0)

if res["added"]:
    print(f"  ✓ activados: {', '.join(res['added'])} (total bloqueados: {res['blocked_count']})")
else:
    print("  · ya estaban activos; nada que hacer")
PY

echo "✓ 0073: completado"
exit 0
