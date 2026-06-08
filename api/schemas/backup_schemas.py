"""
Schemas Pydantic para el sistema de backups.
"""

from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────────────────────────────
# BackupJob — Configuración
# ─────────────────────────────────────────────────────────────────────────────

class BackupJobBase(BaseModel):
    name:             str   = Field(..., min_length=1, max_length=100)
    description:      Optional[str] = Field(None, max_length=255)
    domain_id:        Optional[int] = None

    include_files:     bool = True
    include_databases: bool = True
    include_mail:      bool = False

    backup_type:      str = Field("incremental", pattern="^(full|incremental)$")

    destination_type: str = Field("local", pattern="^(local|sftp|s3)$")

    # Destino local
    local_path: str = Field("/backups", max_length=512)

    # Destino SFTP
    sftp_host:     Optional[str] = Field(None, max_length=255)
    sftp_port:     Optional[int] = Field(22, ge=1, le=65535)
    sftp_user:     Optional[str] = Field(None, max_length=64)
    sftp_password: Optional[str] = Field(None, max_length=500)
    sftp_path:     Optional[str] = Field(None, max_length=512)
    sftp_key_path: Optional[str] = Field(None, max_length=512)

    # Destino S3 / compatible (AWS, Backblaze B2, Wasabi, MinIO…)
    s3_endpoint:   Optional[str] = Field(None, max_length=255)
    s3_region:     Optional[str] = Field(None, max_length=64)
    s3_bucket:     Optional[str] = Field(None, max_length=255)
    s3_prefix:     Optional[str] = Field(None, max_length=512)
    s3_access_key: Optional[str] = Field(None, max_length=255)
    s3_secret_key: Optional[str] = Field(None, max_length=500)

    # Contraseña de cifrado restic (opcional al crear: si se omite, se autogenera)
    restic_password: Optional[str] = Field(None, max_length=255)

    retention_copies: int = Field(7, ge=1, le=365)

    # Programación automática
    schedule_enabled: bool = False
    schedule_minute:  str  = Field("0", max_length=20)
    schedule_hour:    str  = Field("2", max_length=20)
    schedule_day:     str  = Field("*", max_length=20)
    schedule_weekday: str  = Field("*", max_length=20)

    is_active:        bool = True

    @field_validator("name")
    @classmethod
    def name_strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("destination_type")
    @classmethod
    def validate_sftp_fields(cls, v: str) -> str:
        return v

    class Config:
        from_attributes = True


class BackupJobCreate(BackupJobBase):
    pass


class BackupJobUpdate(BaseModel):
    name:             Optional[str] = Field(None, min_length=1, max_length=100)
    description:      Optional[str] = Field(None, max_length=255)
    include_files:    Optional[bool] = None
    include_databases:Optional[bool] = None
    include_mail:     Optional[bool] = None
    backup_type:      Optional[str] = Field(None, pattern="^(full|incremental)$")
    destination_type: Optional[str] = Field(None, pattern="^(local|sftp|s3)$")
    local_path:       Optional[str] = Field(None, max_length=512)
    sftp_host:        Optional[str] = Field(None, max_length=255)
    sftp_port:        Optional[int] = Field(None, ge=1, le=65535)
    sftp_user:        Optional[str] = Field(None, max_length=64)
    sftp_password:    Optional[str] = Field(None, max_length=500)
    sftp_path:        Optional[str] = Field(None, max_length=512)
    sftp_key_path:    Optional[str] = Field(None, max_length=512)
    s3_endpoint:      Optional[str] = Field(None, max_length=255)
    s3_region:        Optional[str] = Field(None, max_length=64)
    s3_bucket:        Optional[str] = Field(None, max_length=255)
    s3_prefix:        Optional[str] = Field(None, max_length=512)
    s3_access_key:    Optional[str] = Field(None, max_length=255)
    s3_secret_key:    Optional[str] = Field(None, max_length=500)
    retention_copies: Optional[int] = Field(None, ge=1, le=365)

    schedule_enabled: Optional[bool] = None
    schedule_minute:  Optional[str]  = Field(None, max_length=20)
    schedule_hour:    Optional[str]  = Field(None, max_length=20)
    schedule_day:     Optional[str]  = Field(None, max_length=20)
    schedule_weekday: Optional[str]  = Field(None, max_length=20)

    is_active:        Optional[bool] = None

    class Config:
        from_attributes = True


class BackupJobResponse(BackupJobBase):
    id:         int
    user_id:    int
    last_run:   Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    # Último registro resumido (inyectado en la ruta)
    last_record_status: Optional[str] = None
    last_record_size_mb: Optional[float] = None

    # Las credenciales nunca se devuelven al cliente
    sftp_password: Optional[str] = None
    s3_secret_key: Optional[str] = None
    restic_password: Optional[str] = None
    # La contraseña de cifrado restic en claro SOLO se devuelve al CREAR el job
    # (para que el usuario la anote); nunca más.
    restic_password_plain: Optional[str] = None

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────────────────────
# BackupRecord — Historial de ejecuciones
# ─────────────────────────────────────────────────────────────────────────────

class BackupRecordResponse(BaseModel):
    id:                int
    job_id:            int
    user_id:           Optional[int] = None
    kind:              str = "backup"
    status:            str
    is_incremental:    bool
    backup_path:       Optional[str] = None
    size_bytes:        int
    size_mb:           Optional[float] = None
    files_transferred: int
    files_total:       int
    db_count:          int
    log_output:        Optional[str] = None
    error_message:     Optional[str] = None
    started_at:        datetime
    finished_at:       Optional[datetime] = None
    duration_seconds:  Optional[int] = None

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────────────────────
# Snapshots en disco
# ─────────────────────────────────────────────────────────────────────────────

class BackupSnapshotResponse(BaseModel):
    name:           str          # timestamp YYYYMMDD_HHMMSS
    path:           str
    size_bytes:     int
    size_mb:        float
    is_incremental: bool
    db_count:       int
    has_files:      bool
    has_databases:  bool
    has_mail:       bool


# ─────────────────────────────────────────────────────────────────────────────
# Trigger manual
# ─────────────────────────────────────────────────────────────────────────────

class BackupRunRequest(BaseModel):
    force_full: bool = False   # ignorar tipo y hacer copia completa


class BackupRestoreRequest(BaseModel):
    # ID de snapshot restic (hex corto) o "latest"
    snapshot_name:     str = Field(..., min_length=1, max_length=64)
    restore_files:     bool = True
    restore_databases: bool = True
    restore_mail:      bool = False
