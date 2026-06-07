"""
Modelo para trabajos de migración/importación (p. ej. backups de HestiaCP).

Un import puede tardar minutos (extraer tar, recrear dominios/BD/correo/DNS,
importar dumps y maildirs), así que se ejecuta en segundo plano y su estado se
persiste aquí para que el frontend pueda hacer polling y mostrar el informe.
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from datetime import datetime
from api.models.database import Base


class MigrationJob(Base):
    __tablename__ = "migration_jobs"

    id = Column(Integer, primary_key=True, index=True)
    # Origen del backup: upload | path | url | ssh
    source_type = Column(String(20), nullable=False, default="upload")
    source_kind = Column(String(20), nullable=False, default="hestia")  # hestia|vesta
    target_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"),
                            nullable=True, index=True)

    # pending | running | success | failed
    status = Column(String(20), nullable=False, default="pending", index=True)
    # Qué partes importar (csv): web,db,mail,dns
    scope = Column(String(60), nullable=False, default="web,db,mail,dns")

    manifest_json = Column(Text, nullable=True)   # manifiesto analizado (JSON)
    report_json = Column(Text, nullable=True)     # informe final (JSON)
    error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
