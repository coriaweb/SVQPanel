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
import secrets
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


def _check_access(current_user: User, job: BackupJob, db: Session = None):
    """Acceso de gestión completo (editar/borrar/ejecutar): admin o dueño del job."""
    if not current_user.is_admin and job.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes permiso sobre este backup")


def _check_view_access(current_user: User, job: BackupJob, db: Session):
    """Acceso de VISTA/RESTAURACIÓN: admin, dueño del job, o cliente cuyos
    dominios estén incluidos en el backup (p. ej. un backup global del admin)."""
    if current_user.is_admin or job.user_id == current_user.id:
        return
    if _job_covers_user(job, current_user, db):
        return
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
    resp.s3_secret_key = None
    resp.restic_password = None        # nunca devolver el cifrado
    resp.restic_password_plain = None  # solo en la respuesta de creación
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
        "s3_endpoint":       job.s3_endpoint,
        "s3_region":         job.s3_region,
        "s3_bucket":         job.s3_bucket,
        "s3_prefix":         job.s3_prefix,
        "s3_access_key":     job.s3_access_key,
        "s3_secret_key":     _decrypt(job.s3_secret_key) if job.s3_secret_key else None,
        "restic_password":   _decrypt(job.restic_password) if job.restic_password else None,
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


def _job_covers_user(job: BackupJob, user: User, db: Session) -> bool:
    """True si el backup del job incluye algún dominio del usuario `user`.
    Se usa para que un CLIENTE vea/restaure los backups (incluidos los creados
    por el ADMIN) que cubren sus propios dominios."""
    if job.user_id == user.id:
        return True
    for domain, owner in _domains_for_job(job, db):
        if owner and owner.id == user.id:
            return True
    return False


def _user_domains_in_job(job: BackupJob, user: User, db: Session) -> list:
    """Dominios del usuario `user` que respalda este job (para un admin: todos).
    Devuelve lista de (domain, owner)."""
    pairs = _domains_for_job(job, db)
    if user.is_admin:
        return pairs
    return [(d, o) for (d, o) in pairs if o and o.id == user.id]


def _resolve_target(job: BackupJob, user: User, db: Session, domain_name: str = None):
    """Resuelve (username, domain) sobre el que operar (snapshots/restore),
    validando que el usuario tenga derecho. Para jobs de un solo dominio usa ese;
    para jobs globales requiere `domain_name` y lo valida.
    Devuelve (username, domain_name) o lanza HTTPException."""
    pairs = _user_domains_in_job(job, user, db)  # solo dominios que el user puede ver
    if not pairs:
        raise HTTPException(status_code=403, detail="No tienes dominios en este backup")

    if domain_name:
        for d, o in pairs:
            if d.domain_name == domain_name:
                return (o.username if o else "root"), d.domain_name
        raise HTTPException(status_code=403, detail="Ese dominio no está en este backup o no es tuyo")

    # Sin dominio explícito: si solo hay uno, usarlo; si hay varios, hace falta elegir
    if len(pairs) == 1:
        d, o = pairs[0]
        return (o.username if o else "root"), d.domain_name
    raise HTTPException(status_code=400,
                        detail="Este backup cubre varios dominios; indica cuál con ?domain=")


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
        from scripts import restic_manager
        job_config = _job_to_config(job)

        domains_to_backup = _domains_for_job(job, db)

        all_log: list[str] = []
        total_size = 0
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
            res = restic_manager.run_backup(
                job_config, username, domain_name,
                files_path=files_path, mail_path=mail_path, databases=databases,
            )
            all_log.extend([l for l in res["log"] if l])
            total_size        += res["size_bytes"]
            total_files_total += res["files_total"]
            total_db_count    += res["db_count"]
            last_path          = res.get("repo")
            if res["status"] == "failed":
                any_failed = True
                all_log.append(f"ERROR {domain_name}: {res['error']}")

        record.status            = "failed" if any_failed else "success"
        record.backup_path       = last_path
        record.size_bytes        = total_size
        record.files_transferred = total_files_total
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
    """Lista los jobs de backup visibles para el usuario.

    Admin: todos. Cliente: los suyos + los que incluyan sus dominios (p. ej. un
    backup global creado por el admin), marcados como de solo lectura para que la
    UI muestre que son "del administrador".
    """
    if current_user.is_admin:
        jobs = db.query(BackupJob).order_by(BackupJob.created_at.desc()).all()
        return [_job_response(j, db) for j in jobs]

    # Cliente: sus jobs + los que cubren alguno de sus dominios
    all_jobs = db.query(BackupJob).order_by(BackupJob.created_at.desc()).all()
    out = []
    for j in all_jobs:
        if j.user_id == current_user.id:
            out.append(_job_response(j, db))
        elif _job_covers_user(j, current_user, db):
            resp = _job_response(j, db)
            resp.managed_by_admin = True   # el cliente no puede editar/borrar
            out.append(resp)
    return out


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
    if payload.destination_type == "s3" and (not payload.s3_bucket or not payload.s3_access_key):
        raise HTTPException(status_code=400, detail="Bucket y access key son obligatorios para destino S3")

    data = payload.model_dump()
    if data.get("sftp_password"):
        data["sftp_password"] = _encrypt(data["sftp_password"])
    if data.get("s3_secret_key"):
        data["s3_secret_key"] = _encrypt(data["s3_secret_key"])

    # Contraseña de cifrado restic: la que ponga el usuario, o una autogenerada.
    # Se devuelve UNA vez en texto claro (restic_password_plain) para que la anote;
    # en BD se guarda cifrada. Sin ella los backups son irrecuperables.
    plain_pw = data.pop("restic_password", None) or secrets.token_urlsafe(24)
    data["restic_password"] = _encrypt(plain_pw)

    job = BackupJob(user_id=current_user.id, **data)
    db.add(job)
    db.commit()
    db.refresh(job)
    resp = _job_response(job, db)
    # Inyectar la contraseña en claro solo en esta respuesta de creación
    resp.restic_password_plain = plain_pw
    return resp


