"""
Administrador de archivos integrado para dominios.

Todas las operaciones quedan encerradas en el public_html del dominio elegido.
"""

import mimetypes
import os
import shutil
import tarfile
import zipfile
from datetime import datetime, timezone
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
from api.models.models_settings import Settings

router = APIRouter()

FILE_MANAGER_ENABLED = os.getenv("FILE_MANAGER_ENABLED", "true").lower() == "true"


def get_upload_limits(db: Session) -> tuple[int, int, int]:
    """Obtiene los límites de upload desde Settings. Retorna (max_upload_mb, max_text_mb, max_extract_mb)"""
    settings = db.query(Settings).filter(Settings.id == 1).first()
    if not settings:
        return 2048, 2, 5120
    return settings.max_upload_mb, settings.max_text_file_mb, settings.max_extract_mb


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


class ExtractRequest(BaseModel):
    path: str = Field(..., min_length=1, description="Ruta relativa al ZIP dentro de public_html")
    dest: str = Field("", description="Carpeta destino relativa; vacío = misma carpeta del ZIP")


class ChmodRequest(BaseModel):
    path: str = Field(..., min_length=1)
    mode: str = Field(..., pattern=r"^[0-7]{3,4}$", description="Permisos en octal, p.ej. '644' o '755'")


class TransferRequest(BaseModel):
    """Mover o copiar varios elementos a una carpeta destino.

    El destino puede estar en OTRO dominio (``dest_domain_id``) siempre que sea
    del mismo propietario; ver ``_resolve_dest_domain``.
    """
    paths: List[str] = Field(..., min_length=1, max_length=500)
    dest: str = Field("", description="Carpeta destino relativa; vacío = raíz de public_html")
    overwrite: bool = Field(False, description="Si el destino ya existe, reemplazarlo")
    dest_domain_id: Optional[int] = Field(
        None, description="Dominio destino; vacío = el mismo dominio de origen"
    )


