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
        v = v.strip()
        if not v:
            raise ValueError("El comando no puede estar vacío")
        _reject_newlines(v, "command")
        # Bloquear caracteres peligrosos de shell
        dangerous = [";", "&&", "||", "|", "`", "$(",  ">{",  ">>", ">|", "2>&1", "&"]
        # Excepción: el pipe solo en contexto específico; aquí bloqueamos todo redirección
        forbidden_chars = set(";`")
        for char in forbidden_chars:
            if char in v:
                raise ValueError(f"El comando contiene caracteres no permitidos: '{char}'")
        # Bloquear operadores de redirección y combinación de comandos
        for op in ["&&", "||", "2>&1"]:
            if op in v:
                raise ValueError(f"El comando contiene operador no permitido: '{op}'")
        return v

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
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("El comando no puede estar vacío")
        _reject_newlines(v, "command")
        forbidden_chars = set(";`")
        for char in forbidden_chars:
            if char in v:
                raise ValueError(f"El comando contiene caracteres no permitidos: '{char}'")
        for op in ["&&", "||", "2>&1"]:
            if op in v:
                raise ValueError(f"El comando contiene operador no permitido: '{op}'")
        return v

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
