"""
Modelos de correo electrónico: MailDomain, Mailbox, MailAlias, WebmailToken
Almacenamiento bajo /home/{panel_user}/mail/{domain}/{mailbox}/
"""

from sqlalchemy import (
    Column, Integer, Float, String, Boolean, DateTime, Text,
    ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import relationship, backref
from datetime import datetime
from api.models.database import Base


class MailDomain(Base):
    """
    Dominio de correo habilitado en el panel.
    Un dominio web puede tener un MailDomain asociado (domain_id)
    o puede ser un dominio de correo sin web (domain_id=NULL).
    """
    __tablename__ = "mail_domains"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    # Dominio web vinculado (opcional — puede ser solo correo sin web)
    domain_id   = Column(Integer, ForeignKey("domains.id", ondelete="SET NULL"),
                         nullable=True, index=True)
    domain_name = Column(String(255), unique=True, nullable=False, index=True)
    is_active   = Column(Boolean, default=True)
    is_suspended = Column(Boolean, default=False, nullable=False)  # suspensión admin

    # ── DKIM ──────────────────────────────────────────────────────────────
    # Clave generada en /etc/rspamd/dkim/{domain}.{selector}.key
    dkim_enabled    = Column(Boolean, default=False)
    dkim_selector   = Column(String(50), default="mail")   # mail._domainkey.domain
    dkim_public_key = Column(Text, nullable=True)           # clave pública (para mostrar TXT)

    # ── Catch-all ─────────────────────────────────────────────────────────
    # Si no es NULL, todo correo sin buzón explícito se redirige aquí
    catch_all = Column(String(255), nullable=True)

    # ── Límites ───────────────────────────────────────────────────────────
    max_mailboxes = Column(Integer, default=0)   # 0 = sin límite
    # Rate-limit de envío del dominio (Rspamd): correos/hora sumando todos sus
    # buzones. 0 = sin límite. Anti-abuso si una cuenta es comprometida.
    send_limit_hour = Column(Integer, default=1000)

    # ── Preferencia de IP de salida SMTP del dominio ───────────────────────
    # Cómo sale el correo de este dominio (sender_dependent transport + bind):
    #   "ipv4" (default) → bindea la IPv4 del servidor/dominio (rDNS garantizado)
    #   "ipv6"           → prefiere la IPv6 del dominio (requiere rDNS v6; la
    #                      entregabilidad es responsabilidad del cliente)
    # Solo tiene efecto si el dominio web vinculado tiene IPv6 asignada.
    mail_out_ip_pref = Column(String(8), default="ipv4", nullable=False)

    # ── SMTP relay propio del dominio (override del relay global) ──────────
    # Si está activo, el correo de ESTE dominio sale por su smarthost (p. ej.
    # Proxmox Mail Gateway, Brevo). La contraseña vive en el password map de
    # Postfix (0600), no en la BD.
    relay_enabled  = Column(Boolean, default=False)
    relay_host     = Column(String(255), nullable=True)
    relay_port     = Column(Integer, default=587)
    relay_username = Column(String(255), nullable=True)

    # ── TLS por dominio (SNI) ──────────────────────────────────────────────
    # Si está activo, el correo de este dominio presenta su propio certificado
    # en mail.{dominio} (IMAP/POP3/SMTP) vía SNI. El cert es el del dominio
    # (Let's Encrypt) con mail.{dominio} como SAN.
    mail_tls_enabled = Column(Boolean, default=False)

    # ── Antispam (Rspamd por dominio) ─────────────────────────────────────
    spam_tag_threshold    = Column(Float, default=6.0)   # score → añadir cabecera spam
    spam_reject_threshold = Column(Float, default=15.0)  # score → rechazar
    whitelist_senders     = Column(Text, default="")     # emails/dominios permitidos (uno por línea)
    blacklist_senders     = Column(Text, default="")     # emails/dominios bloqueados (uno por línea)

    # ── Antivirus (ClamAV vía Rspamd) ─────────────────────────────────────
    # Si está activo, el correo entrante a este dominio con virus se RECHAZA.
    antivirus_enabled     = Column(Boolean, default=False)

    # ── Greylisting por dominio ───────────────────────────────────────────
    # True (por defecto) = se aplica el greylisting global. False = este dominio
    # NO hace greylisting (entrega inmediata, sin retraso). Solo tiene efecto si
    # el greylisting está activo a nivel de servidor.
    greylist_enabled      = Column(Boolean, default=True, nullable=False)

    # ── Mover spam a Junk por dominio ─────────────────────────────────────
    # True (por defecto) = el spam marcado (X-Spam: Yes) va a la carpeta Junk.
    # False = este dominio NO clasifica spam a Junk (Rspamd no lo marca); el
    # rechazo de spam claro se mantiene. Solo aplica si está activo a nivel global.
    spam_to_junk_enabled  = Column(Boolean, default=True, nullable=False)

    # ── Timestamps ────────────────────────────────────────────────────────
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ── Relaciones ────────────────────────────────────────────────────────
    user      = relationship("User", back_populates="mail_domains")
    mailboxes = relationship("Mailbox",  back_populates="mail_domain",
                             cascade="all, delete-orphan")
    aliases   = relationship("MailAlias", back_populates="mail_domain",
                             cascade="all, delete-orphan")

    @property
    def mailbox_count(self):
        return len(self.mailboxes)

    @property
    def alias_count(self):
        return len(self.aliases)

    def __repr__(self):
        return f"<MailDomain {self.domain_name}>"


class Mailbox(Base):
    """
    Buzón virtual de correo.
    El usuario físico es vmail (uid 5000); el correo se almacena en
    /home/{panel_username}/mail/{domain_name}/{username}/
    La contraseña se guarda en formato Dovecot: {SHA512-CRYPT}hash
    """
    __tablename__ = "mailboxes"

    id             = Column(Integer, primary_key=True, index=True)
    mail_domain_id = Column(Integer, ForeignKey("mail_domains.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    username           = Column(String(255), nullable=False)   # "info" → info@domain.com
    password_hash      = Column(String(255), nullable=False)   # {SHA512-CRYPT}...
    encrypted_password = Column(String(512),  nullable=True)   # Fernet-AES para autologin webmail
    quota_mb           = Column(Integer, default=1024)         # MB; 0 = sin límite
    # Rate-limit de envío de ESTE buzón (Rspamd): correos/hora. 0 = sin límite.
    send_limit_hour    = Column(Integer, default=200)
    is_active          = Column(Boolean, default=True)
    is_suspended       = Column(Boolean, default=False, nullable=False)  # suspensión admin
    # ── Reenvío ───────────────────────────────────────────────────────────
    forward_to         = Column(Text, nullable=True)        # emails separados por coma
    forward_keep_copy  = Column(Boolean, default=True)      # guardar copia local
    # ── Auto-respuesta ────────────────────────────────────────────────────
    autoreply_enabled  = Column(Boolean, default=False)
    autoreply_subject  = Column(String(255), nullable=True)
    autoreply_body     = Column(Text, nullable=True)
    created_at         = Column(DateTime, default=datetime.utcnow)
    updated_at         = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("mail_domain_id", "username", name="uq_mailbox_domain_username"),
    )

    mail_domain = relationship("MailDomain", back_populates="mailboxes")

    @property
    def full_email(self):
        return f"{self.username}@{self.mail_domain.domain_name}"

    @property
    def maildir_path(self):
        """Ruta del Maildir en el sistema de ficheros"""
        owner = self.mail_domain.user.username
        domain = self.mail_domain.domain_name
        return f"/home/{owner}/mail/{domain}/{self.username}"

    def __repr__(self):
        return f"<Mailbox {self.username}@{self.mail_domain.domain_name}>"


class MailAlias(Base):
    """
    Alias (redirección) de correo: source@domain → destination.
    El campo source puede ser:
      - Un prefijo normal:  "info"  → info@domain.com
      - Catch-all del dominio: "@"  → cualquier dirección no resuelta
    """
    __tablename__ = "mail_aliases"

    id             = Column(Integer, primary_key=True, index=True)
    mail_domain_id = Column(Integer, ForeignKey("mail_domains.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    source      = Column(String(255), nullable=False)   # prefijo (sin @domain)
    destination = Column(String(255), nullable=False)   # email destino completo
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("mail_domain_id", "source", name="uq_alias_domain_source"),
    )

    mail_domain = relationship("MailDomain", back_populates="aliases")

    @property
    def full_source(self):
        if self.source == "@":
            return f"@{self.mail_domain.domain_name}"
        return f"{self.source}@{self.mail_domain.domain_name}"

    def __repr__(self):
        return f"<MailAlias {self.full_source} → {self.destination}>"


class WebmailToken(Base):
    """
    Token de un solo uso para autologin a Roundcube.
    Generado por el panel → consumido por el plugin de Roundcube (localhost).
    TTL: 60 segundos. Se marca 'used' al consumirse.
    """
    __tablename__ = "webmail_tokens"

    id         = Column(Integer, primary_key=True, index=True)
    token      = Column(String(64), unique=True, nullable=False, index=True)
    mailbox_id = Column(Integer,
                        ForeignKey("mailboxes.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    used       = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # passive_deletes=True: al borrar el buzón, dejamos que la BD haga el
    # CASCADE (ondelete arriba) en vez de que el ORM intente poner mailbox_id=NULL
    # (que violaba el NOT NULL → error 500 al eliminar un buzón).
    mailbox = relationship(
        "Mailbox",
        backref=backref("webmail_tokens", cascade="all, delete-orphan",
                        passive_deletes=True),
    )

    def __repr__(self):
        return f"<WebmailToken mailbox={self.mailbox_id} used={self.used}>"
