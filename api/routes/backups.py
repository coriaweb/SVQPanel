"""
Rutas API para el sistema de copias de seguridad.

Un BackupJob define qué respaldar (archivos web, bases de datos, correo),
con qué tipo de copia (full/incremental) y a qué destino (local o SFTP).
Cada ejecución genera un BackupRecord con su estado y log.

Las copias se ejecutan en segundo plano (BackgroundTasks): el endpoint /run
crea un registro en estado "pending" y devuelve de inmediato; el trabajo real
actualiza el registro a running → success|failed.
"""

import os
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session

from api.models.database import get_db, SessionLocal
from api.models.models_user import User
from api.models.models_domain import Domain
from api.models.models_client_db import ClientDatabase
from api.models.models_backup import BackupJob, BackupRecord
from api.schemas.backup_schemas import (
    BackupJobCreate, BackupJobUpdate, BackupJobResponse,
    BackupRecordResponse, BackupRunRequest,
    BackupSnapshotResponse, BackupRestoreRequest,
)
from api.dependencies import require_auth

router = APIRouter()

PANEL_ENCRYPTION_KEY = os.getenv("PANEL_ENCRYPTION_KEY", "")


# ─────────────────────────────────────────────────────────────────────────────
# Cifrado de la contraseña SFTP (Fernet, igual que databases.py)
# ─────────────────────────────────────────────────────────────────────────────

def _get_fernet():
    if not PANEL_ENCRYPTION_KEY:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(PANEL_ENCRYPTION_KEY.encode())
    except Exception:
        return None


def _encrypt(value: str) -> str:
    """Cifra con Fernet si hay clave; si no, devuelve el valor tal cual."""
    f = _get_fernet()
    if not f or not value:
        return value
    return f.encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    """Descifra con Fernet; si no es descifrable, asume texto plano."""
    f = _get_fernet()
    if not f or not value:
        return value
    try:
        return f.decrypt(value.encode()).decode()
    except Exception:
        return value


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_job_or_404(job_id: int, db: Session) -> BackupJob:
    job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job de backup no encontrado")
    return job


def _check_access(current_user: User, job: BackupJob):
    if not current_user.is_admin and job.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes permiso sobre este backup")


def _assert_domain_ownership(domain_id: int, current_user: User, db: Session) -> Domain:
    domain = db.query(Domain).filter(Domain.id == domain_id).first()
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    if not current_user.is_admin and domain.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Ese dominio no te pertenece")
    return domain


def _job_response(job: BackupJob, db: Session) -> BackupJobResponse:
    """Serializa un job ocultando la contraseña SFTP y adjuntando el último registro."""
    resp = BackupJobResponse.model_validate(job)
    resp.sftp_password = None
    last = (
        db.query(BackupRecord)
        .filter(BackupRecord.job_id == job.id)
        .order_by(BackupRecord.started_at.desc())
        .first()
    )
    if last:
        resp.last_record_status = last.status
        resp.last_record_size_mb = round((last.size_bytes or 0) / 1048576, 2)
    return resp


def _record_response(rec: BackupRecord) -> BackupRecordResponse:
    resp = BackupRecordResponse.model_validate(rec)
    resp.size_mb = round((rec.size_bytes or 0) / 1048576, 2)
    if rec.finished_at and rec.started_at:
        resp.duration_seconds = int((rec.finished_at - rec.started_at).total_seconds())
    return resp


def _owner_and_paths(job: BackupJob, db: Session):
    """Devuelve (username_dueño, domain_name, files_dest, mail_dest) del dominio del job."""
    from scripts.utils import get_domain_root
    domain = db.query(Domain).filter(Domain.id == job.domain_id).first()
    owner = db.query(User).filter(User.id == domain.user_id).first() if domain else None
    username = owner.username if owner else "root"
    domain_name = domain.domain_name if domain else None
    files_dest = get_domain_root(username, domain_name) if domain_name else None
    mail_dest = f"/home/{username}/mail/{domain_name}" if domain_name else None
    return username, domain_name, files_dest, mail_dest


