"""
Historial de ejecuciones de cronjobs.

Cada vez que un cron se ejecuta (por el daemon del sistema vía el wrapper
svq-cron-run, o a mano desde "Ejecutar ahora"), se registra una fila aquí:
inicio, fin, duración, código de salida y salida (cap). Se conservan solo las
últimas N por cron (poda automática) para no llenar la BD.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship, backref
from api.models.database import Base


class CronRun(Base):
    __tablename__ = "cron_runs"

    id          = Column(Integer, primary_key=True, index=True)
    cron_id     = Column(Integer, ForeignKey("cron_jobs.id", ondelete="CASCADE"),
                         nullable=False, index=True)

    started_at  = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)     # milisegundos
    exit_code   = Column(Integer, nullable=True)     # 0 = ok
    output      = Column(Text, nullable=True)        # stdout+stderr, cap ~8 KB
    trigger     = Column(String(10), default="auto", nullable=False)  # auto | manual

    cron = relationship("CronJob",
                        backref=backref("runs", cascade="all, delete-orphan",
                                        passive_deletes=True),
                        lazy="select")
