"""
Modelo de API tokens (acceso programático a la API del panel).

Permite a admin / revendedores / usuarios finales automatizar contra la API sin
usar el JWT del login (que caduca a las 24h y choca con el 2FA). El token:

  - Hereda el rol y el alcance del usuario que lo creó (no escala privilegios):
    entra por el mismo `get_current_user` y devuelve el `User` dueño, así que los
    `require_admin/_or_reseller/_auth` existentes lo limitan automáticamente.
  - Se MUESTRA en claro una sola vez al crearlo; en BD solo se guarda el HASH
    (mismo pbkdf2-sha256 que las contraseñas en models_user.py).
  - Caducidad opcional (`expires_at`), revocable (`is_revoked`).
  - Allowlist de IPs opcional (`allowed_ips`): solo esas IPs pueden usar el token.

El secreto en claro tiene el prefijo `svq_` para distinguirlo de un JWT (que
empieza por `eyJ`) en la capa de autenticación, sin colisión posible.
"""

import hashlib
import secrets
from datetime import datetime

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship

from api.models.database import Base

# Prefijo del secreto en claro. Un JWT nunca empieza así (empieza por "eyJ").
TOKEN_PREFIX = "svq_"


class ApiToken(Base):
    """Token de API de un usuario. Solo se guarda el hash del secreto."""
    __tablename__ = "api_tokens"

    id = Column(Integer, primary_key=True, index=True)

    # Dueño: de aquí salen el rol y el alcance del token.
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name        = Column(String(64), nullable=False)          # etiqueta del usuario
    token_hash  = Column(String(255), nullable=False, unique=True, index=True)
    prefix      = Column(String(16), nullable=False)          # "svq_ab12" para mostrar

    # CSV de IPv4 autorizadas. NULL/"" = sin restricción de IP.
    allowed_ips = Column(Text, nullable=True)

    expires_at   = Column(DateTime, nullable=True)            # NULL = no caduca
    last_used_at = Column(DateTime, nullable=True)
    is_revoked   = Column(Boolean, default=False, nullable=False)
    created_at   = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")

    # ── Generación / hashing ──────────────────────────────────────────────────
    @staticmethod
    def hash_token(secret: str) -> str:
        """Hash determinista del secreto (pbkdf2-sha256 con salt fijo derivado).

        A diferencia de las contraseñas, el token debe poder BUSCARSE por hash en
        la BD (no tenemos el id antes de autenticar), así que el hash es
        determinista: salt fijo derivado del propio secreto del panel no aporta
        aquí; usamos un salt constante de aplicación. La entropía la da el propio
        token (token_urlsafe(32) = 256 bits), que es lo que protege.
        """
        return hashlib.pbkdf2_hmac(
            "sha256", secret.encode(), b"svqpanel-api-token", 100000
        ).hex()

    @classmethod
    def generate(cls):
        """Genera un nuevo secreto. Devuelve (secreto_en_claro, token_hash, prefix).

        El secreto en claro solo se devuelve aquí; el panel lo muestra una vez y
        nunca más. En BD se persiste el hash y el prefix (para identificarlo).
        """
        secret = TOKEN_PREFIX + secrets.token_urlsafe(32)
        return secret, cls.hash_token(secret), secret[:12]

    def matches(self, secret: str) -> bool:
        """True si el secreto en claro corresponde a este token."""
        return secrets.compare_digest(self.token_hash, self.hash_token(secret))

    # ── Validez ───────────────────────────────────────────────────────────────
    def is_expired(self) -> bool:
        return self.expires_at is not None and datetime.utcnow() >= self.expires_at

    def is_valid(self) -> bool:
        return (not self.is_revoked) and (not self.is_expired())

    def ip_allowed(self, ip: str) -> bool:
        """True si la IP puede usar el token. Sin allowlist → cualquier IP."""
        if not self.allowed_ips:
            return True
        allowed = {p.strip() for p in self.allowed_ips.split(",") if p.strip()}
        return ip in allowed if allowed else True
