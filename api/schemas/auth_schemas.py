"""
Esquemas Pydantic para autenticación
"""

from pydantic import BaseModel, EmailStr, field_validator
import re


class LoginRequest(BaseModel):
    """Request para login"""
    username: str
    password: str


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


# ── 2FA ────────────────────────────────────────────────────────────────────────

class TwoFASetupResponse(BaseModel):
    """Response del setup inicial de 2FA: devuelve el QR y el secret"""
    secret: str
    qr_code: str          # imagen PNG en base64 (data:image/png;base64,...)
    issuer: str
    account_name: str


class TwoFAEnableRequest(BaseModel):
    """Request para confirmar y activar 2FA (verificar primer código)"""
    code: str             # código de 6 dígitos del autenticador


class TwoFADisableRequest(BaseModel):
    """Request para desactivar 2FA (requiere código vigente)"""
    code: str


class TwoFAVerifyRequest(BaseModel):
    """Request para el segundo paso del login cuando 2FA está activo"""
    temp_token: str       # token temporal emitido tras usuario/contraseña correctos
    code: str             # código TOTP de 6 dígitos


class LoginResponse(BaseModel):
    """Response del login normal (sin 2FA pendiente)"""
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str
    email: str
    role: str
    is_admin: bool

    class Config:
        from_attributes = True


class LoginWith2FAResponse(BaseModel):
    """Response del login cuando el usuario tiene 2FA activado"""
    requires_2fa: bool = True
    temp_token: str       # token de corta duración (5 min) solo para /auth/2fa/verify
