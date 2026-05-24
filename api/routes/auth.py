"""
Rutas de autenticación (login, logout, cambio de contraseña)
"""

from fastapi import APIRouter, Depends, HTTPException, status
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

router = APIRouter()


@router.post("/auth/login", response_model=LoginResponse, tags=["Authentication"])
async def login(credentials: LoginRequest, db: Session = Depends(get_db)):
    """
    Endpoint de login. Devuelve JWT token si las credenciales son correctas.
    """
    user = db.query(User).filter(User.username == credentials.username).first()

    if not user or not user.check_password(credentials.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos"
        )

    if not user.is_active:
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
    request: ChangePasswordRequest,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """
    Cambia la contraseña del usuario actual.
    Requiere la contraseña actual para validación.
    """
    if not user.check_password(request.current_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Contraseña actual incorrecta"
        )

    # Validación de nueva contraseña (ya hecha por Pydantic validator)
    user.set_password(request.new_password)
    db.commit()

    return {
        "message": "Contraseña actualizada correctamente",
        "status": "success"
    }
