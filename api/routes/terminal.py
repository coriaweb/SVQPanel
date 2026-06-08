"""
Terminal web (consola SSH en el navegador) — rutas.

  GET  /terminal/status              estado (instalado/activo) — admin
  POST /terminal/install             instala/arranca ttyd — admin
  POST /terminal/uninstall           para ttyd — admin
  POST /terminal/session             emite un token de un solo uso para abrir
                                     una sesión. Admin → root o un usuario;
                                     usuario normal → solo su propia cuenta.

La seguridad real está en scripts/terminal_manager: ttyd corre en localhost tras
nginx, y el token de un solo uso (caduca en 30 s) decide la shell. Sin token
válido no hay shell.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from api.models.database import get_db
from api.models.models_user import User
from api.dependencies import require_auth, require_admin
from scripts import terminal_manager as tm

router = APIRouter()


@router.get("/terminal/status")
async def terminal_status(current_user: User = Depends(require_admin)):
    """Estado del terminal web (solo admin gestiona la instalación)."""
    return tm.status()


@router.post("/terminal/install")
async def terminal_install(current_user: User = Depends(require_admin)):
    try:
        return tm.install()
    except Exception as e:
        raise HTTPException(status_code=500,
                            detail=f"Error instalando el terminal web: {e}")


@router.post("/terminal/uninstall")
async def terminal_uninstall(current_user: User = Depends(require_admin)):
    try:
        return tm.uninstall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class SessionRequest(BaseModel):
    # Solo lo usa el admin: a quién abrir la sesión.
    #   "root"        → shell root del servidor
    #   "<username>"  → sesión jailed como ese usuario del sistema
    target: Optional[str] = None


@router.post("/terminal/session")
async def terminal_session(payload: SessionRequest,
                           current_user: User = Depends(require_auth),
                           db: Session = Depends(get_db)):
    """Emite un token de un solo uso para abrir la terminal.

    - Admin: puede pedir 'root' (por defecto) o cualquier usuario existente.
    - Usuario normal: SIEMPRE su propia cuenta del sistema (ignora `target`).
    """
    if not tm.ttyd_active():
        raise HTTPException(status_code=422, detail=(
            "El terminal web no está activo. Un administrador debe instalarlo "
            "desde Administración → Sistema."))

    if current_user.is_admin:
        target = (payload.target or "root").strip()
        if target != "root":
            # Validar que el usuario solicitado existe en el panel
            u = db.query(User).filter(User.username == target).first()
            if not u:
                raise HTTPException(status_code=404,
                                    detail="Usuario no encontrado")
    else:
        # Un usuario normal solo puede abrir SU propia terminal jailed
        target = current_user.username

    token = tm.issue_token(target)
    return {
        "token": token,
        "target": target,
        # La UI abre /terminal/ (proxy a ttyd) y envía el token al prompt.
        "url": "/terminal/",
        "ttl_seconds": tm.TOKEN_TTL_SECONDS,
    }