class CompressRequest(BaseModel):
    paths: List[str] = Field(..., min_length=1, max_length=500)
    dest: str = Field("", description="Carpeta donde dejar el ZIP; vacío = raíz de public_html")
    name: str = Field(..., min_length=1, max_length=120, description="Nombre del ZIP resultante")


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
        modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
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

    _, max_text_mb, _ = get_upload_limits(db)
    max_text_bytes = max_text_mb * 1024 * 1024
    if os.path.getsize(target) > max_text_bytes:
        raise HTTPException(status_code=413, detail=f"Archivo demasiado grande (máximo {max_text_mb} MB)")

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
    overwrite: bool = Form(True),
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Sube uno o varios archivos a una carpeta del dominio.

    Si ``overwrite=false`` los archivos que ya existen se omiten (no sobreescriben).
    """
    _check_enabled()
    domain = _get_domain_or_404(domain_id, db, current_user)
    target_dir = _safe_join(domain.public_html, path)
    if not os.path.isdir(target_dir):
        raise HTTPException(status_code=404, detail="Carpeta no encontrada")

    max_upload_mb, _, _ = get_upload_limits(db)
    max_bytes = max_upload_mb * 1024 * 1024
    saved: list[str] = []
    skipped: list[str] = []

    for upload in files:
        filename = _safe_child_name(upload.filename or "")
        destination = _safe_join(target_dir, filename)

        if not overwrite and os.path.exists(destination):
            await upload.read()   # vaciar el stream aunque no escribamos
            skipped.append(filename)
            continue

        written = 0
        with open(destination, "wb") as fh:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    fh.close()
                    os.remove(destination)
                    raise HTTPException(
                        status_code=413,
                        detail=f"El archivo '{filename}' supera el límite de {max_upload_mb} MB",
                    )
                fh.write(chunk)
        _apply_domain_owner(domain, destination)
        saved.append(filename)

    return {"status": "success", "files": saved, "skipped": skipped}


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


@router.post("/file-manager/domains/{domain_id}/extract", tags=["File Manager"])
def extract_zip(
    domain_id: int,
    payload: ExtractRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Extrae un archivo ZIP dentro del dominio.

    Por defecto extrae en la misma carpeta donde está el ZIP.
    Se puede indicar un ``dest`` relativo para extraer en otro lugar.
    Protege contra path-traversal y ZIP bombs.
    """
    _check_enabled()
    domain = _get_domain_or_404(domain_id, db, current_user)
    root = os.path.realpath(domain.public_html)
    zip_path = _safe_join(root, payload.path)

    if not os.path.isfile(zip_path):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    low = zip_path.lower()
    is_zip = low.endswith(".zip")
    is_tar = low.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz"))
    if not (is_zip or is_tar):
        raise HTTPException(status_code=400,
            detail="Formato no soportado. Usa .zip o .tar(.gz/.bz2/.xz)")

    # Carpeta destino
    if payload.dest:
        dest_dir = _safe_join(root, payload.dest)
    else:
        dest_dir = os.path.dirname(zip_path)
    os.makedirs(dest_dir, exist_ok=True)

    _, _, max_extract_mb = get_upload_limits(db)
    max_extract_bytes = max_extract_mb * 1024 * 1024

    def _escapes(member_name: str) -> bool:
        """True si el miembro escaparía la carpeta del dominio (path traversal)."""
        member_real = os.path.realpath(os.path.join(dest_dir, member_name))
        return os.path.commonpath([root, member_real]) != root

    try:
        if is_zip:
            with zipfile.ZipFile(zip_path, "r") as zf:
                members = zf.infolist()
                total_bytes = 0
                for member in members:
                    if _escapes(member.filename):
                        raise HTTPException(status_code=400,
                            detail=f"El archivo contiene una ruta que escapa el dominio: {member.filename}")
                    total_bytes += member.file_size
                    if total_bytes > max_extract_bytes:
                        raise HTTPException(status_code=413,
                            detail=f"El contenido descomprimido supera el límite de {max_extract_mb} MB")
                extracted_count = len(members)
                zf.extractall(dest_dir)
        else:
            # tar(.gz/.bz2/.xz): mismas protecciones (path traversal + bomba).
            with tarfile.open(zip_path, "r:*") as tf:
                members = tf.getmembers()
                total_bytes = 0
                for member in members:
                    if _escapes(member.name):
                        raise HTTPException(status_code=400,
                            detail=f"El archivo contiene una ruta que escapa el dominio: {member.name}")
                    # No extraer enlaces que apunten fuera del dominio.
                    if (member.issym() or member.islnk()):
                        link_real = os.path.realpath(os.path.join(dest_dir, os.path.dirname(member.name), member.linkname))
                        if os.path.commonpath([root, link_real]) != root:
                            raise HTTPException(status_code=400,
                                detail=f"El archivo contiene un enlace inseguro: {member.name}")
                    total_bytes += member.size
                    if total_bytes > max_extract_bytes:
                        raise HTTPException(status_code=413,
                            detail=f"El contenido descomprimido supera el límite de {max_extract_mb} MB")
                extracted_count = len(members)
                try:
                    tf.extractall(dest_dir, filter="data")  # Python ≥ 3.12
                except TypeError:
                    tf.extractall(dest_dir)                 # validado arriba

    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Archivo ZIP dañado o inválido")
    except tarfile.TarError:
        raise HTTPException(status_code=400, detail="Archivo TAR dañado o inválido")

    # Cambiar propiedad de los ficheros recién extraídos al dueño del dominio
    username = domain.user.username if domain.user else None
    if username:
        for dirpath, dirnames, filenames in os.walk(dest_dir):
            try:
                shutil.chown(dirpath, user=username, group=username)
            except Exception:
                pass
            for fname in filenames:
                try:
                    shutil.chown(os.path.join(dirpath, fname), user=username, group=username)
                except Exception:
                    pass

    return {
        "status": "success",
        "dest": _relative_path(root, dest_dir),
        "files_extracted": extracted_count,
    }


def _tree_size(target: str) -> int:
    """Tamaño total en bytes de un archivo o de un árbol de carpetas.

    No sigue symlinks: cuenta el enlace, no su destino (que puede estar fuera
    del dominio o generar un bucle).
    """
    if os.path.islink(target) or os.path.isfile(target):
        try:
            return os.lstat(target).st_size
        except OSError:
            return 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(target, followlinks=False):
        for fname in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, fname)).st_size
            except OSError:
                continue
    return total


