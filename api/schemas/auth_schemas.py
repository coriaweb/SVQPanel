"""
Esquemas Pydantic para autenticación
"""

from pydantic import BaseModel, EmailStr, field_validator
import re


class LoginRequest(BaseModel):
    """Request para login"""
    username: str
    password: str


class LoginResponse(BaseModel):
    """Response del login"""
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str
    email: str
    role: str
    is_admin: bool

    class Config:
        from_attributes = True


class ChangePasswordRequest(BaseModel):
    """Request para cambiar contraseña"""
    current_password: str
    new_password: str
    new_password_confirm: str

    @field_validator('new_password')
    @classmethod
    def validate_password_strength(cls, v):
        """Validar que la contraseña sea fuerte"""
        if len(v) < 8:
            raise ValueError("La contraseña debe tener al menos 8 caracteres")

        if not re.search(r'[A-Z]', v):
            raise ValueError("La contraseña debe contener al menos una mayúscula")

        if not re.search(r'[0-9]', v):
            raise ValueError("La contraseña debe contener al menos un número")

        return v

    @field_validator('new_password_confirm')
    @classmethod
    def passwords_match(cls, v, info):
        """Verificar que las contraseñas coincidan"""
        if 'new_password' in info.data:
            if v != info.data['new_password']:
                raise ValueError("Las contraseñas no coinciden")
        return v


class ChangePasswordResponse(BaseModel):
    """Response del cambio de contraseña"""
    message: str
    status: str


class CurrentUserResponse(BaseModel):
    """Response con datos del usuario actual"""
    id: int
    username: str
    email: str
    first_name: str | None
    last_name: str | None
    role: str
    is_admin: bool
    is_active: bool

    class Config:
        from_attributes = True
