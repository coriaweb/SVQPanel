"""
Modelo para bases de datos MariaDB de clientes.

Arquitectura de doble BD:
  - PostgreSQL (interno): gestiona metadata del panel (este modelo)
  - MariaDB (clientes): motor MySQL real donde se crean las BDs
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from api.models.database import Base


class ClientDatabase(Base):
    """
    Metadata de una base de datos MariaDB perteneciente a un cliente.

    Convención de nombres (igual que cPanel):
      username "juan", sufijo "wordpress"
        → db_name  = "juan_wordpress"   (real en MariaDB, máx 64 chars)
        → db_user  = "juan_wordpress"   (usuario MariaDB, máx 32 chars)

    El panel almacena aquí la metadata; la BD real vive en MariaDB.
    """
    __tablename__ = "client_databases"

    id = Column(Integer, primary_key=True, index=True)

    # ── Propietario ──────────────────────────────────────────────────────────
    user_id   = Column(Integer, ForeignKey("users.id",   ondelete="CASCADE"),  nullable=False, index=True)
    domain_id = Column(Integer, ForeignKey("domains.id", ondelete="SET NULL"), nullable=True,  index=True)

    # ── Nombres en MariaDB ────────────────────────────────────────────────────
    # db_name  = nombre real de la BD en MariaDB  (ej: "juan_wordpress")
    # db_user  = usuario real en MariaDB           (ej: "juan_wordpress")
    # *_suffix = parte que eligió el usuario       (ej: "wordpress")
    db_name        = Column(String(64),  unique=True, nullable=False, index=True)
    db_name_suffix = Column(String(48),  nullable=False)
    db_user        = Column(String(64),  unique=True, nullable=False)
    db_user_suffix = Column(String(48),  nullable=False)

    # Hash de la contraseña (PBKDF2-SHA256); no reversible → reset si se olvida
    db_password_hash = Column(String(255), nullable=False)

    # Contraseña cifrada con Fernet (simétrico, reversible) — para phpMyAdmin autologin
    # Se rellena si PANEL_ENCRYPTION_KEY está configurada en .env
    db_password_enc  = Column(String(500), nullable=True)

    # ── Configuración MariaDB ─────────────────────────────────────────────────
    db_charset   = Column(String(20),  default="utf8mb4")
    db_collation = Column(String(50),  default="utf8mb4_unicode_ci")  # 'collation' es palabra clave en PostgreSQL
    quota_mb     = Column(Integer,     default=1024)   # 0 = sin límite

    # ── Estadísticas (se puede actualizar con un cron/tarea) ─────────────────
    size_mb = Column(Integer, default=0)

    # ── Estado ────────────────────────────────────────────────────────────────
    is_active = Column(Boolean, default=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ── Relaciones ────────────────────────────────────────────────────────────
    user   = relationship("User",   back_populates="databases")
    domain = relationship("Domain", back_populates="databases")
    db_users = relationship(
        "DatabaseUser",
        back_populates="database",
        cascade="all, delete-orphan",
    )
    remote_hosts = relationship(
        "DbRemoteHost",
        back_populates="database",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<ClientDatabase {self.db_name} (user_id={self.user_id})>"


class DbRemoteHost(Base):
    """IP autorizada a conectar remotamente a una base de datos de cliente.

    Cada IP genera un usuario MySQL '{db_user}'@'{ip}' (mismo hash que
    @localhost) y se añade al set nftables que abre el 3306 solo para ella.
    Nunca se permite '%' ni '0.0.0.0/0' (eso lo valida la API).
    """
    __tablename__ = "db_remote_hosts"

    id          = Column(Integer, primary_key=True, index=True)
    database_id = Column(Integer, ForeignKey("client_databases.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    ip          = Column(String(45), nullable=False)   # IPv4 (o IPv6 a futuro)
    created_at  = Column(DateTime, default=datetime.utcnow)

    database = relationship("ClientDatabase", back_populates="remote_hosts")

    def __repr__(self):
        return f"<DbRemoteHost db={self.database_id} ip={self.ip}>"
