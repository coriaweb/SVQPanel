"""
Daemon de programación automática de backups.

Arranca en un hilo de fondo cuando FastAPI inicia. Cada minuto comprueba qué
BackupJobs tienen schedule_enabled=True y si su expresión cron coincide con el
momento actual; si coincide, lanza el backup en otro hilo.

El matching cron es intencionalmente simple (no soporta listas ni rangos
complejos como @reboot o L) porque los presets de la UI son suficientes para
el 99% de casos de uso de hosting. Soporta:
  - *              (cualquier valor)
  - N              (valor exacto)
  - */N            (cada N unidades)
  - a,b,c          (lista de valores)
  - a-b            (rango)
"""

import logging
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_scheduler_started = False
_scheduler_lock = threading.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# Matching cron
# ─────────────────────────────────────────────────────────────────────────────

def _matches_field(expr: str, value: int) -> bool:
    """Devuelve True si `value` encaja en la expresión cron `expr`."""
    expr = expr.strip()
    if expr == "*":
        return True
    # Cada N (*/N)
    if expr.startswith("*/"):
        try:
            step = int(expr[2:])
            return value % step == 0
        except ValueError:
            return False
    # Lista (a,b,c)
    if "," in expr:
        parts = [p.strip() for p in expr.split(",")]
        return any(_matches_field(p, value) for p in parts)
    # Rango (a-b)
    if "-" in expr:
        try:
            lo, hi = expr.split("-", 1)
            return int(lo) <= value <= int(hi)
        except ValueError:
            return False
    # Valor exacto
    try:
        return int(expr) == value
    except ValueError:
        return False


def _cron_matches(job, now: datetime) -> bool:
    """True si el job debe ejecutarse en el minuto `now`."""
    return (
        _matches_field(job.schedule_minute,  now.minute)
        and _matches_field(job.schedule_hour,    now.hour)
        and _matches_field(job.schedule_day,     now.day)
        and _matches_field(job.schedule_weekday, now.weekday())
    )


# ─────────────────────────────────────────────────────────────────────────────
# Ejecución de un job concreto (en su propio hilo)
# ─────────────────────────────────────────────────────────────────────────────

def _run_job(job_id: int):
    """Lanza un backup para el job dado. Reutiliza _execute_backup de la ruta API."""
    from api.models.database import SessionLocal
    from api.models.models_backup import BackupJob, BackupRecord
    from api.routes.backups import _execute_backup, _job_to_config

    db = SessionLocal()
    record_id = None
    try:
        job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
        if not job or not job.is_active or not job.schedule_enabled:
            return

        record = BackupRecord(
            job_id=job.id,
            user_id=job.user_id,
            status="pending",
            started_at=datetime.utcnow(),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        record_id = record.id
        db.close()

        # Delegar en la misma función que usa el endpoint /run
        _execute_backup(job_id, record_id, force_full=False)
        logger.info("Backup programado job=%d record=%d completado", job_id, record_id)

    except Exception as exc:
        logger.exception("Error lanzando backup programado job=%d", job_id)
        if record_id:
            try:
                db2 = SessionLocal()
                rec = db2.query(BackupRecord).filter(BackupRecord.id == record_id).first()
                if rec:
                    rec.status = "failed"
                    rec.error_message = str(exc)
                    rec.finished_at = datetime.utcnow()
                    db2.commit()
                db2.close()
            except Exception:
                pass
    finally:
        try:
            db.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Loop principal del scheduler
# ─────────────────────────────────────────────────────────────────────────────

def _scheduler_loop():
    """Bucle que corre cada minuto y dispara los jobs programados."""
    from api.models.database import SessionLocal
    from api.models.models_backup import BackupJob

    logger.info("Backup scheduler iniciado")

    # Esperar hasta el siguiente minuto entero para sincronizarse con el reloj
    now = datetime.now(timezone.utc)
    wait = 60 - now.second
    time.sleep(wait)

    while True:
        tick = datetime.now(timezone.utc)
        try:
            db = SessionLocal()
            try:
                jobs = (
                    db.query(BackupJob)
                    .filter(BackupJob.is_active == True,        # noqa: E712
                            BackupJob.schedule_enabled == True)  # noqa: E712
                    .all()
                )
                for job in jobs:
                    if _cron_matches(job, tick):
                        logger.info("Lanzando backup programado job=%d (%s)", job.id, job.name)
                        t = threading.Thread(
                            target=_run_job,
                            args=(job.id,),
                            daemon=True,
                            name=f"backup-job-{job.id}",
                        )
                        t.start()
            finally:
                db.close()
        except Exception:
            logger.exception("Error en scheduler loop")

        # Dormir hasta el siguiente minuto entero
        elapsed = (datetime.now(timezone.utc) - tick).total_seconds()
        sleep_for = max(0, 60 - elapsed)
        time.sleep(sleep_for)


# ─────────────────────────────────────────────────────────────────────────────
# API pública: arrancar el scheduler (idempotente)
# ─────────────────────────────────────────────────────────────────────────────

def start_scheduler():
    """Arranca el daemon en un hilo de fondo. Idempotente: solo arranca una vez."""
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True

    t = threading.Thread(
        target=_scheduler_loop,
        daemon=True,
        name="backup-scheduler",
    )
    t.start()
    logger.info("Hilo backup-scheduler arrancado")
