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
    """Lanza un backup para el job dado. Se ejecuta en un hilo separado."""
    from api.models.database import SessionLocal
    from api.models.models_backup import BackupJob, BackupRecord
    from api.models.models_domain import Domain
    from api.models.models_user import User
    from api.models.models_client_db import ClientDatabase
    from scripts.backup_manager import BackupManager
    from scripts.utils import get_domain_root

    db = SessionLocal()
    record_id = None
    try:
        job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
        if not job or not job.is_active or not job.schedule_enabled:
            return

        # Crear registro pending
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

        record.status = "running"
        db.commit()

        # Resolver paths
        domain = db.query(Domain).filter(Domain.id == job.domain_id).first()
        owner  = db.query(User).filter(User.id == domain.user_id).first() if domain else None
        username    = owner.username if owner else "root"
        domain_name = domain.domain_name if domain else None

        files_path = (
            get_domain_root(username, domain_name)
            if job.include_files and domain_name else None
        )
        mail_path = (
            f"/home/{username}/mail/{domain_name}"
            if job.include_mail and domain_name else None
        )

        databases = []
        if job.include_databases and domain:
            dbs = (
                db.query(ClientDatabase)
                .filter(ClientDatabase.domain_id == domain.id,
                        ClientDatabase.is_active == True)  # noqa: E712
                .all()
            )
            databases = [{"db_name": d.db_name} for d in dbs]

        # Descifrar password SFTP igual que en backups.py
        sftp_password = job.sftp_password
        if sftp_password:
            try:
                import os
                from cryptography.fernet import Fernet
                key = os.getenv("PANEL_ENCRYPTION_KEY", "")
                if key:
                    sftp_password = Fernet(key.encode()).decrypt(sftp_password.encode()).decode()
            except Exception:
                pass

        job_config = {
            "include_files":     job.include_files,
            "include_databases": job.include_databases,
            "include_mail":      job.include_mail,
            "backup_type":       job.backup_type,
            "destination_type":  job.destination_type,
            "local_path":        job.local_path,
            "sftp_host":         job.sftp_host,
            "sftp_port":         job.sftp_port or 22,
            "sftp_user":         job.sftp_user,
            "sftp_password":     sftp_password,
            "sftp_path":         job.sftp_path,
            "sftp_key_path":     job.sftp_key_path,
            "retention_copies":  job.retention_copies,
        }

        mgr = BackupManager()
        res = mgr.run_backup(
            job_config=job_config,
            username=username,
            domain_name=domain_name,
            files_path=files_path,
            mail_path=mail_path,
            databases=databases,
            force_full=False,
        )

        record.status            = res["status"]
        record.is_incremental    = res["is_incremental"]
        record.backup_path       = res["backup_path"]
        record.size_bytes        = res["size_bytes"]
        record.files_transferred = res["files_transferred"]
        record.files_total       = res["files_total"]
        record.db_count          = res["db_count"]
        record.log_output        = "\n".join(res["log"])[:50000]
        record.error_message     = res["error"]
        record.finished_at       = datetime.utcnow()
        job.last_run = datetime.utcnow()
        db.commit()

        logger.info(
            "Backup programado job=%d status=%s size=%s bytes",
            job_id, res["status"], res["size_bytes"],
        )

    except Exception as exc:
        logger.exception("Error en backup programado job=%d", job_id)
        if record_id:
            try:
                rec = db.query(BackupRecord).filter(BackupRecord.id == record_id).first()
                if rec:
                    rec.status = "failed"
                    rec.error_message = str(exc)
                    rec.finished_at = datetime.utcnow()
                    db.commit()
            except Exception:
                pass
    finally:
        db.close()


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
