"""
Importar bases de datos grandes sin phpMyAdmin (ver scripts/db_import.py).

  GET    /databases/{id}/import              → ficheros de ~/imports + estado del import
  GET    /databases/{id}/import/upload       → bytes ya recibidos de una subida (reanudar)
  PUT    /databases/{id}/import/upload       → añade un trozo (cuerpo binario)
  DELETE /databases/{id}/import/files/{name} → borra un fichero (o la subida a medias)
  POST   /databases/{id}/import              → lanza el import en segundo plano
  POST   /databases/{id}/import/cancel       → lo detiene
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from api.models.database import get_db
from api.models.models_client_db import ClientDatabase
from api.models.models_user import User
from api.routes.databases import _assert_can_manage, _check_mariadb_enabled
from scripts import db_import as imp

router = APIRouter()


class ImportStart(BaseModel):
    filename: str
    force: bool = False
    delete_after: bool = False


def _load(db_id: int, db: Session, current_user: User):
    _check_mariadb_enabled()
    cdb = db.query(ClientDatabase).filter(ClientDatabase.id == db_id).first()
    if not cdb:
        raise HTTPException(status_code=404, detail="Base de datos no encontrada")
    _assert_can_manage(current_user, cdb.user_id, db)
    owner = db.query(User).filter(User.id == cdb.user_id).first()
    if not owner:
        raise HTTPException(status_code=404, detail="El dueño de la BD no existe")
    return cdb, owner


def _wrap(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except imp.ImportError_ as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Fichero no encontrado")
    except OSError as e:   # p. ej. ELOOP: un symlink en ~/imports
        raise HTTPException(status_code=400, detail=f"Fichero no válido: {e.strerror}")


@router.get("/databases/{db_id}/import", tags=["Databases"])
def import_overview(db_id: int, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    cdb, owner = _load(db_id, db, current_user)
    data = _wrap(imp.list_files, owner.username)
    data["job"] = imp.status(db_id)
    data["has_password"] = bool(cdb.db_password_enc)
    return data


@router.get("/databases/{db_id}/import/upload", tags=["Databases"])
def upload_offset(db_id: int, name: str = Query(...), size: int = Query(..., gt=0),
                  db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    _, owner = _load(db_id, db, current_user)
    offset = _wrap(imp.upload_offset, owner.username, name, size)
    if offset == 0:
        _wrap(imp.check_space, owner.username, size,
              owner.disk_quota_mb or 0, owner.disk_used_mb or 0)
    return {"offset": offset, "chunk_max": imp.MAX_CHUNK}


@router.put("/databases/{db_id}/import/upload", tags=["Databases"])
async def upload_chunk(db_id: int, request: Request, name: str = Query(...),
                       size: int = Query(..., gt=0), offset: int = Query(..., ge=0),
                       db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    _, owner = _load(db_id, db, current_user)
    data = await request.body()
    return _wrap(imp.append_chunk, owner.username, name, size, offset, data)


@router.delete("/databases/{db_id}/import/files/{name}", tags=["Databases"])
def delete_import_file(db_id: int, name: str, size: Optional[int] = Query(None),
                       db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    _, owner = _load(db_id, db, current_user)
    job = imp.status(db_id)
    if job.get("running") and job.get("file") == name and size is None:
        raise HTTPException(status_code=409, detail="Ese fichero se está importando ahora")
    _wrap(imp.delete_file, owner.username, name, size)
    return {"status": "success"}


@router.post("/databases/{db_id}/import", tags=["Databases"])
def start_import(db_id: int, body: ImportStart, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    cdb, owner = _load(db_id, db, current_user)
    if cdb.is_suspended:
        raise HTTPException(status_code=409, detail="La base de datos está suspendida")
    if not cdb.db_password_enc:
        raise HTTPException(status_code=409, detail=(
            "El panel no tiene guardada la contraseña de esta BD. "
            "Cámbiala desde «Cambiar contraseña» y vuelve a intentarlo."))
    names = {f["name"] for f in _wrap(imp.list_files, owner.username)["files"]}
    if body.filename not in names:
        raise HTTPException(status_code=404, detail=f"No existe {body.filename} en la carpeta imports")
    return _wrap(imp.start, db_id, body.filename, body.force, body.delete_after)


@router.post("/databases/{db_id}/import/cancel", tags=["Databases"])
def cancel_import(db_id: int, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    _load(db_id, db, current_user)
    return imp.cancel(db_id)