def _job_to_config(job: BackupJob) -> dict:
    """Convierte el job en el dict que espera BackupManager (con contraseña descifrada)."""
    return {
        "include_files":     job.include_files,
        "include_databases": job.include_databases,
        "include_mail":      job.include_mail,
        "backup_type":       job.backup_type,
        "destination_type":  job.destination_type,
        "local_path":        job.local_path,
        "sftp_host":         job.sftp_host,
        "sftp_port":         job.sftp_port or 22,
        "sftp_user":         job.sftp_user,
        "sftp_password":     _decrypt(job.sftp_password) if job.sftp_password else None,
        "sftp_path":         job.sftp_path,
        "sftp_key_path":     job.sftp_key_path,
        "retention_copies":  job.retention_copies,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Ejecución en segundo plano
# ─────────────────────────────────────────────────────────────────────────────

def _domains_for_job(job: BackupJob, db: Session) -> list:
    """
    Devuelve la lista de dominios a respaldar para este job.
    - Si job.domain_id está definido: solo ese dominio.
    - Si no (backup global): todos los dominios activos del propietario del job
      (o de todos los usuarios si el creador es admin).
    Cada elemento: (domain_obj, owner_user_obj)
    """
    if job.domain_id:
        domain = db.query(Domain).filter(Domain.id == job.domain_id).first()
        if not domain:
            return []
        owner = db.query(User).filter(User.id == domain.user_id).first()
        return [(domain, owner)]

    # Backup global
    creator = db.query(User).filter(User.id == job.user_id).first()
    query = db.query(Domain).filter(Domain.is_active == True)  # noqa: E712
    if not (creator and creator.is_admin):
        query = query.filter(Domain.user_id == job.user_id)
    domains = query.order_by(Domain.domain_name).all()
    result = []
    for d in domains:
        owner = db.query(User).filter(User.id == d.user_id).first()
        result.append((d, owner))
    return result


def _execute_backup(job_id: int, record_id: int, force_full: bool):
    """Ejecuta el backup y actualiza el BackupRecord. Corre en BackgroundTasks."""
    db = SessionLocal()
    try:
        job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
        record = db.query(BackupRecord).filter(BackupRecord.id == record_id).first()
        if not job or not record:
            return

        record.status = "running"
        db.commit()

        from scripts.utils import get_domain_root
        from scripts.backup_manager import BackupManager
        mgr = BackupManager()
        job_config = _job_to_config(job)

        domains_to_backup = _domains_for_job(job, db)

        all_log: list[str] = []
        total_size = 0
        total_files_transferred = 0
        total_files_total = 0
        total_db_count = 0
        any_failed = False
        last_path = None

        if not domains_to_backup:
            all_log.append("WARN: no hay dominios que respaldar para este job")

        for domain, owner in domains_to_backup:
            username    = owner.username if owner else "root"
            domain_name = domain.domain_name

            files_path = (
                get_domain_root(username, domain_name)
                if job.include_files else None
            )
            mail_path = (
                f"/home/{username}/mail/{domain_name}"
                if job.include_mail else None
            )
            databases = []
            if job.include_databases:
                dbs = (
                    db.query(ClientDatabase)
                    .filter(ClientDatabase.domain_id == domain.id,
                            ClientDatabase.is_active == True)  # noqa: E712
                    .all()
                )
                databases = [{"db_name": d.db_name} for d in dbs]

            all_log.append(f"── {domain_name} ({username}) ──")
            res = mgr.run_backup(
                job_config=job_config,
                username=username,
                domain_name=domain_name,
                files_path=files_path,
                mail_path=mail_path,
                databases=databases,
                force_full=force_full,
            )
            all_log.extend(res["log"])
            total_size             += res["size_bytes"]
            total_files_transferred += res["files_transferred"]
            total_files_total      += res["files_total"]
            total_db_count         += res["db_count"]
            last_path               = res["backup_path"]
            if res["status"] == "failed":
                any_failed = True
                all_log.append(f"ERROR {domain_name}: {res['error']}")

        record.status            = "failed" if any_failed else "success"
        record.backup_path       = last_path
        record.size_bytes        = total_size
        record.files_transferred = total_files_transferred
        record.files_total       = total_files_total
        record.db_count          = total_db_count
        record.log_output        = "\n".join(all_log)[:50000]
        record.error_message     = "Algunos dominios fallaron, revisa el log" if any_failed else None
        record.finished_at       = datetime.utcnow()
        job.last_run = datetime.utcnow()
        db.commit()

    except Exception as exc:
        rec = db.query(BackupRecord).filter(BackupRecord.id == record_id).first()
        if rec:
            rec.status = "failed"
            rec.error_message = str(exc)
            rec.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def _execute_restore(job_id: int, record_id: int, snapshot_name: str,
                     restore_files: bool, restore_databases: bool, restore_mail: bool):
    """Restaura un snapshot y actualiza el BackupRecord. Corre en BackgroundTasks."""
    db = SessionLocal()
    try:
        job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
        record = db.query(BackupRecord).filter(BackupRecord.id == record_id).first()
        if not job or not record:
            return

        record.status = "running"
        db.commit()

        username, domain_name, files_dest, mail_dest = _owner_and_paths(job, db)
        snapshot_path = f"{job.local_path.rstrip('/')}/users/{username}/{domain_name}/{snapshot_name}"

        from scripts.backup_manager import BackupManager
        mgr = BackupManager()
        res = mgr.restore_snapshot(
            snapshot_path=snapshot_path,
            files_dest=files_dest,
            mail_dest=mail_dest,
            restore_files=restore_files,
            restore_databases=restore_databases,
            restore_mail=restore_mail,
        )

        record.status        = res["status"]
        record.backup_path    = snapshot_path
        record.db_count       = res["db_count"]
        record.log_output     = "\n".join(res["log"])[:50000]
        record.error_message  = res["error"]
        record.finished_at    = datetime.utcnow()
        db.commit()

    except Exception as exc:
        rec = db.query(BackupRecord).filter(BackupRecord.id == record_id).first()
        if rec:
            rec.status = "failed"
            rec.error_message = str(exc)
            rec.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# CRUD de jobs
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/backups", response_model=List[BackupJobResponse])
async def list_backup_jobs(
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Lista los jobs de backup del usuario actual (admin: todos)."""
    query = db.query(BackupJob)
    if not current_user.is_admin:
        query = query.filter(BackupJob.user_id == current_user.id)
    jobs = query.order_by(BackupJob.created_at.desc()).all()
    return [_job_response(j, db) for j in jobs]


@router.post("/backups", response_model=BackupJobResponse, status_code=status.HTTP_201_CREATED)
async def create_backup_job(
    payload: BackupJobCreate,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Crea un nuevo job de backup. El dominio es obligatorio."""
    if not (payload.include_files or payload.include_databases or payload.include_mail):
        raise HTTPException(status_code=400, detail="Selecciona al menos un contenido a respaldar")

    if payload.domain_id:
        _assert_domain_ownership(payload.domain_id, current_user, db)

    if payload.destination_type == "sftp" and (not payload.sftp_host or not payload.sftp_user):
        raise HTTPException(status_code=400, detail="Host y usuario SFTP son obligatorios para destino remoto")

    data = payload.model_dump()
    if data.get("sftp_password"):
        data["sftp_password"] = _encrypt(data["sftp_password"])

    job = BackupJob(user_id=current_user.id, **data)
    db.add(job)
    db.commit()
    db.refresh(job)
    return _job_response(job, db)


@router.get("/backups/{job_id}", response_model=BackupJobResponse)
async def get_backup_job(
    job_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    job = _get_job_or_404(job_id, db)
    _check_access(current_user, job)
    return _job_response(job, db)


@router.put("/backups/{job_id}", response_model=BackupJobResponse)
async def update_backup_job(
    job_id: int,
    payload: BackupJobUpdate,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    job = _get_job_or_404(job_id, db)
    _check_access(current_user, job)

    updates = payload.model_dump(exclude_unset=True)
    if "sftp_password" in updates:
        if updates["sftp_password"]:
            updates["sftp_password"] = _encrypt(updates["sftp_password"])
        else:
            # Cadena vacía → no tocar la contraseña existente
            updates.pop("sftp_password")

    for field, value in updates.items():
        setattr(job, field, value)
    job.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(job)
    return _job_response(job, db)


@router.delete("/backups/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_backup_job(
    job_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    job = _get_job_or_404(job_id, db)
    _check_access(current_user, job)
    db.delete(job)
    db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Ejecución manual e historial
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/backups/{job_id}/run", response_model=BackupRecordResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_backup_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    payload: BackupRunRequest = BackupRunRequest(),
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Lanza una ejecución del job en segundo plano y devuelve el registro pendiente."""
    job = _get_job_or_404(job_id, db)
    _check_access(current_user, job)

    if not job.is_active:
        raise HTTPException(status_code=400, detail="El job está desactivado")

    record = BackupRecord(
        job_id=job.id,
        user_id=job.user_id,
        status="pending",
        started_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    background_tasks.add_task(_execute_backup, job.id, record.id, payload.force_full)
    return _record_response(record)


@router.get("/backups/{job_id}/records", response_model=List[BackupRecordResponse])
async def list_backup_records(
    job_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Historial de ejecuciones de un job (más reciente primero)."""
    job = _get_job_or_404(job_id, db)
    _check_access(current_user, job)
    records = (
        db.query(BackupRecord)
        .filter(BackupRecord.job_id == job.id)
        .order_by(BackupRecord.started_at.desc())
        .limit(100)
        .all()
    )
    return [_record_response(r) for r in records]


@router.get("/backups/records/{record_id}", response_model=BackupRecordResponse)
async def get_backup_record(
    record_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Devuelve un registro concreto (para refrescar estado/log durante la ejecución)."""
    rec = db.query(BackupRecord).filter(BackupRecord.id == record_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Registro de backup no encontrado")
    job = _get_job_or_404(rec.job_id, db)
    _check_access(current_user, job)
    return _record_response(rec)


# ─────────────────────────────────────────────────────────────────────────────
# Test de conexión SFTP
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/backups/{job_id}/test-sftp")
async def test_sftp(
    job_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Comprueba la conectividad SFTP configurada en el job."""
    job = _get_job_or_404(job_id, db)
    _check_access(current_user, job)
    if job.destination_type != "sftp":
        raise HTTPException(status_code=400, detail="El job no usa destino SFTP")

    try:
        from scripts.backup_manager import BackupManager
        mgr = BackupManager()
        ok, message = mgr.test_sftp_connection(_job_to_config(job))
    except Exception as exc:
        return {"status": "error", "ok": False, "message": str(exc)}

    return {"status": "success" if ok else "error", "ok": ok, "message": message}


# ─────────────────────────────────────────────────────────────────────────────
# Snapshots y restauración
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/backups/{job_id}/snapshots", response_model=List[BackupSnapshotResponse])
async def list_snapshots(
    job_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Lista los snapshots locales disponibles para el dominio del job."""
    job = _get_job_or_404(job_id, db)
    _check_access(current_user, job)
    username, domain_name, _, _ = _owner_and_paths(job, db)
    if not domain_name:
        return []
    try:
        from scripts.backup_manager import BackupManager
        mgr = BackupManager()
        return mgr.list_local_snapshots(job.local_path, username, domain_name)
    except Exception:
        return []


@router.post("/backups/{job_id}/restore", response_model=BackupRecordResponse, status_code=status.HTTP_202_ACCEPTED)
async def restore_backup(
    job_id: int,
    payload: BackupRestoreRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Restaura un snapshot del job en segundo plano y devuelve el registro pendiente."""
    job = _get_job_or_404(job_id, db)
    _check_access(current_user, job)

    if not (payload.restore_files or payload.restore_databases or payload.restore_mail):
        raise HTTPException(status_code=400, detail="Selecciona al menos un contenido a restaurar")

    username, domain_name, _, _ = _owner_and_paths(job, db)
    if not domain_name:
        raise HTTPException(status_code=400, detail="El job no tiene dominio asociado")

    snapshot_path = f"{job.local_path.rstrip('/')}/users/{username}/{domain_name}/{payload.snapshot_name}"
    if not os.path.isdir(snapshot_path):
        raise HTTPException(status_code=404, detail="Snapshot no encontrado en disco")

    record = BackupRecord(
        job_id=job.id,
        user_id=job.user_id,
        kind="restore",
        status="pending",
        backup_path=snapshot_path,
        started_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    background_tasks.add_task(
        _execute_restore, job.id, record.id, payload.snapshot_name,
        payload.restore_files, payload.restore_databases, payload.restore_mail,
    )
    return _record_response(record)
