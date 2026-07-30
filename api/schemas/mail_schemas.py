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

# Límites del RFC 5321 §4.5.3.1 (los del formato de dirección, no del mensaje):
#   parte local ≤ 64, dominio ≤ 255, total ≤ 254 en la práctica.
MAX_LOCAL_PART = 64
MAX_DOMAIN     = 255
MAX_EMAIL      = 254

# Parte local: allowlist estricta. NO se admite el "quoted string" del RFC 5322
# ("john doe"@ejemplo.com): es válido por RFC pero irrelevante en hosting real y
# rompería los mapas de Postfix (formato clave<TAB>valor) y el passwd-file de
# Dovecot (formato separado por ':').
_LOCAL_RE = re.compile(r'^[a-z0-9][a-z0-9._+-]*$')
# Dominio: etiquetas alfanuméricas con guiones internos, TLD alfabético.
_DOMAIN_RE = re.compile(r'^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$')


def validate_email_address(v: str, field: str = "dirección") -> str:
    """Valida una dirección de correo COMPLETA (local@dominio).

    Sustituye a la regex laxa `^[^@]+@[^@]+\\.[^@]+$` que se repetía en tres
    sitios. Esa regex usaba `[^@]`, que acepta TODO menos la arroba: espacios,
    comas, tabuladores, comillas, ':' y '\\'. Eso importa porque estos valores se
    escriben tal cual en /etc/postfix/virtual_alias (formato «clave<TAB>valor») y
    en el passwd-file de Dovecot (campos separados por ':'):

      - un espacio o TAB en el destino → Postfix lee un destino inválido y el
        correo reenviado se pierde en silencio;
      - una coma → Postfix la interpreta como separador de destinos;
      - dos puntos → rompe la línea del passwd-file de Dovecot.

    Rechaza además lo que el RFC no permite y suele fallar con MTAs remotos:
    punto al principio o al final de la parte local, y dos puntos seguidos.
    """
    if v is None:
        raise ValueError(f"La {field} no puede estar vacía")
    v = v.strip().lower()
    if not v:
        raise ValueError(f"La {field} no puede estar vacía")

    # Cualquier espacio en blanco (incluidos \n, \r, \t) invalida la dirección y
    # además corrompería el fichero de mapas.
    if any(c.isspace() for c in v):
        raise ValueError(f"La {field} no puede contener espacios ni saltos de línea")

    if v.count("@") != 1:
        raise ValueError(f"La {field} debe tener exactamente una @")
    local, domain = v.split("@", 1)

    if len(v) > MAX_EMAIL:
        raise ValueError(f"La {field} es demasiado larga (máx {MAX_EMAIL} caracteres)")
    if len(local) > MAX_LOCAL_PART:
        raise ValueError(
            f"La parte antes de la @ es demasiado larga (máx {MAX_LOCAL_PART})")
    if len(domain) > MAX_DOMAIN:
        raise ValueError(f"El dominio es demasiado largo (máx {MAX_DOMAIN})")

    if not _LOCAL_RE.match(local):
        raise ValueError(
            f"La {field} tiene caracteres no permitidos antes de la @ "
            "(solo letras, dígitos y . _ + -)")
    if local.startswith(".") or local.endswith(".") or ".." in local:
        raise ValueError(
            f"La {field} no puede empezar ni acabar en punto, ni tener dos seguidos")
    if not _DOMAIN_RE.match(domain):
        raise ValueError(f"El dominio de la {field} no es válido")
    return v


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
    # Igual que en la parte local de una dirección: '.inicio', 'fin.' y 'a..b'
    # los rechaza el RFC y dan problemas con MTAs remotos.
    if v.startswith(".") or v.endswith(".") or ".." in v:
        raise ValueError(
            "El nombre no puede empezar ni acabar en punto, ni tener dos seguidos")
    return v


def _validate_forward_list(v: str) -> str:
    """Valida una lista de destinos de reenvío separados por comas.

    forward_to no tenía NINGUNA validación: llegaba tal cual a set_forward() y de
    ahí a virtual_alias, así que un destino con espacios o comillas se escribía
    crudo en el mapa de Postfix."""
    if v is None:
        return None
    if not v.strip():
        return ""
    destinos = [d.strip() for d in v.split(",") if d.strip()]
    if not destinos:
        return ""
    if len(destinos) > 20:
        raise ValueError("Demasiados destinos de reenvío (máx 20)")
    validados = [validate_email_address(d, "dirección de reenvío") for d in destinos]
    # Deduplicar conservando el orden (un destino repetido duplicaría el correo).
    vistos, unicos = set(), []
    for d in validados:
        if d not in vistos:
            vistos.add(d)
            unicos.append(d)
    return ", ".join(unicos)


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
    # Propietario. Obligatorio para admin/reseller: el dominio de correo pertenece
    # a un cliente, no al admin. Se ignora para un usuario normal (es él mismo).
    user_id:       Optional[int] = Field(None, description="ID del cliente propietario (admin/reseller)")
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
        return validate_email_address(v, "dirección del catch-all")