def _assert_inside(root: str, target: str, label: str = "elemento"):
    """Aborta si 'target' (ya resuelto) cae fuera de la raíz del dominio.

    _safe_join ya valida la ruta pedida, pero un symlink *dentro* del dominio
    puede apuntar fuera: al mover/copiar/comprimir seguiríamos ese enlace y
    sacaríamos (o meteríamos) datos ajenos al dominio.
    """
    real = os.path.realpath(target)
    if os.path.commonpath([root, real]) != root:
        raise HTTPException(
            status_code=400,
            detail=f"El {label} apunta fuera del dominio y no se puede procesar",
        )


def _escaping_links_ignore(root: str):
    """Callback 'ignore' para copytree: omite symlinks que apunten fuera del dominio.

    Sin esto, copiar una carpeta que contenga un enlace a /etc o al home de otro
    cliente reproduciría ese enlace en el destino, dejando datos ajenos
    alcanzables desde el public_html.
    """
    def _ignore(dirpath: str, names: list[str]) -> set[str]:
        skipped = set()
        for name in names:
            full = os.path.join(dirpath, name)
            if not os.path.islink(full):
                continue
            if os.path.commonpath([root, os.path.realpath(full)]) != root:
                skipped.add(name)
        return skipped
    return _ignore


def _unique_destination(dest_dir: str, name: str) -> str:
    """Devuelve una ruta libre en dest_dir para 'name' añadiendo ' (copia N)'.

    Se usa cuando el destino ya existe y NO se pidió sobreescribir: así una copia
    en la misma carpeta (el caso típico de "duplicar archivo") no falla.
    """
    base, ext = os.path.splitext(name)
    # Los .tar.gz y compañía llevan doble extensión: conservarla entera.
    if base.lower().endswith(".tar"):
        base, ext = base[:-4], ".tar" + ext
    candidate = os.path.join(dest_dir, name)
    index = 1
    while os.path.exists(candidate):
        suffix = " (copia)" if index == 1 else f" (copia {index})"
        candidate = os.path.join(dest_dir, f"{base}{suffix}{ext}")
        index += 1
    return candidate


def _chown_tree(domain: Domain, target: str):
    """Aplica el owner del dominio a un elemento y, si es carpeta, a su contenido."""
    _apply_domain_owner(domain, target)
    if not os.path.isdir(target):
        return
    for dirpath, _dirnames, filenames in os.walk(target):
        _apply_domain_owner(domain, dirpath)
        for fname in filenames:
            _apply_domain_owner(domain, os.path.join(dirpath, fname))


def _resolve_dest_domain(
    payload: TransferRequest, source_domain: Domain, db: Session, current_user: User
) -> Domain:
    """Devuelve el dominio destino, validando que el usuario pueda escribir en él.

    Mover entre dominios se permite solo cuando ambos son del MISMO propietario.
    Cada dominio corre bajo su propio usuario del sistema (pool PHP-FPM aislado,
    open_basedir propio), así que cruzar archivos entre dos cuentas distintas
    mezclaría datos de clientes que el aislamiento mantiene separados. El admin
    sí puede cruzar: es una operación legítima de administración (p.ej. mover un
    sitio de una cuenta a otra al reasignar un cliente).
    """
    if payload.dest_domain_id is None or payload.dest_domain_id == source_domain.id:
        return source_domain

    # _get_domain_or_404 ya filtra por rol: si el usuario no puede ver el
    # dominio destino, aquí recibe un 404 y no llega a escribir nada.
    dest_domain = _get_domain_or_404(payload.dest_domain_id, db, current_user)

    if current_user.role != "admin" and dest_domain.user_id != source_domain.user_id:
        raise HTTPException(
            status_code=403,
            detail="Solo se puede mover o copiar entre dominios del mismo propietario",
        )
    return dest_domain


def _prepare_transfer(
    payload: TransferRequest, source_domain: Domain, db: Session, current_user: User
):
    """Valida origen/destino comunes a mover y copiar.

    Devuelve (root_origen, dest_dir, dominio_destino). El destino puede estar en
    otro dominio, por eso dest_dir se resuelve contra la raíz de ESE dominio.
    """
    root = os.path.realpath(source_domain.public_html)
    dest_domain = _resolve_dest_domain(payload, source_domain, db, current_user)
    dest_root = os.path.realpath(dest_domain.public_html)
    dest_dir = _safe_join(dest_root, payload.dest)
    if not os.path.isdir(dest_dir):
        raise HTTPException(status_code=404, detail="La carpeta destino no existe")
    return root, dest_dir, dest_domain


