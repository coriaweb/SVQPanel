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
import os
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_scheduler_started = False
_scheduler_lock = threading.Lock()

# Importaciones pesadas a nivel de módulo (se cargan UNA sola vez cuando
# FastAPI importa este módulo al arrancar). Si estuvieran dentro de los hilos,
# Python las re-ejecutaría en cada tick causando una fuga de memoria masiva.
from api.models.database import SessionLocal
from api.models.models_backup import BackupJob, BackupRecord
from api.models.models_domain import Domain
from api.models.models_user import User
from api.models.models_client_db import ClientDatabase


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

def _decrypt_sftp_password(encrypted: str) -> str:
    """Descifra la contraseña SFTP con Fernet si hay clave configurada."""
    if not encrypted:
        return encrypted
    try:
        from cryptography.fernet import Fernet
        key = os.getenv("PANEL_ENCRYPTION_KEY", "")
        if key:
            return Fernet(key.encode()).decrypt(encrypted.encode()).decode()
    except Exception:
        pass
    return encrypted


def _run_job(job_id: int):
    """
    Lanza un backup para el job dado directamente, sin importar api/routes.
    Las importaciones pesadas están al nivel del módulo (se cargan una vez).
    """
    # Importaciones ligeras de scripts (no routes/FastAPI)
    from scripts.backup_manager import BackupManager
    from scripts.utils import get_domain_root

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
        record.status = "running"
        db.commit()

        # Resolver dominios del job (None = todos los del usuario)
        domains_to_backup = []
        if job.domain_id:
            dom = db.query(Domain).filter(Domain.id == job.domain_id).first()
            owner = db.query(User).filter(User.id == dom.user_id).first() if dom else None
            if dom and owner:
                domains_to_backup = [(dom, owner)]
        else:
            creator = db.query(User).filter(User.id == job.user_id).first()
            query = db.query(Domain).filter(Domain.is_active == True)  # noqa
            if not (creator and creator.is_admin):
                query = query.filter(Domain.user_id == job.user_id)
            for d in query.order_by(Domain.domain_name).all():
                o = db.query(User).filter(User.id == d.user_id).first()
                domains_to_backup.append((d, o))

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
            "sftp_password":     _decrypt_sftp_password(job.sftp_password),
            "sftp_path":         job.sftp_path,
            "sftp_key_path":     job.sftp_key_path,
            "s3_endpoint":       job.s3_endpoint,
            "s3_region":         job.s3_region,
            "s3_bucket":         job.s3_bucket,
            "s3_prefix":         job.s3_prefix,
            "s3_access_key":     job.s3_access_key,
            "s3_secret_key":     _decrypt_sftp_password(job.s3_secret_key),
            "retention_copies":  job.retention_copies,
        }

        mgr = BackupManager()
        all_log, total_size, total_xf, total_xt, total_db = [], 0, 0, 0, 0
        any_failed = False

        for domain, owner in (domains_to_backup or []):
            username = owner.username if owner else "root"
            domain_name = domain.domain_name
            files_path = get_domain_root(username, domain_name) if job.include_files else None
            mail_path = f"/home/{username}/mail/{domain_name}" if job.include_mail else None
            databases = []
            if job.include_databases:
                dbs = db.query(ClientDatabase).filter(
                    ClientDatabase.domain_id == domain.id,
                    ClientDatabase.is_active == True  # noqa
                ).all()
                databases = [{"db_name": d.db_name} for d in dbs]

            all_log.append(f"── {domain_name} ({username}) ──")
            res = mgr.run_backup(
                job_config=job_config,
                username=username,
                domain_name=domain_name,
                files_path=files_path,
                mail_path=mail_path,
                databases=databases,
                force_full=False,
            )
            all_log.extend(res["log"])
            total_size += res["size_bytes"]
            total_xf   += res["files_transferred"]
            total_xt   += res["files_total"]
            total_db   += res["db_count"]
            if res["status"] == "failed":
                any_failed = True

        record.status            = "failed" if any_failed else "success"
        record.backup_path       = job_config.get("local_path")
        record.size_bytes        = total_size
        record.files_transferred = total_xf
        record.files_total       = total_xt
        record.db_count          = total_db
        record.log_output        = "\n".join(all_log)[:50000]
        record.error_message     = "Algunos dominios fallaron" if any_failed else None
        record.finished_at       = datetime.utcnow()
        job.last_run = datetime.utcnow()
        db.commit()
        logger.info("Backup programado job=%d status=%s", job_id, record.status)

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
        try:
            db.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Loop principal del scheduler
# ─────────────────────────────────────────────────────────────────────────────

def _scheduler_loop():
    """Bucle que corre cada minuto y dispara los jobs programados."""
    # Sin imports aquí: SessionLocal y BackupJob ya están al nivel del módulo.
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
