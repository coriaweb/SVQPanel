"""
Dependencias y middleware de autenticación
"""

from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status, Header, Request
from sqlalchemy.orm import Session
from api.models.database import get_db
from api.models.models_user import User
from api.models.models_api_token import ApiToken, TOKEN_PREFIX
from api.utils.auth_log import client_ip
from typing import Optional

# No escribir last_used_at en cada request: como mucho una vez cada N minutos.
_LAST_USED_THROTTLE = timedelta(minutes=5)


def _authenticate_api_token(token: str, request: Optional[Request], db: Session) -> User:
    """Resuelve un API token (`svq_…`) a su usuario dueño.

    Comprueba: existe, no revocado, no caducado, y (si tiene allowlist) la IP del
    request está autorizada. Devuelve el `User` dueño — de ahí salen el rol y el
    alcance, así que los require_admin/_or_reseller/_auth lo limitan igual que a
    un login normal. Salta el 2FA a propósito (es para automatización).
    """
    token_hash = ApiToken.hash_token(token)
    api_token = db.query(ApiToken).filter(ApiToken.token_hash == token_hash).first()

    if not api_token or not api_token.is_valid():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de API inválido, revocado o caducado",
        )

    # Allowlist de IPs (si la hay): solo esas IPs pueden usar el token.
    if api_token.allowed_ips:
        ip = client_ip(request) or ""
        if not api_token.ip_allowed(ip):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Esta IP no está autorizada para usar este token de API",
            )

    user = db.query(User).filter(User.id == api_token.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o inactivo",
        )

    # last_used_at (throttled): no escribir en BD en cada petición.
    now = datetime.utcnow()
    if api_token.last_used_at is None or (now - api_token.last_used_at) > _LAST_USED_THROTTLE:
        api_token.last_used_at = now
        db.commit()

    return user


async def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> User:
    """
    Obtiene el usuario actual a partir del header Authorization: Bearer <token>.
    El token puede ser:
      - un JWT del login (ruta histórica), o
      - un API token (empieza por `svq_`): hereda el rol/alcance de su dueño.
    Lanza 401 si el token es inválido o no existe.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No hay token de autenticación"
        )

    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise ValueError()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Formato de token inválido. Usar: Bearer {token}"
        )

    # API token (svq_…) → ruta de API tokens. Si no, ruta JWT de siempre.
    if token.startswith(TOKEN_PREFIX):
        return _authenticate_api_token(token, request, db)

    try:
        payload = User.verify_token(token)
        user_id = int(payload.get("sub"))
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o inactivo"
        )

    return user


async def require_admin(
    user: User = Depends(get_current_user)
) -> User:
    """Requiere que el usuario sea administrador"""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requieren permisos de administrador"
        )
    return user


async def require_admin_or_reseller(
    user: User = Depends(get_current_user)
) -> User:
    """Requiere que el usuario sea admin o reseller"""
    if user.role not in ["admin", "reseller"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requieren permisos de administrador o reseller"
        )
    return user


async def require_auth(
    user: User = Depends(get_current_user)
) -> User:
    """Requiere que el usuario esté autenticado"""
    return user


def _enforcement_mode() -> str:
    """warn | restrict. Controla qué pasa sin licencia válida.
    En beta arranca en 'restrict' (operaciones bloqueadas, pero login/ver/activar
    siguen funcionando). Override por env SVQ_LICENSE_ENFORCEMENT."""
    import os
    return os.getenv("SVQ_LICENSE_ENFORCEMENT", "restrict").strip().lower()


async def require_license(
    user: User = Depends(get_current_user)
) -> User:
    """Requiere que el panel tenga una licencia válida para EJECUTAR la acción.
    Se pone en las rutas de creación/modificación (crear dominios, cuentas, BD…),
    NO en login/ver/activar licencia. En modo 'warn' no bloquea (solo la beta
    podría aflojarlo). Lee el estado cacheado (sin llamada de red por petición)."""
    if _enforcement_mode() == "warn":
        return user
    try:
        from scripts import license_client
        st = license_client.status()
        if not st.get("valid"):
            # Revalida una vez por si la caché está stale (no en cada request)
            st = license_client.validate()
    except Exception:
        # Si el módulo falla, no bloqueamos el panel (fail-open ante errores propios)
        return user
    if not st.get("valid"):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=("Licencia del panel no válida o caducada. Actívala en "
                    "Ajustes → Licencia (o en tu área de cliente de SVQHost)."),
        )
    return user
