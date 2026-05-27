"""
Rutas de autenticación (login, logout, cambio de contraseña)
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from api.models.database import get_db
from api.models.models_user import User
from api.schemas.auth_schemas import (
    LoginRequest,
    LoginResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
    CurrentUserResponse
)
from api.dependencies import get_current_user, require_auth
from api.utils.auth_log import log_auth_failed

router = APIRouter()


@router.post("/auth/login", response_model=LoginResponse, tags=["Authentication"])
async def login(
    credentials: LoginRequest,
    request:     Request,
    db:          Session = Depends(get_db),
):
    """
    Endpoint de login. Devuelve JWT token si las credenciales son correctas.
    Los intentos fallidos se loguean a /opt/svqpanel/logs/auth.log para que
    fail2ban (jail svqpanel-auth) pueda banear las IPs que hacen brute force.
    """
    user = db.query(User).filter(User.username == credentials.username).first()

    if not user:
        log_auth_failed(request, credentials.username, "unknown_user")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos"
        )

    if not user.check_password(credentials.password):
        log_auth_failed(request, credentials.username, "bad_password")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos"
        )

    if not user.is_active:
        log_auth_failed(request, credentials.username, "inactive_user")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario inactivo"
        )

    token = user.generate_token()

    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_admin": user.is_admin
    }


@router.get("/auth/me", response_model=CurrentUserResponse, tags=["Authentication"])
async def get_current_user_info(user: User = Depends(require_auth)):
    """
    Obtiene información del usuario actual autenticado.
    """
    return user


@router.post("/auth/logout", tags=["Authentication"])
async def logout(user: User = Depends(require_auth)):
    """
    Logout (el token se borra desde el cliente).
    Este endpoint simplemente confirma que el logout fue exitoso.
    """
    return {
        "status": "success",
        "message": f"Usuario {user.username} deslogueado correctamente"
    }


@router.post(
    "/auth/change-password",
    response_model=ChangePasswordResponse,
    tags=["Authentication"]
)
async def change_password(
    payload:      ChangePasswordRequest,
    http_request: Request,
    user:         User    = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """
    Cambia la contraseña del usuario actual.
    Requiere la contraseña actual para validación.
    """
    if not user.check_password(payload.current_password):
        log_auth_failed(http_request, user.username, "bad_current_password")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Contraseña actual incorrecta"
        )

    # Validación de nueva contraseña (ya hecha por Pydantic validator)
    user.set_password(payload.new_password)
    db.commit()

    return {
        "message": "Contraseña actualizada correctamente",
        "status": "success"
    }
