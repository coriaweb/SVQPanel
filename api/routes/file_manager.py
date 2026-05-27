"""
Administrador de archivos integrado para dominios.

Todas las operaciones quedan encerradas en el public_html del dominio elegido.
"""

import mimetypes
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import require_auth
from api.models.database import get_db
from api.models.models_domain import Domain
from api.models.models_user import User

router = APIRouter()

FILE_MANAGER_ENABLED = os.getenv("FILE_MANAGER_ENABLED", "true").lower() == "true"
FILE_MANAGER_MAX_UPLOAD_MB = int(os.getenv("FILE_MANAGER_MAX_UPLOAD_MB", "100"))
MAX_TEXT_FILE_BYTES = int(os.getenv("FILE_MANAGER_MAX_TEXT_FILE_MB", "2")) * 1024 * 1024


class FileEntry(BaseModel):
    name: str
    path: str
    type: str
    size: int
    modified_at: Optional[datetime] = None
    mime_type: Optional[str] = None
    permissions: Optional[str] = None


class DomainFileRoot(BaseModel):
    id: int
    domain_name: str
    public_html: str

    class Config:
        from_attributes = True


class DirectoryCreate(BaseModel):
    path: str = ""
    name: str = Field(..., min_length=1, max_length=120)


class RenameRequest(BaseModel):
    path: str = Field(..., min_length=1)
    new_name: str = Field(..., min_length=1, max_length=120)


class DeleteRequest(BaseModel):
    path: str = Field(..., min_length=1)


class TextFileUpdate(BaseModel):
    content: str


def _check_enabled():
    if not FILE_MANAGER_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El administrador de archivos no está habilitado en este servidor.",
        )


def _domain_query_for_user(db: Session, current_user: User):
    query = db.query(Domain)
    if current_user.role == "admin":
        return query
    if current_user.role == "reseller":
        client_ids = [u.id for u in db.query(User.id).filter(User.parent_id == current_user.id).all()]
        client_ids.append(current_user.id)
        return query.filter(Domain.user_id.in_(client_ids))
    return query.filter(Domain.user_id == current_user.id)


def _get_domain_or_404(domain_id: int, db: Session, current_user: User) -> Domain:
    domain = _domain_query_for_user(db, current_user).filter(Domain.id == domain_id).first()
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado o sin permisos")
    if not domain.public_html:
        raise HTTPException(status_code=409, detail="El dominio no tiene public_html configurado")
    return domain


def _safe_join(root: str, requested_path: str = "") -> str:
    root_path = os.path.realpath(root)
    rel = (requested_path or "").replace("\\", "/").lstrip("/")
    target = os.path.realpath(os.path.join(root_path, rel))

    if os.path.commonpath([root_path, target]) != root_path:
        raise HTTPException(status_code=400, detail="Ruta fuera del dominio")
    return target


def _safe_child_name(name: str) -> str:
    if "/" in name or "\\" in name or name in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail="Nombre inválido")
    return name


def _relative_path(root: str, target: str) -> str:
    rel = os.path.relpath(target, root).replace("\\", "/")
    return "" if rel == "." else rel


def _file_entry(root: str, target: str) -> FileEntry:
    stat = os.stat(target)
    is_dir = os.path.isdir(target)
    rel = _relative_path(root, target)
    mime_type = None if is_dir else mimetypes.guess_type(target)[0]
    return FileEntry(
        name=os.path.basename(target),
        path=rel,
        type="directory" if is_dir else "file",
        size=0 if is_dir else stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime),
        mime_type=mime_type,
        permissions=oct(stat.st_mode)[-3:],
    )


def _apply_domain_owner(domain: Domain, target: str):
    """Deja lo creado desde el panel a nombre del usuario propietario del dominio."""
    username = domain.user.username if domain.user else None
    if not username:
        return
    try:
        shutil.chown(target, user=username, group=username)
    except Exception:
        pass


