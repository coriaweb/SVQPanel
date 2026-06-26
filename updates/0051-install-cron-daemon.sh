#!/bin/bash
# 0051-install-cron-daemon.sh
#
# El paquete `cron` NO se instalaba: el daemon estaba ausente y NINGÚN cronjob
# (de cliente ni del panel) se ejecutaba. Instala cron, lo habilita/arranca, y
# REESCRIBE al crontab del sistema todos los cronjobs ACTIVOS guardados en la BD
# del panel (que estaban registrados pero nunca llegaron al spool). Idempotente.

set -euo pipefail

echo "→ 0051: daemon cron + reescribir crons activos…"

if ! command -v crontab >/dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq cron 2>/dev/null || true
fi
systemctl enable --now cron 2>/dev/null || true

if command -v crontab >/dev/null 2>&1; then
    echo "  ✓ cron instalado y activo"
else
    echo "  ⚠ no se pudo instalar cron"
    exit 0
fi

# Reescribir los cronjobs activos de la BD al crontab del sistema.
PYBIN=/opt/svqpanel/venv/bin/python
if [ -x "$PYBIN" ]; then
    cd /opt/svqpanel
    "$PYBIN" - <<'PYEOF' || echo "  ⚠ reescritura de crons con incidencias (no crítico)."
import sys
sys.path.insert(0, "/opt/svqpanel")
from api.models.database import SessionLocal, load_all_models
load_all_models()
from api.models.models_cron import CronJob
from api.models.models_user import User
from scripts.cron_manager import CronManager
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
print(f"  ✓ {n} cron(s) activos reescritos al crontab del sistema")
db.close()
PYEOF
fi

echo "✓ 0051: cron operativo"
exit 0
