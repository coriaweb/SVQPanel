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

from fastapi import (APIRouter, Depends, HTTPException, UploadFile, File, Form)
from sqlalchemy.orm import Session

from api.models.database import get_db
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
