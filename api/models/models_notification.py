"""
Notification model — avisos dirigidos a un usuario del panel, mostrados como
campana/banner al iniciar sesión. Generados por procesos del sistema (ej:
cuota de disco/tráfico al 90% o 100%).

dedup_key: clave estable para no duplicar el mismo aviso en cada pasada del
timer. Ej: "quota_disk_90". Si ya existe una notificación NO leída con el
mismo (user_id, dedup_key), no se crea otra.
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime

from api.models.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id      = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    level   = Column(String(16), default="info")   # info, warning, danger
    title   = Column(String(128), nullable=False)
    message = Column(Text, nullable=False)

    # Clave para deduplicar avisos repetidos del mismo tipo
    dedup_key = Column(String(64), nullable=True, index=True)

    is_read    = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    read_at    = Column(DateTime, nullable=True)

    user = relationship("User", foreign_keys=[user_id])

    def __repr__(self):
        return f"<Notification u={self.user_id} {self.level}: {self.title}>"
