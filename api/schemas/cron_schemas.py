"""
Schemas Pydantic para gestión de cron jobs de clientes.
"""

import re
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, field_validator


# Expresión regular básica para validar un campo cron (minuto/hora/día/mes/día-semana)
# Permite: *, números, rangos (1-5), listas (1,2,3), pasos (*/5, 1-5/2)
_CRON_FIELD_RE = re.compile(
    r"^(\*|(\*\/[0-9]+)|([0-9]+([-,][0-9]+)*(\/[0-9]+)?))$"
)

def _validate_cron_field(value: str, field_name: str) -> str:
    """Valida un campo individual de expresión cron."""
    value = value.strip()
    if not _CRON_FIELD_RE.match(value):
        raise ValueError(f"Valor de {field_name} inválido: '{value}'")
    return value


def _reject_newlines(value: str, field_name: str) -> str:
    """Rechaza saltos de línea en un campo que se escribe en el crontab.

    Sin esto, un \\n en command/comment partiría la línea del crontab e
    inyectaría entradas arbitrarias (que el panel ni controla ni muestra),
    saltándose el wrapper de historial. El .strip() de los validadores solo
    quita saltos en los extremos, no en medio."""
    if "\n" in value or "\r" in value:
        raise ValueError(f"El campo {field_name} no puede contener saltos de línea")
    return value


# Metacaracteres de shell no permitidos en el comando de un cron.
# El comando acaba pasando por un shell, así que estos constructos permiten
# encadenar órdenes, sustituir comandos o redirigir a ficheros arbitrarios.
# El quoting de cron_manager evita que la línea del crontab se parta, pero esto
# es la capa que impide que el propio comando haga algo distinto de lo que dice.
# Un cron corre como el usuario del dominio (no root), así que esto es defensa
# en profundidad, no la única barrera.
_DANGEROUS_OPERATORS = (
    ";",      # encadenar comandos
    "&&",     # AND lógico
    "||",     # OR lógico
    "|",      # tubería (wget ... | sh)
    "`",      # sustitución de comandos (backticks)
    "$(",     # sustitución de comandos POSIX
    "${",     # expansión de variables (${IFS} para evadir filtros)
    "2>&1",   # redirección de descriptores
    ">",      # redirección de salida (cubre >, >>, >| y >{)
    "<",      # redirección de entrada
    "&",      # segundo plano
    "\n", "\r",  # ya cubiertos por _reject_newlines; aquí por si acaso
)


def _validate_cron_command(value: str) -> str:
    """Valida el comando de un cron: no vacío, sin saltos de línea y sin
    metacaracteres de shell. Único punto de verdad para Create y Update."""
    value = value.strip()
    if not value:
        raise ValueError("El comando no puede estar vacío")
    _reject_newlines(value, "command")
    for op in _DANGEROUS_OPERATORS:
        if op in value:
            raise ValueError(
                f"El comando contiene un operador de shell no permitido: '{op}'. "
                "Si necesitas encadenar órdenes o redirigir la salida, pon los "
                "comandos en un script y programa el script."
            )
    return value


class CronJobCreate(BaseModel):
    # Propietario del cron. Para admin/reseller, opcional: si se indica un cliente,
    # el cron se ejecuta BAJO ese usuario del sistema (aislado), no como root.
    # Si se omite, el cron es del propio usuario que lo crea.
    user_id:   Optional[int] = None
    domain_id: Optional[int] = None
    minute:    str = "*"
    hour:      str = "*"
    day:       str = "*"
    month:     str = "*"
    weekday:   str = "*"
    command:   str
    comment:   Optional[str] = None

    @field_validator("minute")
    @classmethod
    def val_minute(cls, v):
        return _validate_cron_field(v, "minute")

    @field_validator("hour")
    @classmethod
    def val_hour(cls, v):
        return _validate_cron_field(v, "hour")

    @field_validator("day")
    @classmethod
    def val_day(cls, v):
        return _validate_cron_field(v, "day")

    @field_validator("month")
    @classmethod
    def val_month(cls, v):
        return _validate_cron_field(v, "month")

    @field_validator("weekday")
    @classmethod
    def val_weekday(cls, v):
        return _validate_cron_field(v, "weekday")

    @field_validator("command")
    @classmethod
    def val_command(cls, v):
        return _validate_cron_command(v)

    @field_validator("comment")
    @classmethod
    def val_comment(cls, v):
        return _reject_newlines(v, "comment") if v is not None else v


class CronJobUpdate(BaseModel):
    domain_id: Optional[int] = None
    minute:    Optional[str] = None
    hour:      Optional[str] = None
    day:       Optional[str] = None
    month:     Optional[str] = None
    weekday:   Optional[str] = None
    command:   Optional[str] = None
    comment:   Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("minute", mode="before")
    @classmethod
    def val_minute(cls, v):
        return _validate_cron_field(v, "minute") if v is not None else v

    @field_validator("hour", mode="before")
    @classmethod
    def val_hour(cls, v):
        return _validate_cron_field(v, "hour") if v is not None else v

    @field_validator("day", mode="before")
    @classmethod
    def val_day(cls, v):
        return _validate_cron_field(v, "day") if v is not None else v

    @field_validator("month", mode="before")
    @classmethod
    def val_month(cls, v):
        return _validate_cron_field(v, "month") if v is not None else v

    @field_validator("weekday", mode="before")
    @classmethod
    def val_weekday(cls, v):
        return _validate_cron_field(v, "weekday") if v is not None else v

    @field_validator("command", mode="before")
    @classmethod
    def val_command(cls, v):
        return _validate_cron_command(v) if v is not None else v

    @field_validator("comment", mode="before")
    @classmethod
    def val_comment(cls, v):
        return _reject_newlines(v, "comment") if v is not None else v


class CronJobResponse(BaseModel):
    id:         int
    user_id:    int
    username:   Optional[str] = None   # username del propietario (para la vista admin)
    domain_id:  Optional[int]
    minute:     str
    hour:       str
    day:        str
    month:      str
    weekday:    str
    command:    str
    comment:    Optional[str]
    is_active:  bool
    created_at: datetime
    updated_at: Optional[datetime]
    last_run:   Optional[datetime]

    class Config:
        from_attributes = True
