"""
Rutas de autenticación (login, logout, cambio de contraseña, 2FA)
"""

import os
import io
import base64
from datetime import datetime, timedelta, timezone

import pyotp
import qrcode
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from api.models.database import get_db
from api.models.models_user import User
from api.schemas.auth_schemas import (
    LoginRequest,
    LoginResponse,
    LoginWith2FAResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
    CurrentUserResponse,
    TwoFASetupResponse,
    TwoFAEnableRequest,
    TwoFADisableRequest,
    TwoFAVerifyRequest,
)
from api.dependencies import get_current_user, require_auth
from api.utils.auth_log import log_auth_failed
from api.utils.secret import get_secret_key

router = APIRouter()

# ── Clave para cifrar el secreto TOTP (misma que usa databases.py) ────────────
_ENCRYPTION_KEY = os.getenv("PANEL_ENCRYPTION_KEY", "")


def _get_fernet():
    """Devuelve Fernet si PANEL_ENCRYPTION_KEY está configurada."""
    if not _ENCRYPTION_KEY:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(_ENCRYPTION_KEY.encode())
    except Exception:
        return None


def _encrypt_secret(secret: str) -> str:
    f = _get_fernet()
    if f:
        return f.encrypt(secret.encode()).decode()
    return secret  # sin cifrar si no hay clave (aceptable en dev)


def _decrypt_secret(enc: str) -> str:
    f = _get_fernet()
    if f:
        try:
            return f.decrypt(enc.encode()).decode()
        except Exception:
            pass
    return enc


def _issue_temp_token(user_id: int, username: str) -> str:
    """Emite un JWT de 5 minutos con flag pending_2fa para el segundo paso del login."""
    secret_key = get_secret_key()
    payload = {
        "sub": str(user_id),
        "username": username,
        "pending_2fa": True,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    return jwt.encode(payload, secret_key, algorithm="HS256")


def _verify_temp_token(token: str) -> dict:
    """Verifica el token temporal. Lanza HTTPException si no es válido."""
    secret_key = get_secret_key()
    try:
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="El código de verificación ha caducado. Vuelve a iniciar sesión."
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido"
        )
    if not payload.get("pending_2fa"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token no es un token de verificación 2FA"
        )
    return payload


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post("/auth/login", tags=["Authentication"])
async def login(
    credentials: LoginRequest,
    request:     Request,
    db:          Session = Depends(get_db),
):
    """
    Login. Si el usuario tiene 2FA activo devuelve {requires_2fa, temp_token};
    en caso contrario devuelve el JWT completo.
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

    # Si 2FA está activo → segundo paso requerido
    if user.totp_enabled and user.totp_secret:
        temp_token = _issue_temp_token(user.id, user.username)
        return {"requires_2fa": True, "temp_token": temp_token}

    # Login normal sin 2FA
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

    user.set_password(payload.new_password)
    db.commit()

    return {
        "message": "Contraseña actualizada correctamente",
        "status": "success"
    }


# ── 2FA ───────────────────────────────────────────────────────────────────────

@router.get("/auth/2fa/setup", response_model=TwoFASetupResponse, tags=["2FA"])
async def setup_2fa(
    user: User    = Depends(require_auth),
    db:   Session = Depends(get_db),
):
    """
    Genera un nuevo secreto TOTP y devuelve el QR code en base64.
    El 2FA NO queda activado hasta que se llame a /auth/2fa/enable con un código válido.
    """
    if user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El doble factor ya está activado. Desactívalo primero."
        )

    # Generar secreto aleatorio en base32
    secret = pyotp.random_base32()

    # Guardar secreto cifrado (aún no activo)
    user.totp_secret  = _encrypt_secret(secret)
    user.totp_enabled = False
    db.commit()

    # Recuperar info del panel para el issuer
    panel_name  = os.getenv("PANEL_NAME", "SVQPanel")
    issuer      = panel_name
    account     = user.username

    # URI estándar otpauth://
    totp_obj = pyotp.TOTP(secret)
    uri = totp_obj.provisioning_uri(name=account, issuer_name=issuer)

    # Generar QR code PNG en base64
    qr_img = qrcode.make(uri)
    buf = io.BytesIO()
    qr_img.save(buf, format="PNG")
    qr_b64 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    return {
        "secret":       secret,
        "qr_code":      qr_b64,
        "issuer":       issuer,
        "account_name": account,
    }


@router.post("/auth/2fa/enable", tags=["2FA"])
async def enable_2fa(
    payload: TwoFAEnableRequest,
    user:    User    = Depends(require_auth),
    db:      Session = Depends(get_db),
):
    """
    Activa 2FA para el usuario tras verificar el primer código TOTP.
    Debe llamarse tras /auth/2fa/setup con un código generado por el autenticador.
    """
    if user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El doble factor ya está activado."
        )

    if not user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Primero debes llamar a /auth/2fa/setup para generar el secreto."
        )

    secret = _decrypt_secret(user.totp_secret)
    totp   = pyotp.TOTP(secret)

    if not totp.verify(payload.code, valid_window=1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Código incorrecto. Comprueba que la hora del dispositivo sea correcta."
        )

    user.totp_enabled    = True
    user.totp_enabled_at = datetime.utcnow()
    db.commit()

    return {"status": "success", "message": "Autenticación de doble factor activada correctamente."}


@router.post("/auth/2fa/disable", tags=["2FA"])
async def disable_2fa(
    payload: TwoFADisableRequest,
    user:    User    = Depends(require_auth),
    db:      Session = Depends(get_db),
):
    """
    Desactiva 2FA verificando el código TOTP actual.
    """
    if not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El doble factor no está activado."
        )

    secret = _decrypt_secret(user.totp_secret)
    totp   = pyotp.TOTP(secret)

    if not totp.verify(payload.code, valid_window=1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Código incorrecto."
        )

    user.totp_enabled    = False
    user.totp_secret     = None
    user.totp_enabled_at = None
    db.commit()

    return {"status": "success", "message": "Autenticación de doble factor desactivada."}


@router.post("/auth/2fa/verify", tags=["2FA"])
async def verify_2fa(
    payload: TwoFAVerifyRequest,
    request: Request,
    db:      Session = Depends(get_db),
):
    """
    Segundo paso del login: recibe el temp_token y el código TOTP.
    Si son correctos, devuelve el JWT completo.
    """
    token_data = _verify_temp_token(payload.temp_token)

    user = db.query(User).filter(User.id == int(token_data["sub"])).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o inactivo"
        )

    if not user.totp_enabled or not user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El usuario no tiene 2FA activo"
        )

    secret = _decrypt_secret(user.totp_secret)
    totp   = pyotp.TOTP(secret)

    if not totp.verify(payload.code, valid_window=1):
        # Registrar el fallo para que fail2ban (jail svqpanel-auth) banee la IP:
        # cierra la fuerza bruta del segundo factor (6 dígitos TOTP).
        log_auth_failed(request, user.username, "bad_2fa_code")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Código incorrecto o caducado"
        )

    # Emitir JWT completo
    token = user.generate_token()
    return {
        "access_token": token,
        "token_type":   "bearer",
        "user_id":      user.id,
        "username":     user.username,
        "email":        user.email,
        "role":         user.role,
        "is_admin":     user.is_admin,
    }


@router.get("/auth/2fa/status", tags=["2FA"])
async def get_2fa_status(user: User = Depends(require_auth)):
    """Devuelve si el usuario tiene 2FA activado."""
    return {
        "totp_enabled":    user.totp_enabled,
        "totp_enabled_at": user.totp_enabled_at.isoformat() if user.totp_enabled_at else None,
    }
