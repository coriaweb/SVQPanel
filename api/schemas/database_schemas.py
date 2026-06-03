"""
Schemas Pydantic para gestión de bases de datos MariaDB de clientes.
"""

from pydantic import BaseModel, field_validator, model_validator, Field
from typing import Optional, List
from datetime import datetime
import re


# Charsets y collations soportados por MariaDB
VALID_CHARSETS = {"utf8mb4", "utf8", "latin1", "ascii"}
VALID_COLLATIONS = {
    "utf8mb4_unicode_ci", "utf8mb4_general_ci", "utf8mb4_spanish_ci",
    "utf8_unicode_ci", "utf8_general_ci",
    "latin1_swedish_ci", "latin1_spanish_ci",
    "ascii_general_ci",
}

# Nombre válido: letras minúsculas, números, guiones bajos. Empieza por letra/número.
_NAME_RE = re.compile(r'^[a-z0-9][a-z0-9_]{0,31}$')


def _validate_db_name(v: str, field_label: str) -> str:
    v = v.lower().strip()
    if not _NAME_RE.match(v):
        raise ValueError(
            f"{field_label}: solo letras minúsculas, números y '_'. "
            f"Debe empezar por letra o número. Máximo 32 caracteres."
        )
    # Evitar palabras reservadas de MySQL
    reserved = {"mysql", "information_schema", "performance_schema", "sys", "test"}
    if v in reserved:
        raise ValueError(f"{field_label}: '{v}' es una palabra reservada de MariaDB")
    return v


# ── Request schemas ───────────────────────────────────────────────────────────

class DatabaseCreate(BaseModel):
    """Crea una BD MariaDB. Los nombres se prefijan con el username del propietario."""
    db_name_suffix: str   # sufijo; nombre real = {username}_{sufijo}
    db_user_suffix: str   # sufijo usuario; user real = {username}_{sufijo}
    db_password: str
    domain_id: Optional[int] = None  # dominio asociado (opcional)
    db_charset: str = "utf8mb4"
    db_collation: str = "utf8mb4_unicode_ci"
    quota_mb: int = 1024             # 0 = sin límite

    @field_validator("db_name_suffix")
    @classmethod
    def validate_db_name_suffix(cls, v):
        return _validate_db_name(v, "db_name_suffix")

    @field_validator("db_user_suffix")
    @classmethod
    def validate_db_user_suffix(cls, v):
        return _validate_db_name(v, "db_user_suffix")

    @field_validator("db_password")
    @classmethod
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError("La contraseña debe tener al menos 8 caracteres")
        if len(v) > 128:
            raise ValueError("La contraseña no puede superar 128 caracteres")
        return v

    @field_validator("db_charset")
    @classmethod
    def validate_charset(cls, v):
        if v not in VALID_CHARSETS:
            raise ValueError(f"Charset inválido. Opciones: {', '.join(VALID_CHARSETS)}")
        return v

    @field_validator("db_collation")
    @classmethod
    def validate_collation(cls, v):
        if v not in VALID_COLLATIONS:
            raise ValueError(f"Collation inválida. Opciones: {', '.join(VALID_COLLATIONS)}")
        return v

    @field_validator("quota_mb")
    @classmethod
    def validate_quota(cls, v):
        if v < 0:
            raise ValueError("quota_mb no puede ser negativo")
        if v > 102400:  # 100 GB
            raise ValueError("quota_mb máximo: 102400 (100 GB)")
        return v


class DatabaseChangePassword(BaseModel):
    """Cambia la contraseña del usuario MariaDB de una BD"""
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError("La contraseña debe tener al menos 8 caracteres")
        if len(v) > 128:
            raise ValueError("La contraseña no puede superar 128 caracteres")
        return v


class DatabaseUpdate(BaseModel):
    """Actualiza configuración de una BD (quota, dominio asociado)"""
    domain_id: Optional[int] = None
    quota_mb: Optional[int] = None
    is_active: Optional[bool] = None

    @field_validator("quota_mb")
    @classmethod
    def validate_quota(cls, v):
        if v is not None and v < 0:
            raise ValueError("quota_mb no puede ser negativo")
        return v


# ── Response schemas ──────────────────────────────────────────────────────────

class DatabaseResponse(BaseModel):
    """Datos de una BD (sin contraseña)"""
    id: int
    user_id: int
    domain_id: Optional[int]

    db_name: str          # nombre real en MariaDB (con prefijo)
    db_name_suffix: str   # sufijo elegido por el usuario
    db_user: str          # usuario real en MariaDB (con prefijo)
    db_user_suffix: str   # sufijo elegido por el usuario

    db_charset: str
    db_collation: str
    size_mb: int
    quota_mb: int
    is_active: bool

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DatabaseCreateResponse(DatabaseResponse):
    """
    Respuesta al crear una BD.
    Incluye la contraseña EN CLARO una única vez — el cliente debe guardarla.
    """
    db_password: str
    message: str = (
        "⚠ Guarda la contraseña ahora. No podrás recuperarla después. "
        "Si la pierdes tendrás que resetearla."
    )


class DatabasePasswordResetResponse(BaseModel):
    """Respuesta al resetear contraseña"""
    status: str = "success"
    db_user: str
    new_password: str
    message: str = "Contraseña actualizada correctamente"


class DatabaseListResponse(BaseModel):
    """Lista paginada de BDs"""
    total: int
    items: list[DatabaseResponse]


# ─── Usuarios adicionales de BD ───────────────────────────────────────────────

ALLOWED_PERMISSIONS = {
    "SELECT", "INSERT", "UPDATE", "DELETE",
    "CREATE", "DROP", "INDEX", "ALTER",
    "REFERENCES", "LOCK TABLES",
}


class DatabaseUserCreate(BaseModel):
    """Crea un usuario adicional de MariaDB para una BD."""
    username_suffix: str = Field(
        ...,
        min_length=1,
        max_length=16,
        pattern=r'^[a-z0-9_]+$',
    )
    password: str = Field(..., min_length=8, max_length=128)
    permissions: List[str] = Field(
        default=["SELECT", "INSERT", "UPDATE", "DELETE"],
    )

    @field_validator("permissions")
    @classmethod
    def validate_perms(cls, v):
        invalid = set(v) - ALLOWED_PERMISSIONS
        if invalid:
            raise ValueError(f"Permisos no válidos: {invalid}")
        if not v:
            raise ValueError("Debe haber al menos un permiso")
        return list(set(v))  # deduplicar


class DatabaseUserUpdate(BaseModel):
    """Actualiza permisos y/o contraseña de un usuario adicional."""
    permissions: Optional[List[str]] = None
    password: Optional[str] = Field(None, min_length=8, max_length=128)
    is_active: Optional[bool] = None

    @field_validator("permissions")
    @classmethod
    def validate_perms(cls, v):
        if v is None:
            return v
        invalid = set(v) - ALLOWED_PERMISSIONS
        if invalid:
            raise ValueError(f"Permisos no válidos: {invalid}")
        if not v:
            raise ValueError("Debe haber al menos un permiso")
        return list(set(v))


class DatabaseUserResponse(BaseModel):
    """Datos de un usuario adicional de BD (sin contraseña)."""
    id: int
    database_id: int
    username: str
    username_suffix: str
    permissions: List[str]
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

    @field_validator("permissions", mode="before")
    @classmethod
    def parse_permissions(cls, v):
        import json
        if isinstance(v, str):
            return json.loads(v)
        return v