@router.post("/file-manager/domains/{domain_id}/move", tags=["File Manager"])
def move_entries(
    domain_id: int,
    payload: TransferRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Mueve uno o varios elementos a otra carpeta, del mismo dominio o de otro
    dominio del mismo propietario."""
    _check_enabled()
    domain = _get_domain_or_404(domain_id, db, current_user)
    root, dest_dir, dest_domain = _prepare_transfer(payload, domain, db, current_user)
    dest_root = os.path.realpath(dest_domain.public_html)

    moved: list[str] = []
    errors: list[dict] = []

    for rel_path in payload.paths:
        name = os.path.basename(rel_path.rstrip("/"))
        try:
            source = _safe_join(root, rel_path)
            if not os.path.exists(source):
                raise HTTPException(status_code=404, detail="No encontrado")
            _assert_inside(root, source, "origen")
            if os.path.dirname(source) == dest_dir:
                raise HTTPException(status_code=400, detail="Ya está en esa carpeta")
            # Mover una carpeta dentro de sí misma destruiría el árbol.
            if os.path.isdir(source) and os.path.commonpath([source, dest_dir]) == source:
                raise HTTPException(status_code=400, detail="No se puede mover una carpeta dentro de sí misma")

            destination = os.path.join(dest_dir, name)
            if os.path.exists(destination):
                if not payload.overwrite:
                    raise HTTPException(status_code=409, detail="Ya existe en el destino")
                if os.path.isdir(destination):
                    shutil.rmtree(destination)
                else:
                    os.remove(destination)

            shutil.move(source, destination)
            # El chown va al dueño del DESTINO: si no, un archivo movido al
            # dominio B quedaría con el owner de A y el pool PHP-FPM de B no
            # podría escribirlo (y B tendría un archivo de otra cuenta dentro).
            _chown_tree(dest_domain, destination)
            moved.append(_relative_path(dest_root, destination))
        except HTTPException as exc:
            errors.append({"path": rel_path, "name": name, "error": exc.detail})

    return {"status": "success", "moved": moved, "errors": errors}


@router.post("/file-manager/domains/{domain_id}/copy", tags=["File Manager"])
def copy_entries(
    domain_id: int,
    payload: TransferRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Copia uno o varios elementos a otra carpeta, del mismo dominio o de otro
    dominio del mismo propietario.

    Si el destino ya existe y no se pidió sobreescribir, se crea "nombre (copia)"
    en vez de fallar: así se puede duplicar dentro de la misma carpeta.
    """
    _check_enabled()
    domain = _get_domain_or_404(domain_id, db, current_user)
    root, dest_dir, dest_domain = _prepare_transfer(payload, domain, db, current_user)
    dest_root = os.path.realpath(dest_domain.public_html)

    _, _, max_copy_mb = get_upload_limits(db)
    max_copy_bytes = max_copy_mb * 1024 * 1024

    copied: list[str] = []
    errors: list[dict] = []

    for rel_path in payload.paths:
        name = os.path.basename(rel_path.rstrip("/"))
        try:
            source = _safe_join(root, rel_path)
            if not os.path.exists(source):
                raise HTTPException(status_code=404, detail="No encontrado")
            _assert_inside(root, source, "origen")
            # Copiar una carpeta dentro de sí misma se realimenta sin fin.
            if os.path.isdir(source) and os.path.commonpath([source, dest_dir]) == source:
                raise HTTPException(status_code=400, detail="No se puede copiar una carpeta dentro de sí misma")

            if _tree_size(source) > max_copy_bytes:
                raise HTTPException(status_code=413, detail=f"Supera el límite de {max_copy_mb} MB")

            destination = os.path.join(dest_dir, name)
            if os.path.exists(destination):
                if payload.overwrite:
                    if os.path.isdir(destination):
                        shutil.rmtree(destination)
                    else:
                        os.remove(destination)
                else:
                    destination = _unique_destination(dest_dir, name)

            if os.path.isdir(source):
                shutil.copytree(source, destination, symlinks=True, ignore=_escaping_links_ignore(root))
            else:
                shutil.copy2(source, destination)
            # Igual que en move: el owner es el del dominio destino.
            _chown_tree(dest_domain, destination)
            copied.append(_relative_path(dest_root, destination))
        except HTTPException as exc:
            errors.append({"path": rel_path, "name": name, "error": exc.detail})
        except OSError as exc:
            errors.append({"path": rel_path, "name": name, "error": str(exc)})

    return {"status": "success", "copied": copied, "errors": errors}


@router.post("/file-manager/domains/{domain_id}/compress", tags=["File Manager"])
def compress_entries(
    domain_id: int,
    payload: CompressRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Comprime en un .zip uno o varios elementos del dominio."""
    _check_enabled()
    domain = _get_domain_or_404(domain_id, db, current_user)
    root = os.path.realpath(domain.public_html)
    dest_dir = _safe_join(root, payload.dest)
    if not os.path.isdir(dest_dir):
        raise HTTPException(status_code=404, detail="La carpeta destino no existe")

    name = _safe_child_name(payload.name)
    if not name.lower().endswith(".zip"):
        name += ".zip"
    zip_path = _safe_join(dest_dir, name)
    if os.path.exists(zip_path):
        raise HTTPException(status_code=409, detail=f"Ya existe un archivo llamado '{name}'")

    # Mismo tope que al extraer: evita llenar el disco del cliente de una tacada.
    _, _, max_zip_mb = get_upload_limits(db)
    max_zip_bytes = max_zip_mb * 1024 * 1024

    sources: list[str] = []
    for rel_path in payload.paths:
        source = _safe_join(root, rel_path)
        if not os.path.exists(source):
            raise HTTPException(status_code=404, detail=f"No encontrado: {rel_path}")
        _assert_inside(root, source, "elemento")
        sources.append(source)

    total = sum(_tree_size(src) for src in sources)
    if total > max_zip_bytes:
        raise HTTPException(status_code=413, detail=f"El contenido a comprimir supera el límite de {max_zip_mb} MB")

    added = 0
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for source in sources:
                base = os.path.basename(source)
                if os.path.isfile(source):
                    zf.write(source, base)
                    added += 1
                    continue
                for dirpath, dirnames, filenames in os.walk(source, followlinks=False):
                    # No descender por enlaces a carpetas que salgan del dominio.
                    dirnames[:] = [
                        d for d in dirnames
                        if os.path.commonpath([root, os.path.realpath(os.path.join(dirpath, d))]) == root
                    ]
                    for fname in filenames:
                        full = os.path.join(dirpath, fname)
                        # El propio ZIP vive dentro del árbol: no incluirlo en sí mismo.
                        if os.path.realpath(full) == zip_path:
                            continue
                        # zf.write() sigue los symlinks: un enlace a /etc/passwd
                        # metería su contenido real en un ZIP descargable.
                        if os.path.islink(full) and \
                                os.path.commonpath([root, os.path.realpath(full)]) != root:
                            continue
                        arcname = os.path.join(base, os.path.relpath(full, source))
                        zf.write(full, arcname)
                        added += 1
    except OSError as exc:
        if os.path.exists(zip_path):
            os.remove(zip_path)
        raise HTTPException(status_code=500, detail=f"Error creando el ZIP: {exc}")

    _apply_domain_owner(domain, zip_path)
    return {
        "status": "success",
        "path": _relative_path(root, zip_path),
        "name": name,
        "files_added": added,
    }


@router.post("/file-manager/domains/{domain_id}/chmod", tags=["File Manager"])
def chmod_entry(
    domain_id: int,
    payload: ChmodRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Cambia los permisos (chmod) de un archivo o carpeta dentro del dominio."""
    _check_enabled()
    domain = _get_domain_or_404(domain_id, db, current_user)
    target = _safe_join(domain.public_html, payload.path)
    if not os.path.exists(target):
        raise HTTPException(status_code=404, detail="Elemento no encontrado")
    mode_int = int(payload.mode, 8)
    os.chmod(target, mode_int)
    return {"status": "success", "path": payload.path, "mode": payload.mode}
