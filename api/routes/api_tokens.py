"""
Rutas de gestión de API tokens (acceso programático a la API del panel).

Un API token hereda el rol y el alcance del usuario que lo crea (ver
api/dependencies.py). Aquí solo se gestiona su ciclo de vida: crear (devuelve el
secreto en claro UNA vez), listar (sin el secreto) y revocar.

Permisos: cada usuario gestiona SOLO sus tokens; un admin puede gestionar los de
cualquiera (mismo patrón de propiedad que el resto del panel).
"""

import ipaddress
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.models.database import get_db
from api.models.models_user import User
from api.models.models_api_token import ApiToken
from api.dependencies import require_auth

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────
class ApiTokenCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    expires_at: Optional[datetime] = None
    allowed_ips: Optional[List[str]] = None  # IPv4; vacío/None = sin restricción


class ApiTokenResponse(BaseModel):
    id: int
    name: str
    prefix: str
    allowed_ips: Optional[List[str]] = None
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    is_revoked: bool
    is_expired: bool
    created_at: Optional[datetime] = None
    username: Optional[str] = None  # para la vista admin


class ApiTokenCreated(ApiTokenResponse):
    secret: str  # el secreto en claro — se muestra UNA sola vez


# ── Helpers ───────────────────────────────────────────────────────────────────
def _validate_ip(ip: str) -> str:
    """Valida una IP de la allowlist. Rechaza comodines/rangos peligrosos —misma
    política que el acceso remoto a MySQL (api/routes/databases.py)."""
    ip = (ip or "").strip()
    if ip in ("%", "*", "", "0.0.0.0", "0.0.0.0/0", "::/0"):
        raise HTTPException(
            status_code=400,
            detail="No se permite autorizar TODAS las IPs. Indica una IP concreta.",
        )
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"IP no válida: {ip}")
    if addr.version != 4:
        raise HTTPException(status_code=400, detail="Solo se admiten IPv4 por ahora.")
    return str(addr)


def _to_response(token: ApiToken, owner: Optional[User] = None) -> dict:
    ips = [p.strip() for p in token.allowed_ips.split(",")] if token.allowed_ips else None
    return {
        "id": token.id,
        "name": token.name,
        "prefix": token.prefix,
        "allowed_ips": ips,
        "expires_at": token.expires_at,
        "last_used_at": token.last_used_at,
        "is_revoked": token.is_revoked,
        "is_expired": token.is_expired(),
        "created_at": token.created_at,
        "username": owner.username if owner else None,
    }


def _get_token_or_404(token_id: int, db: Session) -> ApiToken:
    token = db.query(ApiToken).filter(ApiToken.id == token_id).first()
    if not token:
        raise HTTPException(status_code=404, detail="Token no encontrado")
    return token


def _check_access(current: User, token: ApiToken):
    if not current.is_admin and token.user_id != current.id:
        raise HTTPException(status_code=403, detail="No tienes permiso sobre este token")


# ── Endpoints ─────────────────────────────────────────────────────────────────
@router.get("/tokens", response_model=List[ApiTokenResponse], tags=["API Tokens"])
async def list_tokens(
    user_id: Optional[int] = None,
    current: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Lista los API tokens. Un usuario ve los suyos; un admin puede filtrar por
    `?user_id=` para ver los de otro (o todos si no lo indica)."""
    q = db.query(ApiToken)
    if current.is_admin:
        if user_id is not None:
            q = q.filter(ApiToken.user_id == user_id)
    else:
        q = q.filter(ApiToken.user_id == current.id)

    tokens = q.order_by(ApiToken.created_at.desc()).all()
    owners = {u.id: u for u in db.query(User).all()} if current.is_admin else {current.id: current}
    return [_to_response(t, owners.get(t.user_id)) for t in tokens]


@router.post("/tokens", response_model=ApiTokenCreated, status_code=201, tags=["API Tokens"])
async def create_token(
    payload: ApiTokenCreate,
    current: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Crea un API token para el usuario actual. Devuelve el secreto en claro UNA
    sola vez — el panel no lo vuelve a mostrar (en BD solo se guarda el hash)."""
    # Validar/normalizar las IPs de la allowlist (si las hay)
    allowed_csv = None
    if payload.allowed_ips:
        ips = [_validate_ip(ip) for ip in payload.allowed_ips]
        allowed_csv = ",".join(ips)

    # Caducidad: si se indica, debe ser futura
    if payload.expires_at is not None:
        exp = payload.expires_at.replace(tzinfo=None)
        if exp <= datetime.utcnow():
            raise HTTPException(status_code=400, detail="La fecha de caducidad debe ser futura.")
    else:
        exp = None

    secret, token_hash, prefix = ApiToken.generate()
    token = ApiToken(
        user_id=current.id,
        name=payload.name.strip(),
        token_hash=token_hash,
        prefix=prefix,
        allowed_ips=allowed_csv,
        expires_at=exp,
    )
    db.add(token)
    db.commit()
    db.refresh(token)

    data = _to_response(token, current)
    data["secret"] = secret  # única vez
    return data


@router.delete("/tokens/{token_id}", tags=["API Tokens"])
async def revoke_token(
    token_id: int,
    current: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Revoca (desactiva) un token. Irreversible: hay que crear uno nuevo."""
    token = _get_token_or_404(token_id, db)
    _check_access(current, token)
    token.is_revoked = True
    db.commit()
    return {"status": "success", "message": "Token revocado correctamente"}