@router.get("/backups/{job_id}", response_model=BackupJobResponse)
async def get_backup_job(
    job_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    job = _get_job_or_404(job_id, db)
    _check_view_access(current_user, job, db)
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
    if "s3_secret_key" in updates:
        if updates["s3_secret_key"]:
            updates["s3_secret_key"] = _encrypt(updates["s3_secret_key"])
        else:
            updates.pop("s3_secret_key")
    # La contraseña de cifrado restic NO se cambia tras crear el repo (cambiarla
    # dejaría los backups existentes irrecuperables).
    updates.pop("restic_password", None)

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
# Test de conexión (restic: crea/accede al repositorio en el destino)
# ─────────────────────────────────────────────────────────────────────────────
async def _test_connection(job_id, current_user, db):
    job = _get_job_or_404(job_id, db)
    _check_access(current_user, job)
    username, domain_name, _, _ = _owner_and_paths(job, db)
    if not domain_name:
        return {"status": "error", "ok": False, "message": "El job no tiene dominio asociado"}
    try:
        from scripts import restic_manager
        ok, message = restic_manager.test_connection(_job_to_config(job), username, domain_name)
    except Exception as exc:
        return {"status": "error", "ok": False, "message": str(exc)}
    return {"status": "success" if ok else "error", "ok": ok, "message": message}


@router.post("/backups/{job_id}/test-sftp")
async def test_sftp(job_id: int, current_user: User = Depends(require_auth),
                    db: Session = Depends(get_db)):
    """Comprueba el destino del job (crea/accede al repositorio restic)."""
    return await _test_connection(job_id, current_user, db)


@router.post("/backups/{job_id}/test-s3")
async def test_s3(job_id: int, current_user: User = Depends(require_auth),
                  db: Session = Depends(get_db)):
    """Comprueba el destino del job (crea/accede al repositorio restic)."""
    return await _test_connection(job_id, current_user, db)


# ─────────────────────────────────────────────────────────────────────────────
# Snapshots y restauración
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/backups/{job_id}/domains")
async def job_domains(job_id: int, current_user: User = Depends(require_auth),
                      db: Session = Depends(get_db)):
    """Lista los dominios de este backup que el usuario puede ver/restaurar.
    Para un cliente, solo sus dominios; para el admin, todos."""
    job = _get_job_or_404(job_id, db)
    _check_view_access(current_user, job, db)
    pairs = _user_domains_in_job(job, current_user, db)
    return [{"domain": d.domain_name, "owner": (o.username if o else None)}
            for d, o in pairs]


@router.get("/backups/{job_id}/snapshots")
async def list_snapshots(
    job_id: int,
    domain: str = None,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Snapshots restic del dominio indicado dentro del job (máquina del tiempo).
    Un cliente solo ve los de sus dominios; el admin, cualquiera."""
    job = _get_job_or_404(job_id, db)
    _check_view_access(current_user, job, db)
    username, domain_name = _resolve_target(job, current_user, db, domain)
    try:
        from scripts import restic_manager
        return restic_manager.list_snapshots(_job_to_config(job), username, domain_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listando snapshots: {e}")


@router.get("/backups/{job_id}/snapshots/{snapshot_id}/contents")
async def snapshot_contents(job_id: int, snapshot_id: str, domain: str = None,
                            current_user: User = Depends(require_auth),
                            db: Session = Depends(get_db)):
    """Qué se puede restaurar de un snapshot: web, buzones y BBDD concretas.
    Permite al usuario elegir granularmente qué restaurar."""
    job = _get_job_or_404(job_id, db)
    _check_view_access(current_user, job, db)
    username, domain_name = _resolve_target(job, current_user, db, domain)
    try:
        from scripts import restic_manager
        return restic_manager.list_snapshot_contents(
            _job_to_config(job), username, domain_name, snapshot_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error leyendo el snapshot: {e}")


@router.post("/backups/{job_id}/restore", response_model=BackupRecordResponse, status_code=status.HTTP_202_ACCEPTED)
async def restore_backup(
    job_id: int,
    payload: BackupRestoreRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Restaura un snapshot restic a una carpeta de recuperación (segura) en el
    home del dominio: /home/{user}/restore/{snapshot}/. No sobrescribe la web en
    vivo; el usuario revisa y copia lo que necesite.
    """
    job = _get_job_or_404(job_id, db)
    _check_view_access(current_user, job, db)

    if not payload.snapshot_name:
        raise HTTPException(status_code=400, detail="Falta el snapshot a restaurar")
    # Resuelve y valida el dominio del usuario (cliente: solo el suyo)
    username, domain_name = _resolve_target(job, current_user, db, payload.domain)

    # Copia antigua: restaurar completa (sin granularidad)
    if payload.legacy:
        selection = {"legacy": True}
    else:
        selection = {
            "web": payload.web or (not payload.mail and not payload.databases and payload.restore_files),
            "mail": payload.mail,
            "databases": payload.databases,
        }
        if not (selection["web"] or selection["mail"] or selection["databases"]):
            # nada explícito → restaurar todo lo del snapshot
            selection = {"web": True, "mail": ["*"], "databases": ["*"]}

    record = BackupRecord(
        job_id=job.id, user_id=current_user.id, kind="restore", status="pending",
        started_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    background_tasks.add_task(
        _execute_restic_restore, job.id, record.id, username, domain_name,
        payload.snapshot_name, selection, payload.overwrite,
    )
    return _record_response(record)


def _execute_restic_restore(job_id, record_id, username, domain, snapshot_id,
                            selection, overwrite):
    """Tarea de fondo: aplica la restauración (modo + selección granular)."""
    dbs = SessionLocal()
    try:
        job = dbs.query(BackupJob).filter(BackupJob.id == job_id).first()
        rec = dbs.query(BackupRecord).filter(BackupRecord.id == record_id).first()
        if not job or not rec:
            return
        rec.status = "running"
        dbs.commit()

        from scripts import restic_manager
        # Expandir comodines "*" a lo que haya en el snapshot
        if "*" in selection.get("mail", []) or "*" in selection.get("databases", []):
            contents = restic_manager.list_snapshot_contents(
                _job_to_config(job), username, domain, snapshot_id)
            if "*" in selection["mail"]:
                selection["mail"] = contents.get("mail", [])
            if "*" in selection["databases"]:
                selection["databases"] = contents.get("databases", [])

        res = restic_manager.apply_restore(
            _job_to_config(job), username, domain, snapshot_id,
            selection, overwrite)
        rec.status = "success" if res["ok"] else "failed"
        rec.backup_path = res.get("target")
        rec.log_output = (res.get("message") or "")[:50000]
        rec.error_message = None if res["ok"] else (res.get("message") or "Fallo en la restauración")
        rec.finished_at = datetime.utcnow()
        dbs.commit()
    except Exception as e:
        try:
            rec = dbs.query(BackupRecord).filter(BackupRecord.id == record_id).first()
            if rec:
                rec.status = "failed"
                rec.error_message = str(e)
                rec.finished_at = datetime.utcnow()
                dbs.commit()
        except Exception:
            pass
    finally:
        dbs.close()
