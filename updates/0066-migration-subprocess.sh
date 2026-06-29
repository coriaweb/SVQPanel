#!/bin/bash
# 0066-migration-subprocess.sh
#
# La importación de backups (Hestia/cPanel) ahora corre en un SUBPROCESO aislado
# y consume mucha menos RAM (extracción del tar en streaming). Antes, un sitio
# grande disparaba >1 GB y systemd mataba svqpanel por OOM a mitad de migración,
# dejando el job colgado en 'running' para siempre ("Importando…" eterno).
#
# Este update:
#  1) Las columnas nuevas de migration_jobs (tar_path/cleanup_tar/dns_records_json)
#     las crea el ALTER TABLE de api/main.py al reiniciar svqpanel (lo hace
#     update.sh tras el git pull); aquí no hace falta tocarlas.
#  2) Marca como 'failed' las migraciones que quedaron ZOMBIE en 'running' de la
#     versión antigua (procesos muertos por OOM): así la UI deja de mostrarlas
#     "Importando…". Reutiliza el código del panel, no toca SQL a mano.
#
# Idempotente y no interactivo.

set -u

echo "→ 0066: importación en subproceso aislado + limpieza de jobs zombie…"

VENV_PY=/opt/svqpanel/venv/bin/python
[ -x "$VENV_PY" ] || VENV_PY=$(command -v python3)

# Marcar zombies como failed. Inline porque es trivial y no merece un CLI propio:
# al correr este script svqpanel pudo no haber arrancado aún con el código nuevo,
# así que lo hacemos contra la BD vía SQLAlchemy del propio panel.
cd /opt/svqpanel 2>/dev/null || { echo "✓ 0066: /opt/svqpanel no existe; nada que hacer"; exit 0; }

"$VENV_PY" - <<'PY'
import sys
sys.path.insert(0, "/opt/svqpanel")
try:
    from api.models.database import SessionLocal
    from api.models.models_migration import MigrationJob
    from datetime import datetime
except Exception as e:
    print(f"  · no se pudo importar el panel ({e}); se omite (lo hará el startup)")
    sys.exit(0)

db = SessionLocal()
try:
    zombies = db.query(MigrationJob).filter(MigrationJob.status == "running").all()
    for job in zombies:
        job.status = "failed"
        job.error = ("La importación se interrumpió: el panel se reinició mientras "
                     "corría (falta de memoria, versión anterior). Vuelve a intentarla.")
        job.finished_at = datetime.utcnow()
    if zombies:
        db.commit()
    print(f"  ✓ {len(zombies)} migración(es) zombie marcada(s) como fallida(s)")
finally:
    db.close()
PY

echo "✓ 0066: completado"
exit 0
