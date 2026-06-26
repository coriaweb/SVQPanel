#!/bin/bash
# 0052-cron-history.sh
#
# Historial de ejecuciones de cron: instala el wrapper svq-cron-run + la cola en
# disco (1733), y REESCRIBE los cronjobs activos del crontab para que pasen por
# el wrapper (así registran estado/duración/salida). Idempotente.

set -euo pipefail

echo "→ 0052: historial de ejecuciones de cron…"

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }

cd /opt/svqpanel
"$PYBIN" - <<'PYEOF' || echo "  ⚠ con incidencias (no crítico)."
import sys
sys.path.insert(0, "/opt/svqpanel")
from scripts.cron_manager import CronManager, install_cron_wrapper
from api.models.database import SessionLocal, load_all_models
load_all_models()
from api.models.models_cron import CronJob
from api.models.models_user import User

# 1) Wrapper + cola.
install_cron_wrapper()
print("  ✓ wrapper svq-cron-run + cola instalados")

# 2) Reescribir los crons activos para que usen el wrapper.
db = SessionLocal()
mgr = CronManager()
n = 0
for c in db.query(CronJob).filter(CronJob.is_active == True).all():  # noqa: E712
    u = db.query(User).filter(User.id == c.user_id).first()
    if not u:
        continue
    try:
        mgr.add_cron(u.username, c.id, c.minute, c.hour, c.day, c.month,
                     c.weekday, c.command, comment=c.comment or "")
        n += 1
    except Exception as e:
        print(f"    cron {c.id}: {e}")
print(f"  ✓ {n} cron(s) reescritos con el wrapper de historial")
db.close()
PYEOF

echo "✓ 0052: historial de cron activo"
exit 0
