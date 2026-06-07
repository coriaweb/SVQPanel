"""
Migración / importación de backups de otros paneles a SVQPanel.

Fase 1: HestiaCP. Endpoint de ANÁLISIS (no toca el sistema): recibe el .tar
(subido, o por ruta local del servidor), lo extrae a un tmp seguro, parsea su
contenido y devuelve un manifiesto (webs/BDs/correo/DNS) + los conflictos
detectados contra el panel. La importación real se añade en fases siguientes.
"""

import os
import shutil
import tempfile
import logging
from typing import Optional

from datetime import datetime

from fastapi import (APIRouter, Depends, HTTPException, UploadFile, File, Form,
                     BackgroundTasks)
from sqlalchemy.orm import Session

from api.models.database import get_db, SessionLocal
from api.models.models_user import User
from api.dependencies import require_admin

logger = logging.getLogger(__name__)
router = APIRouter()

# Límite de tamaño del backup subido (configurable a futuro).
MAX_BACKUP_MB = 5120  # 5 GB


# ─────────────────────────────────────────────────────────────────────────────
# Obtención del .tar según el origen (upload / path local). URL y SSH: fase 6.
# ─────────────────────────────────────────────────────────────────────────────
async def _receive_backup(upload: Optional[UploadFile], local_path: Optional[str]
                          ) -> str:
    """Deja el .tar en un fichero temporal del servidor y devuelve su ruta.

    El llamador es responsable de borrarlo. Acepta un UploadFile (subida) o una
    ruta local ya presente en el servidor (p. ej. /backups/user.tar).
    """
    if upload is not None and upload.filename:
        fd, tmp = tempfile.mkstemp(prefix="svq_hestia_up_", suffix=".tar")
        os.close(fd)
        max_bytes = MAX_BACKUP_MB * 1024 * 1024
        written = 0
        try:
            with open(tmp, "wb") as fh:
                while chunk := await upload.read(4 * 1024 * 1024):
                    written += len(chunk)
                    if written > max_bytes:
                        raise HTTPException(status_code=413,
                            detail=f"El backup supera el límite de {MAX_BACKUP_MB} MB")
                    fh.write(chunk)
        except HTTPException:
            os.path.exists(tmp) and os.remove(tmp)
            raise
        return tmp

    if local_path:
        if not os.path.isfile(local_path):
            raise HTTPException(status_code=404,
                detail=f"No existe el archivo en el servidor: {local_path}")
        return local_path  # NO se borra (es del usuario); el analyze no lo mueve

    raise HTTPException(status_code=400,
        detail="Indica un archivo de backup (súbelo o da una ruta del servidor).")


def _is_temp_upload(path: str) -> bool:
    return os.path.basename(path).startswith("svq_hestia_up_")


