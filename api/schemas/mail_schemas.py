"""
Esquemas Pydantic para el módulo de correo electrónico
"""

import re
from pydantic import BaseModel, Field, field_validator, model_validator, ValidationInfo
from typing import Optional, List
from datetime import datetime


# ─────────────────────────────────────────────────────────────────────────────
# Validadores reutilizables
# ─────────────────────────────────────────────────────────────────────────────

def _validate_mailbox_username(v: str) -> str:
    """Valida que un nombre de buzón sea un prefijo de email válido"""
    v = v.lower().strip()
    if not v:
        raise ValueError("El nombre de buzón no puede estar vacío")
    if "@" in v:
        raise ValueError("Introduce solo el nombre, sin @dominio")
    if not re.match(r'^[a-z0-9][a-z0-9._+-]{0,63}$', v):
        raise ValueError(
            "Solo letras minúsculas, dígitos y los caracteres . _ + -"
        )
    return v


def _validate_password(v: str) -> str:
    """Contraseña mínima de 8 caracteres"""
    if len(v) < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres")
    return v


# ─────────────────────────────────────────────────────────────────────────────
# MailDomain
# ─────────────────────────────────────────────────────────────────────────────

class MailDomainCreate(BaseModel):
    domain_name:   str           = Field(..., min_length=4, max_length=255,
                                         description="Nombre de dominio, ej: example.com")
    domain_id:     Optional[int] = Field(None, description="ID del dominio web vinculado (opcional)")
    catch_all:     Optional[str] = Field(None, max_length=255,
                                         description="Email destino del catch-all (vacío = desactivado)")
    max_mailboxes: int           = Field(0, ge=0, description="0 = sin límite")

    @field_validator("domain_name")
    @classmethod
    def validate_domain(cls, v):
        v = v.lower().strip().rstrip(".")
        pattern = r'^(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$'
        if not re.match(pattern, v):
            raise ValueError("Nombre de dominio inválido")
        return v

    @field_validator("catch_all")
    @classmethod
    def validate_catch_all(cls, v):
        if v is None or v == "":
            return None
        if not re.match(r'^[^@]+@[^@]+\.[^@]+$', v):
            raise ValueError("El catch-all debe ser una dirección de email válida")
        return v.lower().strip()


class MailDomainUpdate(BaseModel):
    catch_all:     Optional[str]  = None
    max_mailboxes: Optional[int]  = Field(None, ge=0)
    is_active:     Optional[bool] = None

    @field_validator("catch_all")
    @classmethod
    def validate_catch_all(cls, v):
        if v is None or v == "":
            return None
        if not re.match(r'^[^@]+@[^@]+\.[^@]+$', v):
            raise ValueError("El catch-all debe ser una dirección de email válida")
        return v.lower().strip()


class MailDomainResponse(BaseModel):
    id:             int
    user_id:        int
    domain_id:      Optional[int]  = None
    domain_name:    str
    is_active:      bool
    dkim_enabled:   bool
    dkim_selector:  str
    catch_all:      Optional[str]  = None
    max_mailboxes:  int
    mailbox_count:  int            = 0
    alias_count:    int            = 0
    created_at:     Optional[datetime] = None
    updated_at:     Optional[datetime] = None
    can_edit:       bool           = False

    class Config:
        from_attributes = True


class MailDomainListItem(BaseModel):
    id:            int
    user_id:       int
    domain_name:   str
    is_active:     bool
    dkim_enabled:  bool
    dkim_selector: str
    catch_all:     Optional[str] = None
    max_mailboxes: int
    mailbox_count: int           = 0
    alias_count:   int           = 0
    created_at:    Optional[datetime] = None
    can_edit:      bool          = False

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────────────────────
# Mailbox
# ─────────────────────────────────────────────────────────────────────────────

class MailboxCreate(BaseModel):
    username: str = Field(..., max_length=64,
                          description="Prefijo del email, ej: 'info' para info@dominio.com")
    password: str = Field(..., min_length=8)
    quota_mb: int = Field(1024, ge=0, description="Cuota en MB; 0 = sin límite")

    @field_validator("username")
    @classmethod
    def validate_username(cls, v):
        return _validate_mailbox_username(v)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        return _validate_password(v)


class MailboxUpdate(BaseModel):
    password:  Optional[str] = Field(None, min_length=8)
    quota_mb:  Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if v is not None:
            return _validate_password(v)
        return v


