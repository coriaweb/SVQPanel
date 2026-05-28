"""
Modelo SQLAlchemy para trabajos cron de clientes.
Cada cron pertenece a un usuario y opcionalmente a un dominio.
El comando se ejecutará con el usuario del sistema propietario del dominio.
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey
)
from sqlalchemy.orm import relationship
from api.models.database import Base


class CronJob(Base):
    __tablename__ = "cron_jobs"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    domain_id  = Column(Integer, ForeignKey("domains.id", ondelete="SET NULL"), nullable=True)

    # Campos de tiempo cron
    minute     = Column(String(20), default="*", nullable=False)
    hour       = Column(String(20), default="*", nullable=False)
    day        = Column(String(20), default="*", nullable=False)
    month      = Column(String(20), default="*", nullable=False)
    weekday    = Column(String(20), default="*", nullable=False)

    command    = Column(Text, nullable=False)
    comment    = Column(String(255), nullable=True)   # descripción/etiqueta del cron

    is_active  = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_run   = Column(DateTime, nullable=True)

    # Relaciones (lazy para no cargar innecesariamente)
    user   = relationship("User",   back_populates="cron_jobs", lazy="select")
    domain = relationship("Domain", back_populates="cron_jobs", lazy="select")