@router.get("/file-manager/domains", response_model=List[DomainFileRoot], tags=["File Manager"])
def list_file_manager_domains(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Lista dominios visibles por el usuario actual."""
    _check_enabled()
    return _domain_query_for_user(db, current_user).order_by(Domain.domain_name.asc()).all()


@router.get("/file-manager/domains/{domain_id}/files", response_model=List[FileEntry], tags=["File Manager"])
def list_files(
    domain_id: int,
    path: str = Query("", description="Ruta relativa dentro de public_html"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Lista archivos y carpetas dentro de un dominio."""
    _check_enabled()
    domain = _get_domain_or_404(domain_id, db, current_user)
    root = os.path.realpath(domain.public_html)
    target = _safe_join(root, path)

    if not os.path.isdir(target):
        raise HTTPException(status_code=404, detail="Carpeta no encontrada")

    entries = [_file_entry(root, os.path.join(target, name)) for name in os.listdir(target)]
    return sorted(entries, key=lambda item: (item.type != "directory", item.name.lower()))


@router.get("/file-manager/domains/{domain_id}/file", tags=["File Manager"])
def read_text_file(
    domain_id: int,
    path: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Lee un archivo de texto pequeño para edición en el navegador."""
    _check_enabled()
    domain = _get_domain_or_404(domain_id, db, current_user)
    target = _safe_join(domain.public_html, path)

    if not os.path.isfile(target):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    if os.path.getsize(target) > MAX_TEXT_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Archivo demasiado grande para editarlo en el panel")

    try:
        content = Path(target).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=415, detail="El archivo no parece ser texto UTF-8")

    return {"path": path, "content": content}


@router.put("/file-manager/domains/{domain_id}/file", tags=["File Manager"])
def write_text_file(
    domain_id: int,
    payload: TextFileUpdate,
    path: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Guarda un archivo de texto dentro del dominio."""
    _check_enabled()
    domain = _get_domain_or_404(domain_id, db, current_user)
    target = _safe_join(domain.public_html, path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    Path(target).write_text(payload.content, encoding="utf-8")
    _apply_domain_owner(domain, target)
    return {"status": "success", "path": path}


@router.get("/file-manager/domains/{domain_id}/download", tags=["File Manager"])
def download_file(
    domain_id: int,
    path: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Descarga un archivo del dominio."""
    _check_enabled()
    domain = _get_domain_or_404(domain_id, db, current_user)
    target = _safe_join(domain.public_html, path)
    if not os.path.isfile(target):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(target, filename=os.path.basename(target))


@router.post("/file-manager/domains/{domain_id}/upload", tags=["File Manager"])
async def upload_files(
    domain_id: int,
    path: str = Form(""),
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Sube uno o varios archivos a una carpeta del dominio."""
    _check_enabled()
    domain = _get_domain_or_404(domain_id, db, current_user)
    target_dir = _safe_join(domain.public_html, path)
    if not os.path.isdir(target_dir):
        raise HTTPException(status_code=404, detail="Carpeta no encontrada")

    max_bytes = FILE_MANAGER_MAX_UPLOAD_MB * 1024 * 1024
    saved = []
    for upload in files:
        filename = _safe_child_name(upload.filename or "")
        destination = _safe_join(target_dir, filename)
        written = 0
        with open(destination, "wb") as fh:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    fh.close()
                    os.remove(destination)
                    raise HTTPException(
                        status_code=413,
                        detail=f"'{filename}' supera el limite de {FILE_MANAGER_MAX_UPLOAD_MB} MB",
                    )
                fh.write(chunk)
        _apply_domain_owner(domain, destination)
        saved.append(filename)

    return {"status": "success", "files": saved}


@router.post("/file-manager/domains/{domain_id}/mkdir", tags=["File Manager"])
def create_directory(
    domain_id: int,
    payload: DirectoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Crea una carpeta dentro del dominio."""
    _check_enabled()
    domain = _get_domain_or_404(domain_id, db, current_user)
    parent = _safe_join(domain.public_html, payload.path)
    if not os.path.isdir(parent):
        raise HTTPException(status_code=404, detail="Carpeta padre no encontrada")
    target = _safe_join(parent, _safe_child_name(payload.name))
    os.makedirs(target, exist_ok=False)
    _apply_domain_owner(domain, target)
    return {"status": "success", "path": _relative_path(os.path.realpath(domain.public_html), target)}


@router.post("/file-manager/domains/{domain_id}/rename", tags=["File Manager"])
def rename_entry(
    domain_id: int,
    payload: RenameRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Renombra un archivo o carpeta."""
    _check_enabled()
    domain = _get_domain_or_404(domain_id, db, current_user)
    root = os.path.realpath(domain.public_html)
    source = _safe_join(root, payload.path)
    if not os.path.exists(source):
        raise HTTPException(status_code=404, detail="Elemento no encontrado")
    destination = _safe_join(os.path.dirname(source), _safe_child_name(payload.new_name))
    os.rename(source, destination)
    _apply_domain_owner(domain, destination)
    return {"status": "success", "path": _relative_path(root, destination)}


@router.post("/file-manager/domains/{domain_id}/delete", status_code=status.HTTP_204_NO_CONTENT, tags=["File Manager"])
def delete_entry(
    domain_id: int,
    payload: DeleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Elimina un archivo o carpeta dentro del dominio."""
    _check_enabled()
    domain = _get_domain_or_404(domain_id, db, current_user)
    target = _safe_join(domain.public_html, payload.path)
    if not os.path.exists(target):
        raise HTTPException(status_code=404, detail="Elemento no encontrado")
    if os.path.isdir(target):
        shutil.rmtree(target)
    else:
        os.remove(target)
    return None
