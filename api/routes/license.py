"""
Rutas de licencia del panel.

- GET  /license/status   → estado actual (lee caché, no fuerza red). Para la UI.
- POST /license/activate → guarda la key, fuerza validación y persiste el estado.

La verificación criptográfica vive en scripts/license_client.py. Aquí solo se
expone a la UI y se persiste el estado en Settings (para mostrarlo rápido sin
llamar al servidor en cada carga).
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.models.database import get_db
from api.models.models_settings import Settings
from api.dependencies import require_admin, require_auth
from scripts import license_client

router = APIRouter()


def _persist(db: Session, result: dict) -> None:
    """Guarda el estado de licencia en Settings (para la UI sin red)."""
    s = db.query(Settings).filter(Settings.id == 1).first()
    if not s:
        s = Settings(id=1)
        db.add(s)
    s.license_valid = bool(result.get("valid"))
    s.license_plan = result.get("plan")
    s.license_reason = result.get("reason")
    exp = result.get("expires")
    if exp:
        try:
            s.license_expires = datetime.fromisoformat(exp.replace("Z", "+00:00"))
        except Exception:
            s.license_expires = None
    else:
        s.license_expires = None
    s.license_checked_at = datetime.utcnow()
    db.commit()


def _public(result: dict) -> dict:
    """Forma de respuesta para la UI."""
    return {
        "valid":       bool(result.get("valid")),
        "reason":      result.get("reason"),
        "plan":        result.get("plan"),
        "expires":     result.get("expires"),
        "fingerprint": result.get("fingerprint"),
    }


@router.get("/license/status")
async def license_status(
    refresh: bool = False,
    _: object = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Estado de la licencia. refresh=True fuerza una validación contra el
    servidor (admin lo usa tras activar); por defecto lee la caché."""
    result = license_client.validate(force=True) if refresh else license_client.status()
    try:
        _persist(db, result)
    except Exception:
        pass
    return _public(result)


class ActivateRequest(BaseModel):
    key: str


@router.post("/license/activate")
async def license_activate(
    payload: ActivateRequest,
    _: object = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Guarda la key, valida contra el servidor y persiste el estado."""
    key = (payload.key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="La clave de licencia no puede estar vacía")
    license_client.write_license_key(key)
    result = license_client.validate(force=True)
    _persist(db, result)
    if not result.get("valid"):
        # No es un error 500: devolvemos el motivo para que la UI lo muestre
        reason = result.get("reason")
        msg = {
            "fingerprint_mismatch": "Esta licencia ya está activada en otro servidor.",
            "expired":  "La licencia ha caducado.",
            "suspended": "La licencia está suspendida.",
            "not_found": "La clave de licencia no existe.",
            "offline":  "No se pudo contactar con el servidor de licencias.",
            "bad_signature": "Respuesta del servidor de licencias no válida.",
        }.get(reason, f"No se pudo activar la licencia ({reason}).")
        raise HTTPException(status_code=400, detail=msg)
    return _public(result)
