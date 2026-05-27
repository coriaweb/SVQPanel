from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Enum, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta
from api.models.database import Base
import hashlib
import secrets
import jwt
import os
from enum import Enum as PyEnum

class UserRole(PyEnum):
    """Roles de usuario"""
    ADMIN = "admin"
    RESELLER = "reseller"
    USER = "user"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)

    # Información personal
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)

    # Sistema
    role = Column(String(50), default="user")  # admin, reseller, user
    is_admin = Column(Boolean, default=False)  # Para compatibilidad hacia atrás
    is_active = Column(Boolean, default=True)

    # Reseller: parent_id apunta al reseller propietario de este usuario
    # NULL = cuenta de nivel superior (admin o reseller directo del sistema)
    parent_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Plan asignado (snapshot pattern: los campos siguientes se copian al asignar)
    plan_id   = Column(Integer, ForeignKey("plans.id", ondelete="SET NULL"), nullable=True)
    plan_name = Column(String(64), nullable=True)

    # Límites (los rellena el plan o se editan manualmente; 0 = sin límite)
    domains_limit          = Column(Integer, default=10)
    databases_limit        = Column(Integer, default=5)
    mailboxes_limit        = Column(Integer, default=10)
    dns_zones_limit        = Column(Integer, default=10)
    disk_quota_mb          = Column(Integer, default=1024)
    traffic_quota_mb_month = Column(Integer, default=10240)

    # Stats (actualizadas por cron — Fase 13.2)
    disk_used_mb           = Column(Integer, default=0)
    traffic_used_mb_month  = Column(Integer, default=0)
    stats_updated_at       = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)

    # Shell access
    shell_path = Column(String(255), default="/bin/bash")
    home_dir = Column(String(255), nullable=True)  # /home/usuario

    # Relaciones
    domains      = relationship("Domain",         back_populates="user", cascade="all, delete-orphan")
    mail_domains = relationship("MailDomain",     back_populates="user", cascade="all, delete-orphan")
    databases    = relationship("ClientDatabase", back_populates="user", cascade="all, delete-orphan")
    # Nota: los clientes de un reseller se consultan por parent_id directamente en las rutas
    
    def set_password(self, password: str):
        """Hash y guarda la contraseña"""
        salt = secrets.token_hex(32)
        pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        self.password_hash = f"{salt}${pwd_hash.hex()}"
    
    def check_password(self, password: str) -> bool:
        """Verifica la contraseña"""
        try:
            salt, pwd_hash = self.password_hash.split('$')
            pwd_check = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
            return pwd_check.hex() == pwd_hash
        except:
            return False

    def generate_token(self, expires_hours: int = 24) -> str:
        """Genera JWT token válido por 24 horas"""
        secret = os.getenv("SECRET_KEY", "dev-secret-key-cambiar-en-produccion")
        payload = {
            "sub": str(self.id),
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "is_admin": self.is_admin,
            "exp": datetime.utcnow() + timedelta(hours=expires_hours)
        }
        return jwt.encode(payload, secret, algorithm="HS256")

    @staticmethod
    def verify_token(token: str) -> dict:
        """Verifica JWT token y devuelve payload"""
        secret = os.getenv("SECRET_KEY", "dev-secret-key-cambiar-en-produccion")
        try:
            payload = jwt.decode(token, secret, algorithms=["HS256"])
            return payload
        except jwt.ExpiredSignatureError:
            raise ValueError("Token expirado")
        except jwt.InvalidTokenError:
            raise ValueError("Token inválido")

    def can_manage_user(self, other_user: "User") -> bool:
        """Verifica si puede editar otro usuario"""
        if self.role == "admin":
            return True
        if self.role == "reseller":
            # Reseller solo puede gestionar sus propios clientes (parent_id = self.id)
            return other_user.parent_id == self.id
        if self.id == other_user.id:
            return True
        return False

    def can_manage_domain(self, domain: "Domain") -> bool:
        """Verifica si puede editar un dominio"""
        from api.models.models_domain import Domain
        if self.role == "admin":
            return True
        if self.role == "reseller" and domain.user.role == "user":
            # Reseller puede editar dominios de sus usuarios
            return domain.user_id == self.id or domain.user.id in [u.id for u in self.users]
        if self.role == "user":
            # Usuario solo puede editar sus propios dominios
            return domain.user_id == self.id
        return False

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"
