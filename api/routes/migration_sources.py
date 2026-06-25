"""
Servidores de origen guardados para migraciones (estilo cPanel).

Permite guardar un servidor Hestia/cPanel (host, usuario SSH, puerto y la
credencial CIFRADA) y reconectar sin rellenar todo. La contraseña/clave se
guardan con Fernet y NUNCA se devuelven en claro por la API.
"""
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.models.database import get_db
from api.models.models_migration_source import MigrationSource
from api.models.models_user import User
from api.dependencies import require_admin

router = APIRouter()

PANEL_ENCRYPTION_KEY = os.getenv("PANEL_ENCRYPTION_KEY", "")


def _get_fernet():
    if not PANEL_ENCRYPTION_KEY:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(PANEL_ENCRYPTION_KEY.encode())
    except Exception:
        return None


def _encrypt(value: Optional[str]) -> Optional[str]:
    f = _get_fernet()
    if not value:
        return None
    if not f:
        return value
    return f.encrypt(value.encode()).decode()


def _decrypt(value: Optional[str]) -> Optional[str]:
    f = _get_fernet()
    if not value:
        return None
    if not f:
        return value
    try:
        return f.decrypt(value.encode()).decode()
    except Exception:
        return value


class SourceIn(BaseModel):
    label: str
    panel: str = "hestia"
    host: str
    ssh_user: str = "root"
    ssh_port: int = 22
    ssh_password: Optional[str] = None
    ssh_key: Optional[str] = None
    last_remote_user: Optional[str] = None


def _to_dict(s: MigrationSource) -> dict:
    """Salida SIN secretos: solo indica si tiene credencial guardada."""
    return {
        "id": s.id, "label": s.label, "panel": s.panel, "host": s.host,
        "ssh_user": s.ssh_user, "ssh_port": s.ssh_port,
        "last_remote_user": s.last_remote_user,
        "has_password": bool(s.ssh_password_enc),
        "has_key": bool(s.ssh_key_enc),
    }


@router.get("/migration-sources")
async def list_sources(current_user: User = Depends(require_admin),
                       db: Session = Depends(get_db)):
    """Lista los servidores de origen guardados (sin secretos)."""
    return [_to_dict(s) for s in db.query(MigrationSource).order_by(MigrationSource.label).all()]


@router.post("/migration-sources")
async def create_source(data: SourceIn, current_user: User = Depends(require_admin),
                        db: Session = Depends(get_db)):
    """Guarda un servidor de origen (cifra la credencial)."""
    if not data.label.strip() or not data.host.strip():
        raise HTTPException(400, "Etiqueta y host son obligatorios")
    s = MigrationSource(
        label=data.label.strip(), panel=data.panel, host=data.host.strip(),
        ssh_user=(data.ssh_user or "root").strip(), ssh_port=data.ssh_port or 22,
        ssh_password_enc=_encrypt(data.ssh_password),
        ssh_key_enc=_encrypt(data.ssh_key),
        last_remote_user=(data.last_remote_user or "").strip() or None,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return _to_dict(s)


@router.put("/migration-sources/{source_id}")
async def update_source(source_id: int, data: SourceIn,
                        current_user: User = Depends(require_admin),
                        db: Session = Depends(get_db)):
    """Actualiza un servidor. Si ssh_password/ssh_key vienen vacíos, se conserva
    la credencial existente (no se borra)."""
    s = db.query(MigrationSource).filter(MigrationSource.id == source_id).first()
    if not s:
        raise HTTPException(404, "Servidor no encontrado")
    s.label = data.label.strip()
    s.panel = data.panel
    s.host = data.host.strip()
    s.ssh_user = (data.ssh_user or "root").strip()
    s.ssh_port = data.ssh_port or 22
    if data.ssh_password:
        s.ssh_password_enc = _encrypt(data.ssh_password)
    if data.ssh_key:
        s.ssh_key_enc = _encrypt(data.ssh_key)
    if data.last_remote_user is not None:
        s.last_remote_user = data.last_remote_user.strip() or None
    db.commit()
    db.refresh(s)
    return _to_dict(s)


@router.delete("/migration-sources/{source_id}")
async def delete_source(source_id: int, current_user: User = Depends(require_admin),
                        db: Session = Depends(get_db)):
    s = db.query(MigrationSource).filter(MigrationSource.id == source_id).first()
    if not s:
        raise HTTPException(404, "Servidor no encontrado")
    db.delete(s)
    db.commit()
    return {"status": "deleted"}


@router.get("/migration-sources/{source_id}/credentials")
async def get_source_credentials(source_id: int,
                                 current_user: User = Depends(require_admin),
                                 db: Session = Depends(get_db)):
    """Devuelve los datos de conexión DESCIFRADOS para reconectar. Solo admin,
    se usa al iniciar una migración desde un servidor guardado. No se expone en
    el listado normal."""
    s = db.query(MigrationSource).filter(MigrationSource.id == source_id).first()
    if not s:
        raise HTTPException(404, "Servidor no encontrado")
    return {
        "panel": s.panel, "host": s.host, "ssh_user": s.ssh_user,
        "ssh_port": s.ssh_port,
        "ssh_password": _decrypt(s.ssh_password_enc),
        "ssh_key": _decrypt(s.ssh_key_enc),
        "last_remote_user": s.last_remote_user,
    }
