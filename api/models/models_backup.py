"""
Modelos SQLAlchemy para el sistema de backups.

Arquitectura:
  - BackupJob   → configuración de un backup (qué, cuándo, dónde)
  - BackupRecord → historial de ejecuciones de un job

Destinos soportados:
  - local : /backups/{username}/{dominio}/{timestamp}/
  - sftp  : rsync sobre SSH a servidor remoto

Contenido seleccionable:
  - include_files     → archivos web del dominio (/home/user/public_html/dominio)
  - include_databases → dumps MariaDB asociadas al dominio
  - include_mail      → buzones de correo del dominio (/var/mail/vhosts/dominio)
"""

from datetime import datetime
from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from api.models.database import Base


class BackupJob(Base):
    """Configuración de un backup (job)."""

    __tablename__ = "backup_jobs"

    id      = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Dominio al que aplica (NULL = backup global, solo admin)
    domain_id = Column(Integer, ForeignKey("domains.id", ondelete="SET NULL"), nullable=True, index=True)

    # Nombre descriptivo del job
    name        = Column(String(100), nullable=False)
    description = Column(String(255), nullable=True)

    # ── Contenido a respaldar ─────────────────────────────────────────────────
    include_files     = Column(Boolean, default=True,  nullable=False)
    include_databases = Column(Boolean, default=True,  nullable=False)
    include_mail      = Column(Boolean, default=False, nullable=False)

    # ── Tipo de copia ─────────────────────────────────────────────────────────
    # full        → copia completa siempre
    # incremental → rsync con --link-dest al snapshot anterior (hardlinks)
    backup_type = Column(String(20), default="incremental", nullable=False)

    # ── Destino ───────────────────────────────────────────────────────────────
    # local : copia en /backups/ del servidor
    # sftp  : rsync sobre SSH a host remoto
    # s3    : subida a almacenamiento compatible S3 (AWS S3, Backblaze B2, Wasabi, MinIO…)
    destination_type = Column(String(10), default="local", nullable=False)

    # Destino local
    local_path = Column(String(512), default="/backups", nullable=False)

    # Destino SFTP/SSH remoto
    sftp_host     = Column(String(255), nullable=True)
    sftp_port     = Column(Integer,     default=22)
    sftp_user     = Column(String(64),  nullable=True)
    sftp_password = Column(String(500), nullable=True)   # cifrado con Fernet si está disponible
    sftp_path     = Column(String(512), nullable=True)
    sftp_key_path = Column(String(512), nullable=True)   # ruta a clave SSH privada en el servidor

    # Destino S3 / compatible (AWS S3, Backblaze B2, Wasabi, MinIO…)
    s3_endpoint   = Column(String(255), nullable=True)   # vacío = AWS; B2: s3.us-west-002.backblazeb2.com
    s3_region     = Column(String(64),  nullable=True)
    s3_bucket     = Column(String(255), nullable=True)
    s3_prefix     = Column(String(512), nullable=True)   # carpeta dentro del bucket
    s3_access_key = Column(String(255), nullable=True)
    s3_secret_key = Column(String(500), nullable=True)   # cifrado con Fernet si está disponible

    # ── Retención ─────────────────────────────────────────────────────────────
    retention_copies = Column(Integer, default=7, nullable=False)  # cuántas copias conservar

    # ── Programación automática ───────────────────────────────────────────────
    schedule_enabled = Column(Boolean, default=False, nullable=False)
    # Campos cron estilo unix (* = cualquier valor)
    schedule_minute  = Column(String(20), default="0",  nullable=False)
    schedule_hour    = Column(String(20), default="2",  nullable=False)
    schedule_day     = Column(String(20), default="*",  nullable=False)
    schedule_weekday = Column(String(20), default="*",  nullable=False)

    # ── Estado ────────────────────────────────────────────────────────────────
    is_active = Column(Boolean, default=True, nullable=False)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_run   = Column(DateTime, nullable=True)

    # ── Relaciones ────────────────────────────────────────────────────────────
    user    = relationship("User",   lazy="select")
    domain  = relationship("Domain", lazy="select")
    records = relationship("BackupRecord", back_populates="job",
                           cascade="all, delete-orphan", order_by="BackupRecord.started_at.desc()")


class BackupRecord(Base):
    """Registro de una ejecución concreta de un BackupJob."""

    __tablename__ = "backup_records"

    id     = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("backup_jobs.id", ondelete="CASCADE"), nullable=False, index=True)

    # Snapshot del user_id en el momento de ejecución (para auditoría aunque se borre el job)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    # ── Tipo de operación ───────────────────────────────────────────────────
    # backup  → copia de seguridad
    # restore → restauración de un snapshot
    kind = Column(String(20), default="backup", nullable=False)

    # ── Estado ────────────────────────────────────────────────────────────────
    # pending → running → success | failed | cancelled
    status = Column(String(20), default="pending", nullable=False)

    # ── Información del backup ─────────────────────────────────────────────────
    is_incremental = Column(Boolean, default=False, nullable=False)
    backup_path    = Column(String(1024), nullable=True)   # ruta en destino
    size_bytes     = Column(BigInteger, default=0)          # tamaño en bytes (BigInteger: backups > 2 GB)

    # Contadores
    files_transferred = Column(Integer, default=0)
    files_total       = Column(Integer, default=0)
    db_count          = Column(Integer, default=0)

    # ── Logs ──────────────────────────────────────────────────────────────────
    log_output    = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    started_at  = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)

    # ── Relaciones ────────────────────────────────────────────────────────────
    job  = relationship("BackupJob", back_populates="records")
    user = relationship("User", lazy="select")
