"""
Modelo para usuarios adicionales de bases de datos MariaDB.

Cada ClientDatabase tiene un usuario principal (db_user) y puede tener
N usuarios adicionales con permisos configurables por el cliente.
Este modelo representa esos usuarios adicionales.
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from api.models.database import Base


class DatabaseUser(Base):
    """
    Usuario adicional de MariaDB vinculado a una ClientDatabase.

    Convención de nombres:
      propietario "juan", suffix "analista"
        → username = "juan_analista"   (usuario real en MariaDB, máx 64 chars)
        → username_suffix = "analista" (parte que eligió el cliente)

    Permisos:
      - Se almacenan como JSON array: ["SELECT", "INSERT", ...]
      - El usuario principal (db_user de ClientDatabase) NO aparece aquí;
        este modelo es solo para los usuarios secundarios/adicionales.
    """
    __tablename__ = "database_users"

    id = Column(Integer, primary_key=True, index=True)

    # ── Vínculo con la BD ────────────────────────────────────────────────────
    database_id = Column(
        Integer,
        ForeignKey("client_databases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Nombres en MariaDB ───────────────────────────────────────────────────
    # username       = nombre completo real en MariaDB (ej: "juan_analista")
    # username_suffix = parte elegida por el cliente (ej: "analista")
    username        = Column(String(64), nullable=False)
    username_suffix = Column(String(48), nullable=False)

    # ── Permisos como JSON array ─────────────────────────────────────────────
    # Ej: '["SELECT","INSERT","UPDATE","DELETE"]'
    permissions = Column(
        Text,
        nullable=False,
        default='["SELECT","INSERT","UPDATE","DELETE"]',
    )

    # ── Contraseña ────────────────────────────────────────────────────────────
    # PBKDF2-SHA256 con salt  →  para verificación interna
    db_password_hash = Column(String(255), nullable=False)
    # Fernet (reversible)     →  para phpMyAdmin autologin (opcional)
    db_password_enc  = Column(String(500), nullable=True)

    # ── Estado ────────────────────────────────────────────────────────────────
    is_active = Column(Boolean, default=True, nullable=False)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # ── Relaciones ────────────────────────────────────────────────────────────
    database = relationship("ClientDatabase", back_populates="db_users")

    def __repr__(self):
        return (
            f"<DatabaseUser {self.username} "
            f"(database_id={self.database_id}, active={self.is_active})>"
        )