class MailDomainUpdate(BaseModel):
    # max_length igual que en Create: era asimétrico (Create lo tenía, Update no).
    catch_all:     Optional[str]  = Field(None, max_length=254)
    max_mailboxes: Optional[int]  = Field(None, ge=0)
    is_active:     Optional[bool] = None
    send_limit_hour: Optional[int] = Field(None, ge=0, le=1000000)

    @field_validator("catch_all")
    @classmethod
    def validate_catch_all(cls, v):
        if v is None or v == "":
            return None
        return validate_email_address(v, "dirección del catch-all")


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
    send_limit_hour: int           = 1000
    antivirus_enabled: bool        = False
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
    is_suspended:  bool          = False
    dkim_enabled:  bool
    dkim_selector: str
    catch_all:     Optional[str] = None
    max_mailboxes: int
    antivirus_enabled: bool       = False
    mailbox_count: int           = 0
    alias_count:   int           = 0
    mail_used_mb:  int           = 0
    webmail_ssl:   bool          = False
    mail_ssl:      bool          = False
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
    send_limit_hour: int = Field(200, ge=0, le=100000,
                                 description="Máx. correos/hora que puede enviar; 0 = sin límite")

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
    send_limit_hour: Optional[int] = Field(None, ge=0, le=100000)
    # Reenvío
    forward_to:        Optional[str]  = Field(None, max_length=2048)   # separados por coma
    forward_keep_copy: Optional[bool] = None
    # Auto-respuesta
    autoreply_enabled: Optional[bool] = None
    autoreply_subject: Optional[str]  = Field(None, max_length=255)
    # 64 KB: una plantilla HTML de correo real (tablas + estilos inline + varios
    # idiomas) pasa fácil de 10 KB; el límite anterior las rechazaba.
    autoreply_body:    Optional[str]  = Field(None, max_length=65536)
    autoreply_is_html: Optional[bool] = None
    autoreply_body_text: Optional[str] = Field(None, max_length=20000)
    autoreply_days:    Optional[int]  = Field(None, ge=1, le=60)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if v is not None:
            return _validate_password(v)
        return v

    @field_validator("forward_to")
    @classmethod
    def validate_forward_to(cls, v):
        return _validate_forward_list(v)

    @field_validator("autoreply_subject")
    @classmethod
    def validate_autoreply_subject(cls, v):
        """El asunto va a una cabecera del Sieve de autorespuesta: un salto de
        línea permitiría inyectar cabeceras adicionales en la respuesta."""
        if v is None:
            return v
        if "\n" in v or "\r" in v:
            raise ValueError("El asunto no puede contener saltos de línea")
        return v.strip()


class MailboxResponse(BaseModel):
    id:             int
    mail_domain_id: int
    username:       str
    quota_mb:       int
    send_limit_hour: int = 200
    is_active:      bool
    full_email:     str = ""
    disk_usage_mb:  float = 0.0
    forward_to:        Optional[str]  = None
    forward_keep_copy: bool = True
    autoreply_enabled: bool = False
    autoreply_subject: Optional[str] = None
    autoreply_body:    Optional[str] = None
    autoreply_is_html: bool = False
    autoreply_body_text: Optional[str] = None
    autoreply_days:    int = 1
    created_at:     Optional[datetime] = None
    updated_at:     Optional[datetime] = None

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────────────────────
# MailAlias
# ─────────────────────────────────────────────────────────────────────────────

class MailAliasCreate(BaseModel):
    # max_length 64: es la parte local de una dirección (RFC 5321). Antes decía
    # 128, que contradecía al propio validador (tope 64) y no servía de nada.
    source:      str = Field(..., max_length=64,
                             description="Prefijo origen, ej: 'info' o '@' para catch-all")
    destination: str = Field(..., max_length=254,
                             description="Email destino completo")

    @field_validator("source")
    @classmethod
    def validate_source(cls, v):
        v = v.lower().strip()
        if v == "@":
            return v   # catch-all explícito
        # Mismo validador que el nombre de buzón: es el mismo tipo de valor y
        # antes estaba duplicado inline (y sin el check de puntos).
        return _validate_mailbox_username(v)

    @field_validator("destination")
    @classmethod
    def validate_destination(cls, v):
        return validate_email_address(v, "dirección de destino")


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


# ─────────────────────────────────────────────────────────────────────────────
# Webmail autologin (Roundcube)
# ─────────────────────────────────────────────────────────────────────────────

class WebmailTokenResponse(BaseModel):
    """Respuesta al generar un token de autologin para Roundcube"""
    token:      str
    url:        str   # URL completa con el token para abrir Roundcube
    expires_in: int   # Segundos de validez (60 por defecto)


class RoundcubeStatusResponse(BaseModel):
    """Estado de Roundcube: si está instalado y su URL de acceso"""
    enabled:     bool
    url:         Optional[str] = None   # None si no está instalado
    webmail_url: Optional[str] = None   # URL base del webmail (sin token)