# ─────────────────────────────────────────────────────────────────────────────
# Análisis (preflight) — NO toca el sistema
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/migrations/hestia/analyze")
async def hestia_analyze(
    file: Optional[UploadFile] = File(None),
    path: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Analiza un backup de Hestia y devuelve manifiesto + conflictos.

    No crea nada en el sistema; solo lee el backup y compara con la BD del panel.
    """
    from scripts.hestia_import import HestiaBackup, find_conflicts, HestiaImportError, has_zstd

    tar_path = await _receive_backup(file, path)
    cleanup = _is_temp_upload(tar_path)
    try:
        with HestiaBackup(tar_path) as backup:
            manifest = backup.analyze()
            conflicts = find_conflicts(manifest, db)
    except HestiaImportError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Error analizando backup Hestia")
        raise HTTPException(status_code=500, detail=f"Error analizando el backup: {e}")
    finally:
        if cleanup and os.path.exists(tar_path):
            os.remove(tar_path)

    # ¿Hay datos comprimidos en zst y no tenemos soporte? Avisar (no bloquea analyze).
    warnings = []
    needs_zst = any(
        (w.get("_data_tar") or "").endswith((".zst", ".zstd")) for w in manifest["web"]
    ) or any((d.get("_dump") or "").endswith((".zst", ".zstd")) for d in manifest["db"])
    if needs_zst and not has_zstd():
        warnings.append("El backup usa compresión zstd y el servidor no tiene "
                        "soporte (instala el paquete 'zstd'). La importación de "
                        "esos datos fallará hasta instalarlo.")

    # Limpiar campos internos (_data_tar, _conf_dir…) antes de enviar al cliente.
    def _clean(items):
        return [{k: v for k, v in it.items() if not k.startswith("_")} for it in items]

    return {
        "status": "success",
        "data": {
            "system": manifest["system"],
            "user": manifest["user"],
            "web": _clean(manifest["web"]),
            "db": _clean(manifest["db"]),
            "mail": [{**{k: v for k, v in m.items() if not k.startswith("_")},
                      "accounts_count": len(m["accounts"])} for m in manifest["mail"]],
            "dns": _clean(manifest["dns"]),
            "conflicts": conflicts,
            "importable": len(conflicts) == 0,
            "warnings": warnings,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Importación (background) — solo si el preflight de conflictos pasa
# ─────────────────────────────────────────────────────────────────────────────
def _run_import_job(job_id: int, tar_path: str, cleanup_tar: bool):
    """Ejecuta la importación en segundo plano y actualiza el MigrationJob."""
    import json
    from scripts.hestia_import import run_import
    from api.models.models_migration import MigrationJob

    db = SessionLocal()
    try:
        job = db.query(MigrationJob).filter(MigrationJob.id == job_id).first()
        if not job:
            return
        job.status = "running"
        job.started_at = datetime.utcnow()
        db.commit()

        scope = [s for s in (job.scope or "").split(",") if s]
        report = run_import(tar_path, job.target_user_id, scope, db)

        job.report_json = json.dumps(report, ensure_ascii=False)
        job.status = "failed" if report["summary"]["errors"] and not report["summary"]["created"] else "success"
        job.finished_at = datetime.utcnow()
        db.commit()
    except Exception as e:
        logger.exception("Error en job de importación Hestia")
        try:
            job = db.query(MigrationJob).filter(MigrationJob.id == job_id).first()
            if job:
                job.status = "failed"
                job.error = str(e)
                job.finished_at = datetime.utcnow()
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
        if cleanup_tar and os.path.exists(tar_path):
            try:
                os.remove(tar_path)
            except OSError:
                pass


@router.post("/migrations/hestia/import")
async def hestia_import(
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(None),
    path: Optional[str] = Form(None),
    target_user_id: int = Form(...),
    scope: str = Form("web,db,mail,dns"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Importa un backup de Hestia al usuario destino (en segundo plano).

    Hace el preflight de conflictos: si hay alguno, ABORTA con 409 (no toca nada).
    Si no, crea un MigrationJob y lanza la importación en background; devuelve el
    job_id para hacer polling de su estado.
    """
    import json
    from scripts.hestia_import import HestiaBackup, find_conflicts, HestiaImportError
    from api.models.models_migration import MigrationJob

    # Validar usuario destino (cliente, no admin)
    target = db.query(User).filter(User.id == target_user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario destino no encontrado")
    if target.role == "admin" or target.is_admin:
        raise HTTPException(status_code=403,
            detail="El destino debe ser una cuenta de cliente, no un administrador.")

    tar_path = await _receive_backup(file, path)
    cleanup_tar = _is_temp_upload(tar_path)

    # Preflight: analizar y comprobar conflictos. Si hay, abortar.
    try:
        with HestiaBackup(tar_path) as backup:
            manifest = backup.analyze()
            conflicts = find_conflicts(manifest, db)
    except HestiaImportError as e:
        if cleanup_tar and os.path.exists(tar_path):
            os.remove(tar_path)
        raise HTTPException(status_code=422, detail=str(e))

    if conflicts:
        if cleanup_tar and os.path.exists(tar_path):
            os.remove(tar_path)
        raise HTTPException(status_code=409, detail={
            "message": "La importación se ha cancelado: hay recursos que ya existen.",
            "conflicts": conflicts,
        })

    # Crear el job y lanzar en background.
    job = MigrationJob(
        source_type="upload" if cleanup_tar else "path",
        source_kind=manifest.get("system") or "hestia",
        target_user_id=target_user_id,
        status="pending",
        scope=scope,
        manifest_json=json.dumps({"system": manifest["system"],
                                  "web": len(manifest["web"]),
                                  "db": len(manifest["db"]),
                                  "mail": len(manifest["mail"]),
                                  "dns": len(manifest["dns"])}),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(_run_import_job, job.id, tar_path, cleanup_tar)
    return {"status": "success", "data": {"job_id": job.id, "status": "pending"}}


@router.get("/migrations/jobs/{job_id}")
async def migration_job_status(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Estado y, si terminó, informe de un job de importación."""
    import json
    from api.models.models_migration import MigrationJob
    job = db.query(MigrationJob).filter(MigrationJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return {"status": "success", "data": {
        "id": job.id,
        "status": job.status,
        "scope": job.scope,
        "target_user_id": job.target_user_id,
        "manifest": json.loads(job.manifest_json) if job.manifest_json else None,
        "report": json.loads(job.report_json) if job.report_json else None,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }}