class MailboxResponse(BaseModel):
    id:             int
    mail_domain_id: int
    username:       str
    quota_mb:       int
    is_active:      bool
    full_email:     str = ""
    disk_usage_mb:  float = 0.0
    created_at:     Optional[datetime] = None
    updated_at:     Optional[datetime] = None

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────────────────────
# MailAlias
# ─────────────────────────────────────────────────────────────────────────────

class MailAliasCreate(BaseModel):
    source:      str = Field(..., max_length=128,
                             description="Prefijo origen, ej: 'info' o '@' para catch-all")
    destination: str = Field(..., max_length=255,
                             description="Email destino completo")

    @field_validator("source")
    @classmethod
    def validate_source(cls, v):
        v = v.lower().strip()
        if v == "@":
            return v   # catch-all explícito
        if "@" in v:
            raise ValueError("Introduce solo el prefijo, sin @dominio")
        if not re.match(r'^[a-z0-9][a-z0-9._+-]{0,63}$', v):
            raise ValueError("Prefijo de alias inválido")
        return v

    @field_validator("destination")
    @classmethod
    def validate_destination(cls, v):
        if not re.match(r'^[^@]+@[^@]+\.[^@]+$', v):
            raise ValueError("El destino debe ser una dirección de email válida")
        return v.lower().strip()


class MailAliasResponse(BaseModel):
    id:             int
    mail_domain_id: int
    source:         str
    destination:    str
    is_active:      bool
    full_source:    str = ""
    created_at:     Optional[datetime] = None

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────────────────────
# DKIM
# ─────────────────────────────────────────────────────────────────────────────

class DkimGenerateRequest(BaseModel):
    selector: str = Field("mail", max_length=63,
                          description="Selector DKIM, ej: 'mail' → mail._domainkey.dominio.com")

    @field_validator("selector")
    @classmethod
    def validate_selector(cls, v):
        v = v.lower().strip()
        if not re.match(r'^[a-z0-9][a-z0-9_-]{0,62}$', v):
            raise ValueError("El selector solo puede contener letras, dígitos, - y _")
        return v


class DkimResponse(BaseModel):
    enabled:          bool
    selector:         str
    dns_record_name:  Optional[str] = None
    dns_record_value: Optional[str] = None
    public_key_pem:   Optional[str] = None
    dns_auto_added:   bool          = False
    message:          str           = ""


# ─────────────────────────────────────────────────────────────────────────────
# Antispam (Rspamd por dominio)
# ─────────────────────────────────────────────────────────────────────────────

class SpamSettingsUpdate(BaseModel):
    spam_tag_threshold:    Optional[float] = Field(None, ge=1.0,  le=30.0,
        description="Score para etiquetar como spam (cabecera X-Spam)")
    spam_reject_threshold: Optional[float] = Field(None, ge=3.0,  le=100.0,
        description="Score para rechazar el mensaje definitivamente")
    whitelist_senders:     Optional[str]   = Field(None,
        description="Remitentes permitidos, uno por línea (email o @dominio)")
    blacklist_senders:     Optional[str]   = Field(None,
        description="Remitentes bloqueados, uno por línea (email o @dominio)")

    @field_validator("spam_reject_threshold")
    @classmethod
    def reject_gt_tag(cls, v, info):
        tag = info.data.get("spam_tag_threshold")
        if tag is not None and v is not None and v <= tag:
            raise ValueError("El umbral de rechazo debe ser mayor que el de etiquetado")
        return v


class SpamHistoryItem(BaseModel):
    id:             str   = ""
    from_addr:      str   = ""
    subject:        str   = ""
    action:         str   = ""
    score:          float = 0.0
    required_score: float = 0.0
    timestamp:      str   = ""
    size:           int   = 0
    ip:             str   = ""


class SpamStatsResponse(BaseModel):
    scanned:    int = 0
    rejected:   int = 0
    tagged:     int = 0
    greylisted: int = 0
    clean:      int = 0
    learned:    int = 0
    error:      Optional[str]           = None
    history:    List[SpamHistoryItem]   = []


class SpamSettingsResponse(BaseModel):
    spam_tag_threshold:    float = 6.0
    spam_reject_threshold: float = 15.0
    whitelist_senders:     str   = ""
    blacklist_senders:     str   = ""
    stats:                 SpamStatsResponse = SpamStatsResponse()
