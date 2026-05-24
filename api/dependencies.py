"""
Dependencias y middleware de autenticación
"""

from fastapi import Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from api.models.database import get_db
from api.models.models_user import User
from typing import Optional


async def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> User:
    """
    Obtiene el usuario actual basado en el JWT token.
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
