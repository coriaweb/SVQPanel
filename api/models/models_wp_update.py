"""
Historial de actualizaciones seguras de WordPress (wp_safe_update).

Cada ejecución (manual o del pase automático nocturno) deja una fila con qué
había pendiente, las sondas de salud antes/después (JSON), si hubo rollback y
el log resumido. Es el estado persistente del job (el dict en memoria de
wp_safe_update solo sirve para el polling de la UI mientras corre).
"""

from datetime import datetime

from sqlalchemy import (Boolean, Column, DateTime, ForeignKey, Integer,
                        String, Text)

from api.models.database import Base


class WpUpdateRun(Base):
    __tablename__ = "wp_update_runs"

    id        = Column(Integer, primary_key=True, index=True)
    domain_id = Column(Integer, ForeignKey("domains.id", ondelete="CASCADE"),
                       nullable=False, index=True)

    mode   = Column(String(10), nullable=False, default="manual")  # manual|auto
    status = Column(String(16), nullable=False, default="running")
    # running | success | rolled_back | failed

    # Qué había pendiente al empezar: {"core": "6.6.2"|None, "plugins": [...], "themes": [...]}
    updated_items = Column(Text, nullable=True)   # JSON
    pre_health    = Column(Text, nullable=True)   # JSON {wp_ok, http_status, ...}
    post_health   = Column(Text, nullable=True)   # JSON

    rollback        = Column(Boolean, nullable=False, default=False)
    checkpoint_path = Column(String(512), nullable=True)
    error           = Column(Text, nullable=True)
    log             = Column(Text, nullable=True)

    started_at  = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<WpUpdateRun {self.id} domain={self.domain_id} {self.status}>"
