"""
Rutas API para gestión de correo electrónico
(dominios, buzones, alias, DKIM, autologin Roundcube)
"""

import os
import uuid
import socket
import base64
import hashlib
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel as _BM, Field as _F

from api.models.database import get_db
from api.models.models_mail import MailDomain, Mailbox, MailAlias, WebmailToken
from api.models.models_dns import DnsZone, DnsRecord
from api.schemas.mail_schemas import (
    MailDomainCreate, MailDomainUpdate, MailDomainResponse, MailDomainListItem,
    MailboxCreate, MailboxUpdate, MailboxResponse,
    MailAliasCreate, MailAliasResponse,
    DkimGenerateRequest, DkimResponse,
    SpamSettingsUpdate, SpamSettingsResponse, SpamStatsResponse,
    WebmailTokenResponse, RoundcubeStatusResponse,
)
from api.dependencies import require_auth, require_admin

router = APIRouter()
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Cifrado reversible de contraseñas (para autologin webmail)
# ─────────────────────────────────────────────────────────────────────────────

def _get_fernet():
    """Devuelve un cifrador Fernet derivado de la SECRET_KEY del panel."""
    from cryptography.fernet import Fernet
    from api.utils.secret import get_secret_key
    secret = get_secret_key()
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def _encrypt_password(plain: str) -> str:
    """Cifra una contraseña en claro para almacenarla en la BD."""
    return _get_fernet().encrypt(plain.encode()).decode()


def _decrypt_password(encrypted: str) -> str:
    """Descifra una contraseña almacenada en la BD."""
    return _get_fernet().decrypt(encrypted.encode()).decode()


# ─────────────────────────────────────────────────────────────────────────────
# Dependencias
# ─────────────────────────────────────────────────────────────────────────────

def _require_mail_enabled():
    """Devuelve 503 si MAIL_ENABLED no está en true en el .env"""
    if os.getenv("MAIL_ENABLED", "false").lower() != "true":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servidor de correo no está instalado en este servidor. "
                   "Reinstala SVQPanel con la opción de correo activada."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de permisos
# ─────────────────────────────────────────────────────────────────────────────

def _can_edit(mail_domain: MailDomain, current_user) -> bool:
    """True si el usuario tiene permiso para gestionar este dominio de correo"""
    if current_user.role == "admin":
        return True
    if current_user.role == "reseller":
        # El reseller puede gestionar los dominios de correo de sus usuarios
        owner = mail_domain.user
        return (mail_domain.user_id == current_user.id or
                (owner is not None and owner.parent_id == current_user.id))
    # Usuario regular: solo sus propios dominios
    return mail_domain.user_id == current_user.id


def _require_edit(mail_domain: MailDomain, current_user):
    if not _can_edit(mail_domain, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para gestionar este dominio de correo"
        )


def _get_mail_domain_or_404(domain_id: int, db: Session) -> MailDomain:
    md = db.query(MailDomain).filter(MailDomain.id == domain_id).first()
    if not md:
        raise HTTPException(status_code=404, detail="Dominio de correo no encontrado")
    return md


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de serialización (evita DetachedInstanceError con propiedades lazy)
# ─────────────────────────────────────────────────────────────────────────────

def _cert_covers(host: str, parent_domain: str) -> bool:
    """¿Hay un certificado SSL que cubra `host`? True si:
      1) existe un cert propio /etc/letsencrypt/live/{host}/, o
      2) el cert del dominio padre incluye `host` como SAN (caso típico de
         webmail.{dom} cubierto por el cert de {dom}).
    Solo I/O + lectura de un fichero; rápido.
    """
    import os
    if os.path.exists(f"/etc/letsencrypt/live/{host}/fullchain.pem"):
        return True
    # Mirar el cert del dominio padre y ver si lista `host` en su texto (SAN).
    parent_cert = f"/etc/letsencrypt/live/{parent_domain}/cert.pem"
    try:
        if os.path.exists(parent_cert):
            with open(parent_cert, "rb") as f:
                pem = f.read()
            from cryptography import x509
            cert = x509.load_pem_x509_certificate(pem)
            try:
                san = cert.extensions.get_extension_for_class(
                    x509.SubjectAlternativeName).value
                names = san.get_values_for_type(x509.DNSName)
                return host in names
            except x509.ExtensionNotFound:
                return False
    except Exception:
        pass
    return False


def _mail_domain_used_mb(md: MailDomain) -> int:
    """Tamaño total (MB) del correo de un dominio: du de /home/{user}/mail/{dom}.
    Best-effort: 0 si no se puede medir."""
    import os
    import subprocess
    try:
        owner = md.user
        if not owner:
            return 0
        path = f"/home/{owner.username}/mail/{md.domain_name}"
        if not os.path.isdir(path):
            return 0
        r = subprocess.run(["/usr/bin/du", "-sb", "--apparent-size", path],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return 0
        return int(r.stdout.split()[0]) // (1024 * 1024)
    except Exception:
        return 0


def _mail_domain_to_dict(md: MailDomain, current_user) -> dict:
    dom = md.domain_name
    return {
        "id":            md.id,
        "user_id":       md.user_id,
        "domain_id":     md.domain_id,
        "domain_name":   md.domain_name,
        "is_active":     md.is_active,
        "is_suspended":  bool(getattr(md, "is_suspended", False)),
        "dkim_enabled":  md.dkim_enabled,
        "dkim_selector": md.dkim_selector,
        "catch_all":     md.catch_all,
        "max_mailboxes": md.max_mailboxes,
        "send_limit_hour": getattr(md, "send_limit_hour", 1000),
        "antivirus_enabled": bool(getattr(md, "antivirus_enabled", False)),
        "mailbox_count": len(md.mailboxes),
        "alias_count":   len(md.aliases),
        # Tamaño total del correo de este dominio (suma de todos sus buzones).
        "mail_used_mb":  _mail_domain_used_mb(md),
        # SSL de webmail.{dom} y mail.{dom}: cert propio O cubierto por el cert
        # del dominio padre como SAN (webmail suele ir en el cert del dominio).
        "webmail_ssl":   _cert_covers(f"webmail.{dom}", dom),
        "mail_ssl":      _cert_covers(f"mail.{dom}", dom),
        "created_at":    md.created_at,
        "updated_at":    md.updated_at,
        "can_edit":      _can_edit(md, current_user),
    }


def _mailbox_to_dict(mb: Mailbox, disk_usage_mb: float = 0.0) -> dict:
    return {
        "id":             mb.id,
        "mail_domain_id": mb.mail_domain_id,
        "username":       mb.username,
        "quota_mb":       mb.quota_mb,
        "send_limit_hour": getattr(mb, "send_limit_hour", 200),
        "is_active":      mb.is_active,
        "full_email":     f"{mb.username}@{mb.mail_domain.domain_name}",
        "disk_usage_mb":  disk_usage_mb,
        "forward_to":        getattr(mb, "forward_to", None),
        "forward_keep_copy": getattr(mb, "forward_keep_copy", True),
        "autoreply_enabled": getattr(mb, "autoreply_enabled", False),
        "autoreply_subject": getattr(mb, "autoreply_subject", None),
        "autoreply_body":    getattr(mb, "autoreply_body", None),
        "created_at":     mb.created_at,
        "updated_at":     mb.updated_at,
    }


def _alias_to_dict(al: MailAlias) -> dict:
    source_str = (f"@{al.mail_domain.domain_name}"
                  if al.source == "@"
                  else f"{al.source}@{al.mail_domain.domain_name}")
    return {
        "id":             al.id,
        "mail_domain_id": al.mail_domain_id,
        "source":         al.source,
        "destination":    al.destination,
        "is_active":      al.is_active,
        "full_source":    source_str,
        "created_at":     al.created_at,
    }


# ─────────────────────────────────────────────────────────────────────────────
# DKIM: helper para auto-añadir TXT record al DNS de SVQPanel
# ─────────────────────────────────────────────────────────────────────────────

def _dns_add_dkim_record(domain_name: str, selector: str,
                         dns_value: str, db: Session) -> bool:
    """
    Si existe una zona DNS de SVQPanel para el dominio, añade/actualiza
    el registro TXT del DKIM automáticamente.
    Devuelve True si se añadió, False si no hay zona DNS.
    """
    zone = db.query(DnsZone).filter(DnsZone.domain_name == domain_name).first()
    if not zone:
        return False

    dkim_name = f"{selector}._domainkey"
    existing = db.query(DnsRecord).filter(
        DnsRecord.zone_id == zone.id,
        DnsRecord.record_type == "TXT",
        DnsRecord.name == dkim_name,
    ).first()

    if existing:
        existing.content = dns_value
        logger.info(f"DKIM TXT actualizado en zona DNS: {dkim_name}.{domain_name}")
    else:
        db.add(DnsRecord(
            zone_id=zone.id,
            record_type="TXT",
            name=dkim_name,
            content=dns_value,
            ttl=3600,
            priority=0,
        ))
        logger.info(f"DKIM TXT añadido a zona DNS: {dkim_name}.{domain_name}")

    # Subir el serial y sincronizar la zona DE VERDAD: reescribir BIND + recargar
    # + empujar al cluster (slaves). Antes solo se reescribía el fichero sin subir
    # serial ni recargar/resync → BIND seguía sirviendo la versión vieja sin DKIM
    # y los slaves nunca recibían la clave pública (DKIM "no válido" en destino).
    from api.routes.dns import _bump_serial, _sync_zone_to_bind
    zone.serial = _bump_serial(zone.serial)
    db.commit()
    db.refresh(zone)
    try:
        _sync_zone_to_bind(zone, db)
    except Exception as e:
        logger.warning(f"No se pudo sincronizar la zona tras DKIM: {e}")

    return True


def _dns_remove_dkim_record(domain_name: str, selector: str, db: Session):
    """Elimina el registro TXT DKIM de la zona DNS de SVQPanel si existe"""
    zone = db.query(DnsZone).filter(DnsZone.domain_name == domain_name).first()
    if not zone:
        return

    dkim_name = f"{selector}._domainkey"
    db.query(DnsRecord).filter(
        DnsRecord.zone_id == zone.id,
        DnsRecord.record_type == "TXT",
        DnsRecord.name == dkim_name,
    ).delete()
    db.commit()


def _rebuild_rspamd(db: Session):
    """
    Regenera TODA la config de Rspamd derivada de la BD: umbrales/listas
    (settings+multimap) y rate-limit de envío (mapas + ratelimit.conf).
    Tolerante a fallos (entorno dev sin root). Llamar tras cualquier cambio en
    dominios de correo, buzones o sus límites.
    """
    try:
        from scripts.rspamd_manager import RspamdManager
        from sqlalchemy.orm import joinedload
        mgr = RspamdManager()
        if not mgr.rspamd_available():
            return
        all_domains = (
            db.query(MailDomain)
            .options(joinedload(MailDomain.mailboxes))
            .filter(MailDomain.is_active == True)  # noqa: E712
            .all()
        )
        # Límite del correo NO autenticado (PHP/localhost) por usuario del
        # SISTEMA. Cubre a TODOS los usuarios con web (tengan correo o no): el
        # envelope sender de ese correo es "usuario_sistema@hostname", así que
        # un sitio hackeado de cualquier dominio queda topado. Default
        # conservador (RspamdManager.DEFAULT_UNAUTH_LIMIT_HOUR); si el dominio de
        # correo tiene un send_limit menor, se respeta vía domain_sysuser.
        from api.models.models_domain import Domain
        from api.models.models_user import User as _User
        domain_sysuser = {}
        for md in all_domains:
            dom = (db.query(Domain).filter(Domain.id == md.domain_id).first()
                   if getattr(md, "domain_id", None) else None) \
                or db.query(Domain).filter(Domain.domain_name == md.domain_name).first()
            if dom:
                owner = db.query(_User).filter(_User.id == dom.user_id).first()
                if owner and owner.username:
                    domain_sysuser[md.domain_name] = owner.username

        # TODOS los usuarios de sistema con al menos un dominio web → tope default.
        unauth_sysusers = {}
        for dom in db.query(Domain).all():
            owner = db.query(_User).filter(_User.id == dom.user_id).first()
            if owner and owner.username:
                unauth_sysusers.setdefault(owner.username,
                                           RspamdManager.DEFAULT_UNAUTH_LIMIT_HOUR)

        mgr.rebuild_from_db(all_domains)
        mgr.rebuild_ratelimit_from_db(all_domains, domain_sysuser=domain_sysuser,
                                      unauth_sysusers=unauth_sysusers)
        mgr.rebuild_antivirus_from_db(all_domains)
    except PermissionError:
        logger.warning("Sin permisos para actualizar Rspamd (¿entorno dev?)")
    except Exception as e:
        logger.error(f"Error actualizando Rspamd: {e}")


def _domain_effective_ipv4(domain_name: str, db: Session) -> str:
    """IPv4 por la que vive el dominio: su IP DEDICADA si la tiene (el PTR de
    esa IP apunta a mail.{dominio}), si no la principal del servidor. Los
    helpers de DNS de correo deben usar SIEMPRE esta, no la de Settings a
    secas: forzar la del servidor pisaba la dedicada (visto con globatel.es,
    su mail A volvía a la IP compartida al activar el TLS de correo)."""
    try:
        from api.models.models_domain import Domain as _D
        d = db.query(_D).filter(_D.domain_name == domain_name).first()
        if d and getattr(d, "ipv4", None):
            return d.ipv4
    except Exception:
        pass
    from api.models.models_settings import Settings
    s = db.query(Settings).filter(Settings.id == 1).first()
    return (s.server_ipv4 if s else None) or ""


def _dns_ensure_mail_record(domain_name: str, db: Session) -> bool:
    """
    Asegura el registro 'mail' (A → IP efectiva del dominio) en la zona del
    panel, para que mail.{dominio} resuelva (necesario para el cert TLS y para
    que los clientes conecten). Devuelve True si la zona está en el panel.
    """
    zone = db.query(DnsZone).filter(DnsZone.domain_name == domain_name).first()
    if not zone:
        return False
    server_ip = _domain_effective_ipv4(domain_name, db) or zone.ip_address
    if not server_ip:
        return True  # zona en panel pero sin IP conocida; no rompemos

    from api.routes.dns import _sync_zone_to_bind, _bump_serial
    existing = db.query(DnsRecord).filter(
        DnsRecord.zone_id == zone.id, DnsRecord.name == "mail",
        DnsRecord.record_type == "A",
    ).first()
    if existing:
        if existing.content != server_ip:
            existing.content = server_ip
        else:
            return True
    else:
        db.add(DnsRecord(zone_id=zone.id, record_type="A", name="mail",
                         content=server_ip, ttl=14400, priority=0))
    zone.serial = _bump_serial(zone.serial)
    db.commit()
    db.refresh(zone)
    try:
        _sync_zone_to_bind(zone, db)
    except Exception as e:
        logger.warning(f"No se pudo sincronizar zona tras mail A: {e}")
    return True


def _dns_add_spf_dmarc(domain_name: str, db: Session) -> bool:
    """
    Publica automáticamente SPF y DMARC en la zona DNS del panel (si existe),
    igual que ya se hace con DKIM. Sin estos registros, el correo del dominio
    puntua como sospechoso (SPF_NONE) y acaba en spam.
      - SPF:   TXT @        v=spf1 a mx ip4:<IP> ~all
      - DMARC: TXT _dmarc   v=DMARC1; p=quarantine; rua=mailto:dmarc@dominio
    Respeta registros existentes (no los pisa si el admin ya puso uno propio).
    Devuelve True si había zona en el panel.
    """
    zone = db.query(DnsZone).filter(DnsZone.domain_name == domain_name).first()
    if not zone:
        return False

    from api.routes.dns import _sync_zone_to_bind, _bump_serial
    server_ip = _domain_effective_ipv4(domain_name, db) or zone.ip_address
    changed = False

    # ── SPF (TXT en la raíz @) ──
    # ilike en cualquier posición: los TXT importados de Hestia llevan las
    # comillas DENTRO del contenido ("v=spf1 …") y con prefijo estricto no
    # casaría → añadiríamos un SPF duplicado (dos SPF = permerror).
    spf_exists = db.query(DnsRecord).filter(
        DnsRecord.zone_id == zone.id,
        DnsRecord.record_type == "TXT",
        DnsRecord.name.in_(["@", domain_name + "."]),
        DnsRecord.content.ilike("%v=spf1%"),
    ).first()
    if not spf_exists:
        ip_part = f" ip4:{server_ip}" if server_ip else ""
        spf_value = f"v=spf1 a mx{ip_part} ~all"
        db.add(DnsRecord(zone_id=zone.id, record_type="TXT", name="@",
                         content=spf_value, ttl=14400, priority=0))
        changed = True
        logger.info(f"SPF añadido a zona DNS de {domain_name}: {spf_value}")

    # ── DMARC (TXT en _dmarc) ──
    dmarc_exists = db.query(DnsRecord).filter(
        DnsRecord.zone_id == zone.id,
        DnsRecord.record_type == "TXT",
        DnsRecord.name == "_dmarc",
    ).first()
    if not dmarc_exists:
        dmarc_value = f"v=DMARC1; p=quarantine; rua=mailto:dmarc@{domain_name}; fo=1"
        db.add(DnsRecord(zone_id=zone.id, record_type="TXT", name="_dmarc",
                         content=dmarc_value, ttl=14400, priority=0))
        changed = True
        logger.info(f"DMARC añadido a zona DNS de {domain_name}")

    if changed:
        zone.serial = _bump_serial(zone.serial)
        db.commit()
        db.refresh(zone)
        try:
            _sync_zone_to_bind(zone, db)
        except Exception as e:
            logger.warning(f"No se pudo sincronizar zona tras SPF/DMARC: {e}")
    return True


def _rebuild_mail_tls(db: Session):
    """Regenera la config SNI (Dovecot+Postfix) desde la BD. Tolerante a fallos."""
    try:
        from scripts.mail_tls_manager import MailTLSManager
        all_domains = db.query(MailDomain).filter(MailDomain.is_active == True).all()  # noqa: E712
        MailTLSManager().rebuild_from_db(all_domains)
    except PermissionError:
        logger.warning("Sin permisos para configurar SNI de correo (¿entorno dev?)")
    except Exception as e:
        logger.error(f"Error configurando SNI de correo: {e}")


def _dns_set_webmail_record(domain_name: str, db: Session, present: bool) -> bool:
    """
    Añade (present=True) o quita el registro 'webmail' (CNAME → dominio) en la
    zona DNS del panel, y resincroniza (respeta cluster vía _sync_zone_to_bind).
    Devuelve True si había zona en el panel; False si el DNS es externo.
    """
    zone = db.query(DnsZone).filter(DnsZone.domain_name == domain_name).first()
    if not zone:
        return False

    from api.routes.dns import _sync_zone_to_bind, _bump_serial
    existing = db.query(DnsRecord).filter(
        DnsRecord.zone_id == zone.id,
        DnsRecord.name == "webmail",
        DnsRecord.record_type.in_(["CNAME", "A"]),
    ).first()

    if present and not existing:
        db.add(DnsRecord(zone_id=zone.id, record_type="CNAME", name="webmail",
                         content=f"{domain_name}.", ttl=14400, priority=0))
    elif not present and existing:
        db.query(DnsRecord).filter(
            DnsRecord.zone_id == zone.id, DnsRecord.name == "webmail",
            DnsRecord.record_type.in_(["CNAME", "A"]),
        ).delete()
    else:
        return True  # nada que cambiar

    zone.serial = _bump_serial(zone.serial)
    db.commit()
    db.refresh(zone)
    try:
        _sync_zone_to_bind(zone, db)
    except Exception as e:
        logger.warning(f"No se pudo sincronizar la zona tras webmail DNS: {e}")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Dominios de correo
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/mail/domains", response_model=List[MailDomainListItem])
async def list_mail_domains(
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """
    Lista los dominios de correo.
    - Admin: todos
    - Reseller: los de sus usuarios + los propios
    - Usuario: solo los suyos
    """
    query = db.query(MailDomain).order_by(MailDomain.domain_name)

    if current_user.role == "admin":
        domains = query.all()
    elif current_user.role == "reseller":
        from api.models.models_user import User
        client_ids = [
            u.id for u in db.query(User).filter(User.parent_id == current_user.id).all()
        ]
        domains = query.filter(
            MailDomain.user_id.in_(client_ids + [current_user.id])
        ).all()
    else:
        domains = query.filter(MailDomain.user_id == current_user.id).all()

    return [_mail_domain_to_dict(md, current_user) for md in domains]


@router.post("/mail/domains", response_model=MailDomainResponse,
             status_code=status.HTTP_201_CREATED)
async def create_mail_domain(
    data: MailDomainCreate,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Crea un nuevo dominio de correo y lo registra en Postfix"""
    _require_mail_enabled()

    # Verificar que el dominio no existe ya como dominio de correo
    if db.query(MailDomain).filter(
            MailDomain.domain_name == data.domain_name).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"'{data.domain_name}' ya es un dominio de correo"
        )

    # Seguridad: el dominio de correo pertenece SIEMPRE a un cliente, no al admin.
    # Admin/reseller debe elegir el propietario (igual que en dominios/BD).
    from api.utils.validators import validate_owner_assignment, OwnerAssignmentError
    owner_user = None
    if data.user_id:
        owner_user = db.query(User).filter(User.id == data.user_id).first()
    try:
        user_id = validate_owner_assignment(
            actor_role=getattr(current_user, "role", None),
            actor_id=current_user.id,
            actor_is_admin=bool(current_user.is_admin),
            requested_user_id=data.user_id,
            owner_exists=owner_user is not None,
            owner_is_admin=bool(owner_user.is_admin) if owner_user else False,
            owner_parent_id=getattr(owner_user, "parent_id", None) if owner_user else None,
            resource_label="el dominio de correo",
        )
    except OwnerAssignmentError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    md = MailDomain(
        user_id       = user_id,
        domain_id     = data.domain_id,
        domain_name   = data.domain_name,
        catch_all     = data.catch_all,
        max_mailboxes = data.max_mailboxes,
    )
    db.add(md)
    db.commit()
    db.refresh(md)

    # Registrar en Postfix
    try:
        from scripts.mail_manager import MailManager
        MailManager().create_mail_domain(data.domain_name, current_user.username)
    except PermissionError:
        logger.warning("Sin permisos root para crear dominio en Postfix (¿entorno dev?)")
    except Exception as e:
        logger.error(f"Error registrando dominio de correo en Postfix: {e}")
        # No revertimos la BD — el admin puede corregir manualmente

    # Webmail por dominio (webmail.{dominio}) — automático al activar correo:
    # registro DNS + vhost nginx que sirve el Roundcube compartido.
    _activate_webmail(data.domain_name, db)

    # SPF + DMARC automáticos en la zona DNS (si existe en el panel). Sin esto el
    # correo del dominio puntúa como sospechoso (SPF_NONE) y acaba en spam.
    try:
        _dns_add_spf_dmarc(data.domain_name, db)
    except Exception as e:
        logger.warning(f"No se pudieron añadir SPF/DMARC para {data.domain_name}: {e}")

    # Rate-limit de envío (el dominio entra con su send_limit_hour por defecto)
    _rebuild_rspamd(db)

    return _mail_domain_to_dict(md, current_user)


def _activate_webmail(domain_name: str, db: Session) -> dict:
    """Crea el registro DNS webmail + el vhost nginx. Tolerante a fallos."""
    result = {"dns": False, "vhost": False, "message": ""}
    try:
        result["dns"] = _dns_set_webmail_record(domain_name, db, present=True)
    except Exception as e:
        logger.warning(f"webmail DNS para {domain_name}: {e}")
    try:
        from scripts.webmail_manager import WebmailManager
        ok, msg = WebmailManager().enable(domain_name)
        result["vhost"] = ok
        result["message"] = msg
    except PermissionError:
        logger.warning("Sin root para crear el vhost webmail (¿entorno dev?)")
    except Exception as e:
        logger.error(f"Error creando vhost webmail para {domain_name}: {e}")
        result["message"] = str(e)
    return result


def _deactivate_webmail(domain_name: str, db: Session, destroy: bool = False) -> None:
    """Quita el vhost webmail + el registro DNS. Tolerante a fallos.

    Con destroy=False (desactivar webmail de un dominio que sigue existiendo) el
    vhost se sustituye por el placeholder 503; con destroy=True (el dominio de
    correo se borra entero) el vhost se elimina por completo — si quedara, sería
    un fichero huérfano en sites-available/enabled para siempre.
    """
    try:
        from scripts.webmail_manager import WebmailManager
        wm = WebmailManager()
        if destroy:
            wm.destroy(domain_name)
        else:
            wm.remove(domain_name)
    except PermissionError:
        pass
    except Exception as e:
        logger.warning(f"Error quitando vhost webmail de {domain_name}: {e}")
    try:
        _dns_set_webmail_record(domain_name, db, present=False)
    except Exception as e:
        logger.warning(f"webmail DNS remove para {domain_name}: {e}")


@router.get("/mail/domains/{domain_id}", response_model=MailDomainResponse)
async def get_mail_domain(
    domain_id: int,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Devuelve los detalles de un dominio de correo"""
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)
    return _mail_domain_to_dict(md, current_user)


@router.put("/mail/domains/{domain_id}", response_model=MailDomainResponse)
async def update_mail_domain(
    domain_id: int,
    data: MailDomainUpdate,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Actualiza configuración de un dominio de correo (catch-all, límites, activo)"""
    _require_mail_enabled()
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)

    old_catch_all = md.catch_all

    send_limit_changed = False
    if data.catch_all is not None:
        md.catch_all = data.catch_all or None
    if data.max_mailboxes is not None:
        md.max_mailboxes = data.max_mailboxes
    if data.is_active is not None:
        md.is_active = data.is_active
    if data.send_limit_hour is not None and data.send_limit_hour != md.send_limit_hour:
        md.send_limit_hour = data.send_limit_hour
        send_limit_changed = True

    db.commit()
    db.refresh(md)

    # Sincronizar catch-all en Postfix
    if data.catch_all is not None and data.catch_all != old_catch_all:
        try:
            from scripts.mail_manager import MailManager
            mgr = MailManager()
            if md.catch_all:
                mgr.set_catch_all(md.domain_name, md.catch_all)
            else:
                mgr.remove_catch_all(md.domain_name)
        except Exception as e:
            logger.warning(f"Error actualizando catch-all en Postfix: {e}")

    # Aplicar el nuevo límite de envío del dominio en Rspamd
    if send_limit_changed:
        _rebuild_rspamd(db)

    return _mail_domain_to_dict(md, current_user)


@router.delete("/mail/domains/{domain_id}",
               status_code=status.HTTP_204_NO_CONTENT)
async def delete_mail_domain(
    domain_id: int,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """
    Elimina un dominio de correo y TODOS sus datos:
    buzones, alias, claves DKIM y los Maildir del disco.
    """
    _require_mail_enabled()
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)

    domain_name    = md.domain_name
    panel_username = md.user.username if md.user else current_user.username
    dkim_selector  = md.dkim_selector

    # Eliminar registros DNS DKIM si existen
    if md.dkim_enabled:
        _dns_remove_dkim_record(domain_name, dkim_selector, db)

    # Quitar el webmail por dominio (vhost + DNS) antes de borrar la zona/datos.
    # destroy=True: se borra el dominio de correo entero, así que el vhost debe
    # desaparecer del todo (no dejar el placeholder 503, que quedaría huérfano).
    _deactivate_webmail(domain_name, db, destroy=True)

    # Eliminar de la BD (cascade elimina mailboxes y aliases)
    db.delete(md)
    db.commit()

    # Limpiar Postfix + Dovecot + disco
    try:
        from scripts.mail_manager import MailManager
        MailManager().delete_mail_domain(domain_name, panel_username)
    except PermissionError:
        logger.warning("Sin permisos root para limpiar dominio de correo (¿entorno dev?)")
    except Exception as e:
        logger.error(f"Error eliminando dominio de correo del sistema: {e}")

    # Eliminar clave DKIM
    try:
        from scripts.dkim_manager import DkimManager
        DkimManager().remove_key(domain_name, dkim_selector)
    except Exception as e:
        logger.warning(f"No se pudo eliminar clave DKIM: {e}")

    # Regenerar Rspamd (el dominio y sus buzones salen de los mapas/listas)
    try:
        from scripts.rspamd_manager import RspamdManager
        RspamdManager().remove_domain(domain_name)
    except Exception:
        pass
    _rebuild_rspamd(db)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Webmail por dominio (webmail.{dominio})
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/mail/domains/{domain_id}/webmail")
async def get_webmail_status(
    domain_id: int,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Estado del webmail por dominio: vhost activo, SSL, DNS, URL."""
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)

    from scripts.webmail_manager import (
        WebmailManager, webmail_host, cert_includes_webmail,
    )
    host = webmail_host(md.domain_name)
    enabled = ssl = roundcube_ok = False
    try:
        enabled = WebmailManager().is_enabled(md.domain_name)
        ssl = cert_includes_webmail(md.domain_name)
    except Exception:
        pass
    roundcube_ok = os.path.exists("/var/www/webmail")

    # ¿La zona DNS está en el panel? (para saber si el registro webmail es nuestro)
    zone = db.query(DnsZone).filter(DnsZone.domain_name == md.domain_name).first()
    dns_managed = zone is not None

    return {
        "domain": md.domain_name,
        "host": host,
        "enabled": enabled,
        "ssl": ssl,
        "url": f"https://{host}" if ssl else f"http://{host}",
        "roundcube_installed": roundcube_ok,
        "dns_managed": dns_managed,
    }


@router.post("/mail/domains/{domain_id}/webmail")
async def set_webmail(
    domain_id: int,
    enabled: bool = True,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Activa o desactiva el webmail.{dominio} (vhost nginx + registro DNS)."""
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)

    if enabled:
        res = _activate_webmail(md.domain_name, db)
        if not res["vhost"] and res.get("message"):
            raise HTTPException(status_code=409, detail=res["message"])
        return {"status": "success", "enabled": True, **res}
    else:
        _deactivate_webmail(md.domain_name, db)
        return {"status": "success", "enabled": False}


def _domain_ipv4_ipv6(md, db):
    """IPv4/IPv6 del dominio web vinculado al MailDomain (o del servidor)."""
    from api.models.models_domain import Domain
    ipv4 = ipv6 = None
    dom = None
    if getattr(md, "domain_id", None):
        dom = db.query(Domain).filter(Domain.id == md.domain_id).first()
    if not dom:
        dom = db.query(Domain).filter(Domain.domain_name == md.domain_name).first()
    if dom:
        ipv4 = dom.ipv4
        ipv6 = dom.ipv6
    # Fallback IPv4: la del servidor
    if not ipv4:
        try:
            from api.routes.dns import _get_server_ipv4
            ipv4 = _get_server_ipv4(db)
        except Exception:
            ipv4 = None
    return ipv4, ipv6


def _apply_domain_sender_ip(md, db):
    """Aplica en Postfix la IP de salida del dominio según mail_out_ip_pref.

    - pref ipv6 y el dominio tiene IPv6 → transporte con bind v4+v6, prefiere v6.
    - pref ipv4 (o sin IPv6) → transporte que fuerza IPv4.
    No revienta si Postfix no está disponible (entorno dev)."""
    try:
        from scripts.mail_manager import MailManager
        mm = MailManager()
        if not mm.mail_available():
            return
        ipv4, ipv6 = _domain_ipv4_ipv6(md, db)
        if not ipv4:
            return
        pref = getattr(md, "mail_out_ip_pref", "ipv4") or "ipv4"
        mm.set_domain_sender_ip(md.domain_name, ipv4, ipv6 or "", pref)
    except Exception as e:
        logger.warning(f"_apply_domain_sender_ip {md.domain_name}: {e}")


@router.get("/mail/domains/{domain_id}/out-ip")
async def get_mail_out_ip(domain_id: int, current_user=Depends(require_auth),
                          db: Session = Depends(get_db)):
    """Preferencia de IP de salida SMTP del dominio + si tiene IPv6 disponible."""
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)
    ipv4, ipv6 = _domain_ipv4_ipv6(md, db)
    server = _server_out_ips()   # por dónde sale realmente en modo Predeterminada
    return {
        "domain": md.domain_name,
        "pref": getattr(md, "mail_out_ip_pref", "ipv4") or "ipv4",
        "ipv4": ipv4,            # IPv4 del dominio (informativo)
        "ipv6": ipv6,            # IPv6 dedicada del dominio (para el opt-in)
        "ipv6_available": bool(ipv6),
        # IPs GLOBALES por las que sale el correo en modo "Predeterminada".
        "server_ipv4": server["ipv4"],
        "server_ipv6": server["ipv6"],
    }


def _server_out_ips() -> dict:
    """IPs de salida GLOBALES del servidor (por las que sale el correo en modo
    'Predeterminada'): smtp_bind_address / smtp_bind_address6 de Postfix. Estas
    ya tienen PTR/SPF/DKIM correctos. Best-effort; '' si no se puede leer."""
    import subprocess
    out = {"ipv4": "", "ipv6": ""}
    try:
        r = subprocess.run(["postconf", "-h", "smtp_bind_address", "smtp_bind_address6"],
                           capture_output=True, text=True, timeout=5)
        vals = [l.strip() for l in (r.stdout or "").splitlines()]
        if len(vals) >= 1:
            out["ipv4"] = vals[0]
        if len(vals) >= 2:
            out["ipv6"] = vals[1]
    except Exception:
        pass
    return out


def _sync_spf_out_ip6(md, domain_ipv6: str, pref: str, db) -> bool:
    """Pone en el SPF de la zona la IPv6 por la que SALE el correo del dominio:
    la dedicada si pref=ipv6 (y la tiene), o la GLOBAL del servidor en caso
    contrario. apply_ip6_to_spf deja una única ip6 (corrige la equivocada). No-op
    si el panel no gestiona la zona. Devuelve True si cambió algo."""
    from api.routes.dns import (apply_ip6_to_spf, _get_server_ipv6, _bump_serial,
                                _sync_zone_to_bind)
    from api.models.models_dns import DnsZone, DnsRecord
    server_ipv6 = _get_server_ipv6(db)
    ip6 = domain_ipv6 if (pref == "ipv6" and domain_ipv6) else server_ipv6
    if not ip6:
        return False
    zone = db.query(DnsZone).filter(DnsZone.domain_name == md.domain_name).first()
    if not zone:
        return False  # DNS externo
    rec = (db.query(DnsRecord)
           .filter(DnsRecord.zone_id == zone.id, DnsRecord.record_type == "TXT",
                   DnsRecord.name == "@")
           .filter(DnsRecord.content.like("%v=spf1%")).first())
    if not rec:
        return False
    # Los TXT importados de Hestia llevan las comillas DENTRO del contenido
    # ("v=spf1 …") → normalizar antes de operar (apply_ip6_to_spf espera el
    # valor limpio) y guardar ya sin comillas (el render las añade al servir).
    contenido = (rec.content or "").strip()
    if contenido.startswith('"') and contenido.endswith('"'):
        contenido = contenido[1:-1]
    nuevo = apply_ip6_to_spf(contenido, ip6)
    if nuevo == rec.content:
        return False
    rec.content = nuevo
    zone.serial = _bump_serial(zone.serial)
    db.commit()
    try:
        _sync_zone_to_bind(zone, db)
    except Exception:
        pass
    return True


def _ipv6_has_ptr(ipv6: str) -> str:
    """Devuelve el hostname del PTR de una IPv6, o '' si no tiene. Best-effort
    (dig); no revienta si no está disponible."""
    import subprocess
    try:
        r = subprocess.run(["dig", "+short", "-x", ipv6, "@1.1.1.1"],
                           capture_output=True, text=True, timeout=6)
        return (r.stdout or "").strip().splitlines()[0].rstrip(".") if r.stdout.strip() else ""
    except Exception:
        return ""


class MailOutIpRequest(_BM):
    pref: str = _F("ipv4", pattern="^(ipv4|ipv6)$")


@router.post("/mail/domains/{domain_id}/out-ip")
async def set_mail_out_ip(domain_id: int, data: MailOutIpRequest,
                          current_user=Depends(require_auth),
                          db: Session = Depends(get_db)):
    """Cambia la preferencia de IP de salida SMTP del dominio (ipv4/ipv6).

    Elegir ipv6 requiere que el dominio tenga IPv6 asignada; la entregabilidad
    (rDNS de la IPv6) es responsabilidad del cliente/proveedor."""
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)

    ipv4, ipv6 = _domain_ipv4_ipv6(md, db)
    if data.pref == "ipv6" and not ipv6:
        raise HTTPException(status_code=409,
            detail="El dominio no tiene IPv6 asignada. Actívala antes de enviar correo por IPv6.")

    md.mail_out_ip_pref = data.pref
    db.commit()
    db.refresh(md)
    _apply_domain_sender_ip(md, db)

    # El SPF debe declarar la IPv6 por la que SALE el correo: la dedicada si
    # pref=ipv6, la global del servidor en caso contrario. Sin esto, cambiar el
    # pref dejaría el SPF apuntando a la IPv6 equivocada → SPF fail.
    try:
        _sync_spf_out_ip6(md, ipv6, data.pref, db)
    except Exception as e:
        logger.warning(f"_sync_spf_out_ip6 {md.domain_name}: {e}")

    # Al elegir IPv6, verificamos EN VIVO si esa IPv6 ya tiene PTR (rDNS). Si no,
    # avisamos claramente: el cliente/proveedor debe configurarlo o Gmail/Outlook
    # rechazan el correo (550 5.7.25). El envío global (por defecto) usa la IP del
    # servidor, que sí tiene PTR — por eso ipv6 dedicada es opt-in consciente.
    warning = None
    if data.pref == "ipv6" and ipv6:
        has_ptr = _ipv6_has_ptr(ipv6)
        if has_ptr:
            warning = f"La IPv6 {ipv6} ya tiene PTR ({has_ptr}); envío por IPv6 activado."
        else:
            warning = (f"⚠ La IPv6 {ipv6} NO tiene PTR (rDNS). Debes configurar el "
                       "registro inverso con tu proveedor o Gmail/Outlook rechazarán "
                       "el correo (550 5.7.25). Mientras tanto, considera volver a IPv4.")
    return {"status": "success", "pref": md.mail_out_ip_pref, "warning": warning}


@router.post("/mail/domains/{domain_id}/webmail/ssl")
async def issue_webmail_ssl(
    domain_id: int,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """
    Emite/expande el certificado del dominio para incluir webmail.{dominio} y
    regenera el vhost webmail con HTTPS. Requiere que webmail.{dominio} resuelva
    (DNS) hacia este servidor para que pase la validación ACME.
    """
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)

    # Email del admin para Let's Encrypt
    email = getattr(current_user, "email", None) or "admin@" + md.domain_name

    try:
        from scripts.ssl_manager import SSLManager
        SSLManager().expand_for_webmail(md.domain_name, email)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Se necesitan privilegios root")
    except Exception as e:
        raise HTTPException(status_code=502,
                            detail=f"No se pudo emitir el certificado de webmail.{md.domain_name}: {e}. "
                                   f"Comprueba que webmail.{md.domain_name} apunta a este servidor.")

    # Regenerar el vhost webmail ahora con SSL
    try:
        from scripts.webmail_manager import WebmailManager
        ok, msg = WebmailManager().enable(md.domain_name, ssl=True)
        return {"status": "success", "ssl": True, "message": msg}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# SMTP relay propio del dominio (override del relay global)
# ─────────────────────────────────────────────────────────────────────────────


class DomainRelayRequest(_BM):
    enabled:  bool = True
    host:     str = _F("", max_length=255)
    port:     int = _F(587, ge=1, le=65535)
    username: str = _F("", max_length=255)
    password: str = _F("", max_length=255)


@router.get("/mail/domains/{domain_id}/relay")
async def get_domain_relay(domain_id: int, current_user=Depends(require_auth),
                           db: Session = Depends(get_db)):
    """Relay SMTP propio del dominio (override del global). Sin la contraseña."""
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)
    # ¿Hay relay global activo? (para informar de qué se usa si no hay override)
    from api.models.models_settings import Settings
    s = db.query(Settings).filter(Settings.id == 1).first()
    return {
        "domain":   md.domain_name,
        "enabled":  bool(getattr(md, "relay_enabled", False)),
        "host":     getattr(md, "relay_host", None) or "",
        "port":     getattr(md, "relay_port", None) or 587,
        "username": getattr(md, "relay_username", None) or "",
        "global_relay_active": bool(s and s.relay_enabled),
        "global_relay_host": (s.relay_host if s and s.relay_enabled else None),
    }


@router.post("/mail/domains/{domain_id}/relay")
async def set_domain_relay(domain_id: int, data: DomainRelayRequest,
                           current_user=Depends(require_auth),
                           db: Session = Depends(get_db)):
    """Configura o quita el relay SMTP propio de este dominio."""
    _require_mail_enabled()
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)
    from scripts.mail_manager import MailManager

    if not data.enabled:
        md.relay_enabled = False
        db.commit()
        try:
            MailManager().remove_domain_relay(md.domain_name)
        except PermissionError:
            raise HTTPException(403, "Se necesitan privilegios root")
        except Exception as e:
            raise HTTPException(502, f"Error quitando el relay del dominio: {e}")
        return {"status": "success", "enabled": False}

    if not data.host:
        raise HTTPException(400, "Indica el host del relay")

    md.relay_enabled  = True
    md.relay_host     = data.host.strip()
    md.relay_port     = data.port
    md.relay_username = data.username.strip() or None
    db.commit()

    try:
        MailManager().set_domain_relay(md.domain_name, data.host, data.port,
                                       data.username, data.password)
    except PermissionError:
        raise HTTPException(403, "Se necesitan privilegios root")
    except Exception as e:
        raise HTTPException(502, f"Error configurando el relay del dominio: {e}")

    return {"status": "success", "enabled": True, "host": data.host, "port": data.port}


# ─────────────────────────────────────────────────────────────────────────────
# TLS por dominio de correo (SNI: mail.{dominio} con su propio certificado)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/mail/domains/{domain_id}/tls")
async def get_mail_tls(domain_id: int, current_user=Depends(require_auth),
                       db: Session = Depends(get_db)):
    """Estado del TLS propio del dominio: activo, cert válido, DNS, host."""
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)
    from scripts.mail_tls_manager import mail_host, cert_includes_mail
    zone = db.query(DnsZone).filter(DnsZone.domain_name == md.domain_name).first()
    return {
        "domain": md.domain_name,
        "host": mail_host(md.domain_name),
        "enabled": bool(getattr(md, "mail_tls_enabled", False)),
        "cert_valid": cert_includes_mail(md.domain_name),
        "dns_managed": zone is not None,
    }


@router.post("/mail/domains/{domain_id}/tls")
async def set_mail_tls(domain_id: int, enabled: bool = True,
                       current_user=Depends(require_auth),
                       db: Session = Depends(get_db)):
    """
    Activa/desactiva el TLS propio del dominio (cert para mail.{dominio} vía SNI).
    Al activar: asegura el registro DNS 'mail', emite/expande el cert con
    mail.{dominio} y regenera la config SNI de Dovecot+Postfix.
    """
    _require_mail_enabled()
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)

    if not enabled:
        md.mail_tls_enabled = False
        db.commit()
        _rebuild_mail_tls(db)
        return {"status": "success", "enabled": False}

    # 1) DNS mail.{dominio} → IP (si la zona está en el panel)
    _dns_ensure_mail_record(md.domain_name, db)

    # 2) Emitir/expandir el cert del dominio para incluir mail.{dominio}
    email = getattr(current_user, "email", None) or f"admin@{md.domain_name}"
    try:
        from scripts.ssl_manager import SSLManager
        SSLManager().expand_for_mail(md.domain_name, email)
    except PermissionError:
        raise HTTPException(403, "Se necesitan privilegios root")
    except Exception as e:
        raise HTTPException(
            502,
            f"No se pudo emitir el certificado de mail.{md.domain_name}: {e}. "
            f"Comprueba que mail.{md.domain_name} apunta a este servidor.")

    # 3) Activar y regenerar SNI
    md.mail_tls_enabled = True
    db.commit()
    _rebuild_mail_tls(db)

    from scripts.mail_tls_manager import cert_includes_mail
    return {
        "status": "success", "enabled": True,
        "cert_valid": cert_includes_mail(md.domain_name),
        "message": f"TLS activado: los clientes ya pueden usar mail.{md.domain_name} "
                   f"con certificado válido.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Antivirus ClamAV por dominio
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/mail/domains/{domain_id}/antivirus")
async def get_mail_antivirus(domain_id: int, current_user=Depends(require_auth),
                             db: Session = Depends(get_db)):
    """Estado del antivirus del dominio + método del servidor.

    `method`: 'rspamd' (control por dominio), 'milter' (global, este toggle no
    aplica) o 'none' (ClamAV no disponible). La UI usa esto para mostrar el
    switch por dominio o remitir al interruptor global.
    """
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)
    method = "none"
    try:
        from scripts import antivirus_manager as av
        method = av.detect_method()
    except Exception:
        method = "none"
    return {
        "domain": md.domain_name,
        "enabled": bool(getattr(md, "antivirus_enabled", False)),
        "available": method != "none",
        "method": method,
        "per_domain": method == "rspamd",
    }


@router.post("/mail/domains/{domain_id}/antivirus")
async def set_mail_antivirus(domain_id: int, enabled: bool = True,
                             current_user=Depends(require_auth),
                             db: Session = Depends(get_db)):
    """Activa/desactiva el antivirus (rechazo de correo con virus) del dominio."""
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)

    if enabled:
        try:
            from scripts.rspamd_manager import RspamdManager
            if not RspamdManager().clamav_available():
                raise HTTPException(status_code=422, detail=(
                    "ClamAV no está disponible en el servidor. Instálalo/arráncalo "
                    "(clamav-daemon) antes de activar el antivirus."))
        except HTTPException:
            raise
        except Exception:
            pass

    md.antivirus_enabled = bool(enabled)
    db.commit()
    db.refresh(md)
    _rebuild_rspamd(db)
    return {"status": "success", "domain": md.domain_name,
            "enabled": md.antivirus_enabled}


@router.get("/mail/domains/{domain_id}/greylist")
async def get_mail_greylist(domain_id: int, current_user=Depends(require_auth),
                            db: Session = Depends(get_db)):
    """Estado del greylisting del dominio + si está activo a nivel de servidor."""
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)
    # ¿Está el greylisting activo a nivel global?
    from api.models.models_settings import Settings
    s = db.query(Settings).filter(Settings.id == 1).first()
    global_on = bool(getattr(s, "greylisting_enabled", True)) if s else True
    return {
        "domain": md.domain_name,
        "enabled": bool(getattr(md, "greylist_enabled", True)),
        "global_enabled": global_on,
    }


@router.post("/mail/domains/{domain_id}/greylist")
async def set_mail_greylist(domain_id: int, enabled: bool = True,
                            current_user=Depends(require_auth),
                            db: Session = Depends(get_db)):
    """Activa/desactiva el greylisting (retraso anti-spam) SOLO de este dominio.

    Desactivarlo = entrega inmediata (sin retraso); el resto del filtrado
    anti-spam (marcar/rechazar) NO cambia. Solo tiene efecto si el greylisting
    está activo a nivel de servidor."""
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)
    md.greylist_enabled = bool(enabled)
    db.commit()
    db.refresh(md)
    _rebuild_rspamd(db)
    return {"status": "success", "domain": md.domain_name,
            "enabled": md.greylist_enabled}


@router.get("/mail/greylisting")
async def get_global_greylisting(current_user=Depends(require_admin),
                                 db: Session = Depends(get_db)):
    """[Admin] Estado del greylisting global del servidor."""
    from api.models.models_settings import Settings
    s = db.query(Settings).filter(Settings.id == 1).first()
    return {"enabled": bool(getattr(s, "greylisting_enabled", True)) if s else True}


@router.put("/mail/greylisting")
async def set_global_greylisting(enabled: bool = True,
                                 current_user=Depends(require_admin),
                                 db: Session = Depends(get_db)):
    """[Admin] Activa/desactiva el greylisting para TODO el servidor.

    Si se desactiva, ningún dominio hace greylisting (entrega inmediata para
    todos). Si se activa, cada dominio puede excluirse individualmente."""
    from api.models.models_settings import Settings
    s = db.query(Settings).filter(Settings.id == 1).first()
    if not s:
        s = Settings(id=1)
        db.add(s)
    s.greylisting_enabled = bool(enabled)
    db.commit()
    try:
        from scripts.rspamd_manager import RspamdManager
        RspamdManager().set_global_greylisting(bool(enabled))
    except Exception as e:
        raise HTTPException(status_code=500,
            detail=f"Guardado en BD pero falló aplicar en Rspamd: {e}")
    return {"status": "success", "enabled": bool(enabled)}


# ─── Tamaño máximo de mensaje (global) ────────────────────────────────────────

@router.get("/mail/message-size-limit")
async def get_message_size_limit(current_user=Depends(require_admin)):
    """[Admin] Tope de tamaño por mensaje del servidor (message_size_limit)."""
    from scripts.mail_manager import MailManager
    res = MailManager().get_message_size_limit()
    if not res.get("success"):
        raise HTTPException(status_code=400,
            detail="Postfix no está instalado en este servidor.")
    return {
        "mb": res["mb"],
        "bytes": res["bytes"],
        "default_mb": MailManager.DEFAULT_MESSAGE_SIZE_MB,
        "max_mb": MailManager.MAX_MESSAGE_SIZE_MB,
    }


@router.put("/mail/message-size-limit")
async def set_message_size_limit(mb: int, current_user=Depends(require_admin)):
    """[Admin] Fija el tope de tamaño por mensaje (en MB) para TODO el servidor.

    Afecta a lo que aceptan tanto la recepción (MX) como el envío. Postfix se
    recarga al aplicar. Rango permitido: 1..MAX_MESSAGE_SIZE_MB MB.
    """
    from scripts.mail_manager import MailManager
    res = MailManager().set_message_size_limit(mb)
    if not res.get("success"):
        reason = res.get("reason", "")
        if reason == "postfix_not_installed":
            raise HTTPException(status_code=400,
                detail="Postfix no está instalado en este servidor.")
        if reason == "out_of_range":
            raise HTTPException(status_code=422,
                detail=f"El valor debe estar entre 1 y {res.get('max_mb')} MB.")
        raise HTTPException(status_code=422, detail="Valor de tamaño no válido.")
    return {"status": "success", "mb": res["mb"], "bytes": res["bytes"]}


# ─── Mover spam a Junk (global + por dominio) ─────────────────────────────────

@router.get("/mail/domains/{domain_id}/spam-to-junk")
async def get_mail_spam_to_junk(domain_id: int, current_user=Depends(require_auth),
                                db: Session = Depends(get_db)):
    """Estado de 'mover spam a Junk' del dominio + si está activo globalmente."""
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)
    from api.models.models_settings import Settings
    s = db.query(Settings).filter(Settings.id == 1).first()
    global_on = bool(getattr(s, "spam_to_junk_enabled", True)) if s else True
    return {
        "domain": md.domain_name,
        "enabled": bool(getattr(md, "spam_to_junk_enabled", True)),
        "global_enabled": global_on,
    }


@router.post("/mail/domains/{domain_id}/spam-to-junk")
async def set_mail_spam_to_junk(domain_id: int, enabled: bool = True,
                                current_user=Depends(require_auth),
                                db: Session = Depends(get_db)):
    """Activa/desactiva el envío de spam a la carpeta Junk SOLO de este dominio.

    Desactivarlo = el dominio NO clasifica spam a Junk (Rspamd deja de marcar
    X-Spam); el rechazo de spam claro se mantiene. Solo tiene efecto si está
    activo a nivel de servidor."""
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)
    md.spam_to_junk_enabled = bool(enabled)
    db.commit()
    db.refresh(md)
    _rebuild_rspamd(db)
    return {"status": "success", "domain": md.domain_name,
            "enabled": md.spam_to_junk_enabled}


@router.get("/mail/spam-to-junk")
async def get_global_spam_to_junk(current_user=Depends(require_admin),
                                  db: Session = Depends(get_db)):
    """[Admin] Estado global de 'mover spam a Junk'."""
    from api.models.models_settings import Settings
    s = db.query(Settings).filter(Settings.id == 1).first()
    return {"enabled": bool(getattr(s, "spam_to_junk_enabled", True)) if s else True}


@router.put("/mail/spam-to-junk")
async def set_global_spam_to_junk(enabled: bool = True,
                                  current_user=Depends(require_admin),
                                  db: Session = Depends(get_db)):
    """[Admin] Activa/desactiva mover el spam a la carpeta Junk para TODO el
    servidor. Instala/actualiza el Sieve global de Dovecot."""
    from api.models.models_settings import Settings
    s = db.query(Settings).filter(Settings.id == 1).first()
    if not s:
        s = Settings(id=1)
        db.add(s)
    s.spam_to_junk_enabled = bool(enabled)
    db.commit()
    try:
        from scripts import dovecot_spam_sieve
        dovecot_spam_sieve.apply(bool(enabled))
    except Exception as e:
        raise HTTPException(status_code=500,
            detail=f"Guardado en BD pero falló aplicar en Dovecot: {e}")
    return {"status": "success", "enabled": bool(enabled)}


# ─────────────────────────────────────────────────────────────────────────────
# Antivirus — estado global del servidor, firmas y modo milter (admin)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/mail/antivirus/status")
async def antivirus_status(current_user=Depends(require_auth)):
    """Estado global del antivirus del servidor: método, firmas y, en modo
    milter, si el escaneo global está activo."""
    from scripts import antivirus_manager as av
    method = av.detect_method()
    out = {
        "method": method,                 # rspamd | milter | none
        "available": method != "none",
        "ssse3": av.cpu_has_ssse3(),
        "signatures": av.signatures_status(),
    }
    if method == "milter":
        out["milter_enabled"] = av.milter_enabled()
    return out


@router.post("/mail/antivirus/update-signatures")
async def antivirus_update_signatures(current_user=Depends(require_admin)):
    """Fuerza una actualización de las firmas de virus (botón 'Actualizar ahora').
    Solo admin."""
    from scripts import antivirus_manager as av
    if not av.clamav_available():
        raise HTTPException(status_code=422,
                            detail="ClamAV no está disponible en el servidor.")
    res = av.update_signatures()
    if not res.get("ok"):
        # No abortamos con 500: devolvemos el mensaje (p. ej. 'up-to-date' o error)
        return {"status": "warning", **res}
    return {"status": "success", **res}


@router.post("/mail/antivirus/milter")
async def antivirus_set_milter(enabled: bool = True,
                               current_user=Depends(require_admin)):
    """Activa/desactiva el antivirus GLOBAL vía clamav-milter. Solo aplica en
    servidores en modo 'milter' (sin SSSE3). Solo admin."""
    from scripts import antivirus_manager as av
    if av.detect_method() == "none":
        raise HTTPException(status_code=422,
                            detail="ClamAV no está disponible en el servidor.")
    try:
        if enabled:
            av.enable_milter()
        else:
            av.disable_milter()
    except Exception as e:
        raise HTTPException(status_code=500,
                            detail=f"Error configurando clamav-milter: {e}")
    return {"status": "success", "enabled": av.milter_enabled()}


@router.post("/mail/domains/{domain_id}/dns-fix")
async def fix_mail_dns(
    domain_id: int,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """
    Publica/repara SPF y DMARC en la zona DNS del dominio de correo. Útil para
    dominios creados antes de que esto fuera automático, o si faltan registros.
    """
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)
    had_zone = _dns_add_spf_dmarc(md.domain_name, db)
    if not had_zone:
        return {"status": "no_zone",
                "message": "Este dominio no tiene su DNS en el panel; añade SPF/DMARC en tu proveedor."}
    return {"status": "ok",
            "message": "SPF y DMARC publicados en la zona DNS. Pueden tardar unos minutos en propagarse."}


# ─────────────────────────────────────────────────────────────────────────────
# DKIM
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/mail/domains/{domain_id}/dkim", response_model=DkimResponse)
async def generate_dkim(
    domain_id: int,
    data: DkimGenerateRequest = DkimGenerateRequest(),
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """
    Genera (o rota) la clave DKIM para el dominio.
    Si existe zona DNS en SVQPanel, añade el TXT record automáticamente.
    """
    _require_mail_enabled()
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)

    try:
        from scripts.dkim_manager import DkimManager
        result = DkimManager().generate_key(md.domain_name, data.selector)
    except PermissionError:
        raise HTTPException(403, "Se necesitan permisos de root para generar claves DKIM")
    except Exception as e:
        raise HTTPException(500, f"Error generando clave DKIM: {e}")

    # Actualizar BD
    md.dkim_enabled    = True
    md.dkim_selector   = data.selector
    md.dkim_public_key = result["public_key_b64"]
    db.commit()

    # Añadir automáticamente a la zona DNS de SVQPanel si existe
    dns_added = _dns_add_dkim_record(
        md.domain_name, data.selector, result["dns_record_value"], db
    )

    msg = "Clave DKIM generada correctamente"
    if dns_added:
        msg += ". Registro TXT añadido automáticamente a la zona DNS."
    else:
        msg += (f". Añade manualmente este TXT a tu DNS: "
                f"{result['dns_record_name']}  →  {result['dns_record_value'][:40]}...")

    return DkimResponse(
        enabled          = True,
        selector         = data.selector,
        dns_record_name  = result["dns_record_name"],
        dns_record_value = result["dns_record_value"],
        public_key_pem   = result["public_key_pem"],
        dns_auto_added   = dns_added,
        message          = msg,
    )


@router.delete("/mail/domains/{domain_id}/dkim",
               status_code=status.HTTP_204_NO_CONTENT)
async def remove_dkim(
    domain_id: int,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Elimina la clave DKIM del dominio"""
    _require_mail_enabled()
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)

    _dns_remove_dkim_record(md.domain_name, md.dkim_selector, db)

    try:
        from scripts.dkim_manager import DkimManager
        DkimManager().remove_key(md.domain_name, md.dkim_selector)
    except Exception as e:
        logger.warning(f"No se pudo eliminar clave DKIM del disco: {e}")

    md.dkim_enabled    = False
    md.dkim_public_key = None
    db.commit()

    return None


@router.get("/mail/domains/{domain_id}/dkim", response_model=DkimResponse)
async def get_dkim_info(
    domain_id: int,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Devuelve el estado y el registro DNS de la clave DKIM del dominio"""
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)

    if not md.dkim_enabled or not md.dkim_public_key:
        return DkimResponse(enabled=False, selector=md.dkim_selector or "mail",
                            message="DKIM no configurado para este dominio")

    dns_name  = f"{md.dkim_selector}._domainkey.{md.domain_name}"
    dns_value = f"v=DKIM1; k=rsa; p={md.dkim_public_key}"

    return DkimResponse(
        enabled          = True,
        selector         = md.dkim_selector,
        dns_record_name  = dns_name,
        dns_record_value = dns_value,
        public_key_pem   = None,   # no almacenamos la clave privada en BD
        message          = "DKIM activo",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Buzones
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/mail/domains/{domain_id}/mailboxes",
            response_model=List[MailboxResponse])
async def list_mailboxes(
    domain_id: int,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Lista los buzones de un dominio de correo, con el espacio ocupado real."""
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)

    # Calcular el uso real de cada buzón (doveadm quota get; rápido). Si falla
    # (entorno sin permisos/dev), devolvemos 0.0 sin romper el listado.
    panel_username = md.user.username if md.user else current_user.username
    usage = {}
    try:
        from scripts.mail_manager import MailManager
        mgr = MailManager()
        for mb in md.mailboxes:
            try:
                usage[mb.id] = mgr.get_mailbox_usage(
                    panel_username, md.domain_name, mb.username)
            except Exception:
                usage[mb.id] = 0.0
    except Exception:
        pass

    return [_mailbox_to_dict(mb, usage.get(mb.id, 0.0)) for mb in md.mailboxes]


@router.get("/mail/domains/{domain_id}/send-usage")
async def mailboxes_send_usage(
    domain_id: int,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Correos enviados por cada buzón del dominio en los últimos 60 min.

    Se calcula bajo demanda (lee el mail.log) para no penalizar el listado. Cada
    item: {mailbox_id, full_email, sent_last_hour, send_limit_hour, pct}.
    """
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)

    emails = [f"{mb.username}@{md.domain_name}" for mb in md.mailboxes]
    sent = {}
    try:
        from scripts.mail_stats import sent_last_hour
        sent = sent_last_hour(emails)
    except Exception:
        sent = {}

    out = []
    for mb in md.mailboxes:
        email = f"{mb.username}@{md.domain_name}"
        n = int(sent.get(email.lower(), 0))
        limit = int(getattr(mb, "send_limit_hour", 0) or 0)
        pct = round(n / limit * 100) if limit > 0 else 0
        out.append({
            "mailbox_id": mb.id,
            "full_email": email,
            "sent_last_hour": n,
            "send_limit_hour": limit,
            "pct": pct,
        })
    return {"status": "success", "data": out}


@router.post("/mail/domains/{domain_id}/mailboxes",
             response_model=MailboxResponse,
             status_code=status.HTTP_201_CREATED)
async def create_mailbox(
    domain_id: int,
    data: MailboxCreate,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Crea un nuevo buzón de correo"""
    _require_mail_enabled()
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)

    # Política de contraseñas del panel
    from scripts.password_policy import enforce_or_400
    enforce_or_400(data.password, db)

    # Comprobar límite de buzones por dominio de correo
    if md.max_mailboxes > 0:
        current_count = db.query(Mailbox).filter(
            Mailbox.mail_domain_id == md.id
        ).count()
        if current_count >= md.max_mailboxes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Límite de {md.max_mailboxes} buzones alcanzado en este dominio"
            )

    # Comprobar límite de buzones del PLAN (total del usuario, todos sus dominios)
    owner = md.user
    if owner and owner.mailboxes_limit and owner.mailboxes_limit > 0:
        total_mailboxes = (
            db.query(Mailbox)
            .join(MailDomain, Mailbox.mail_domain_id == MailDomain.id)
            .filter(MailDomain.user_id == owner.id)
            .count()
        )
        if total_mailboxes >= owner.mailboxes_limit:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Límite de buzones del plan alcanzado "
                    f"({total_mailboxes}/{owner.mailboxes_limit})."
                ),
            )

    # Comprobar que el buzón no existe ya
    existing = db.query(Mailbox).filter(
        Mailbox.mail_domain_id == md.id,
        Mailbox.username == data.username,
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El buzón '{data.username}@{md.domain_name}' ya existe"
        )

    # Crear en el sistema (genera hash + Maildir + Postfix + Dovecot)
    panel_username = md.user.username if md.user else current_user.username
    pwd_hash = ""
    try:
        from scripts.mail_manager import MailManager
        mgr = MailManager()
        pwd_hash = mgr.hash_password(data.password)
        mgr.create_mailbox(
            panel_username, md.domain_name,
            data.username, data.password, data.quota_mb
        )
    except PermissionError:
        logger.warning("Sin permisos root para crear buzón (¿entorno dev?)")
        # Generar hash de todas formas para no dejar BD vacía
        try:
            from scripts.mail_manager import MailManager
            pwd_hash = MailManager().hash_password(data.password)
        except Exception:
            pwd_hash = f"{{PLAIN}}{data.password}"  # fallback solo en dev
    except Exception as e:
        raise HTTPException(500, f"Error creando buzón en el sistema: {e}")

    # Cifrar la contraseña en claro para autologin webmail (Roundcube)
    try:
        enc_pwd = _encrypt_password(data.password)
    except Exception:
        enc_pwd = None

    # Crear en la BD
    mb = Mailbox(
        mail_domain_id     = md.id,
        username           = data.username,
        password_hash      = pwd_hash,
        encrypted_password = enc_pwd,
        quota_mb           = data.quota_mb,
        send_limit_hour    = getattr(data, "send_limit_hour", 200),
    )
    db.add(mb)
    db.commit()
    db.refresh(mb)

    # Actualizar el rate-limit de Rspamd (nuevo buzón en el mapa)
    _rebuild_rspamd(db)

    return _mailbox_to_dict(mb)


@router.put("/mail/domains/{domain_id}/mailboxes/{mailbox_id}",
            response_model=MailboxResponse)
async def update_mailbox(
    domain_id:  int,
    mailbox_id: int,
    data:       MailboxUpdate,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Actualiza un buzón: contraseña, cuota o estado activo/suspendido"""
    _require_mail_enabled()
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)

    mb = db.query(Mailbox).filter(
        Mailbox.id == mailbox_id,
        Mailbox.mail_domain_id == domain_id,
    ).first()
    if not mb:
        raise HTTPException(404, "Buzón no encontrado")

    panel_username = md.user.username if md.user else current_user.username

    if data.password is not None:
        from scripts.password_policy import enforce_or_400
        enforce_or_400(data.password, db)

    try:
        from scripts.mail_manager import MailManager
        mgr = MailManager()

        if data.password is not None:
            new_hash = mgr.hash_password(data.password)
            mgr.change_mailbox_password(
                panel_username, md.domain_name, mb.username,
                data.password, data.quota_mb or mb.quota_mb
            )
            mb.password_hash = new_hash
            try:
                mb.encrypted_password = _encrypt_password(data.password)
            except Exception:
                pass

        if data.quota_mb is not None and data.quota_mb != mb.quota_mb:
            mgr.update_mailbox_quota(
                panel_username, md.domain_name, mb.username,
                data.quota_mb, mb.password_hash
            )
            mb.quota_mb = data.quota_mb

        if data.is_active is not None and data.is_active != mb.is_active:
            mgr.set_mailbox_active(
                panel_username, md.domain_name, mb.username,
                data.is_active,
                password_hash=mb.password_hash,
                quota_mb=mb.quota_mb,
            )
            mb.is_active = data.is_active

    except PermissionError:
        logger.warning("Sin permisos root para modificar buzón (¿entorno dev?)")
        # Actualizar solo la BD
        if data.password is not None:
            try:
                from scripts.mail_manager import MailManager
                mb.password_hash = MailManager().hash_password(data.password)
            except Exception:
                pass
            try:
                mb.encrypted_password = _encrypt_password(data.password)
            except Exception:
                pass
        if data.quota_mb is not None:
            mb.quota_mb = data.quota_mb
        if data.is_active is not None:
            mb.is_active = data.is_active
    except Exception as e:
        raise HTTPException(500, f"Error actualizando buzón: {e}")

    # Límite de envío (solo BD; lo aplica Rspamd vía el mapa)
    send_limit_changed = False
    if getattr(data, "send_limit_hour", None) is not None and data.send_limit_hour != mb.send_limit_hour:
        mb.send_limit_hour = data.send_limit_hour
        send_limit_changed = True

    # ── Reenvío ──────────────────────────────────────────────────────────
    forward_changed = False
    if data.forward_to is not None or data.forward_keep_copy is not None:
        new_forward_to   = data.forward_to   if data.forward_to   is not None else (mb.forward_to or "")
        new_keep_copy    = data.forward_keep_copy if data.forward_keep_copy is not None else getattr(mb, "forward_keep_copy", True)
        mb.forward_to        = new_forward_to or None
        mb.forward_keep_copy = new_keep_copy
        forward_changed = True
        try:
            from scripts.mail_manager import MailManager
            mgr2 = MailManager()
            if new_forward_to and new_forward_to.strip():
                destinations = [e.strip() for e in new_forward_to.split(",") if e.strip()]
                mgr2.set_forward(md.domain_name, mb.username, destinations, new_keep_copy)
            else:
                mgr2.remove_forward(md.domain_name, mb.username)
        except Exception as e:
            logger.warning(f"Error configurando forward en Postfix: {e}")

    # ── Auto-respuesta ────────────────────────────────────────────────────
    if data.autoreply_enabled is not None:
        mb.autoreply_enabled = data.autoreply_enabled
        if data.autoreply_subject is not None:
            mb.autoreply_subject = data.autoreply_subject
        if data.autoreply_body is not None:
            mb.autoreply_body = data.autoreply_body
        try:
            from scripts.mail_manager import MailManager
            mgr3 = MailManager()
            if data.autoreply_enabled:
                mgr3.set_autoreply(
                    panel_username, md.domain_name, mb.username,
                    mb.autoreply_subject or f"Re: (Respuesta automática)",
                    mb.autoreply_body   or "Estoy fuera de la oficina.",
                )
            else:
                mgr3.remove_autoreply(panel_username, md.domain_name, mb.username)
        except Exception as e:
            logger.warning(f"Error configurando autoreply Sieve: {e}")

    db.commit()
    db.refresh(mb)
    if send_limit_changed:
        _rebuild_rspamd(db)
    return _mailbox_to_dict(mb)


@router.delete("/mail/domains/{domain_id}/mailboxes/{mailbox_id}",
               status_code=status.HTTP_204_NO_CONTENT)
async def delete_mailbox(
    domain_id:  int,
    mailbox_id: int,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Elimina un buzón y su Maildir del disco"""
    _require_mail_enabled()
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)

    mb = db.query(Mailbox).filter(
        Mailbox.id == mailbox_id,
        Mailbox.mail_domain_id == domain_id,
    ).first()
    if not mb:
        raise HTTPException(404, "Buzón no encontrado")

    panel_username  = md.user.username if md.user else current_user.username
    mailbox_username = mb.username

    # Borrar primero los tokens de webmail del buzón (defensa en profundidad:
    # el FK ya es ON DELETE CASCADE, pero esto evita el 500 en BD antiguas donde
    # el cascade no estuviera aplicado).
    db.query(WebmailToken).filter(WebmailToken.mailbox_id == mb.id).delete(
        synchronize_session=False)
    db.delete(mb)
    db.commit()

    try:
        from scripts.mail_manager import MailManager
        MailManager().delete_mailbox(panel_username, md.domain_name, mailbox_username)
    except PermissionError:
        logger.warning("Sin permisos root para eliminar buzón del sistema (¿entorno dev?)")
    except Exception as e:
        logger.error(f"Error eliminando buzón del sistema: {e}")

    # El buzón sale del mapa de rate-limit
    _rebuild_rspamd(db)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Alias
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/mail/domains/{domain_id}/aliases",
            response_model=List[MailAliasResponse])
async def list_aliases(
    domain_id: int,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Lista los alias de un dominio de correo"""
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)
    return [_alias_to_dict(al) for al in md.aliases]


@router.post("/mail/domains/{domain_id}/aliases",
             response_model=MailAliasResponse,
             status_code=status.HTTP_201_CREATED)
async def create_alias(
    domain_id: int,
    data: MailAliasCreate,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Crea un alias o catch-all para el dominio"""
    _require_mail_enabled()
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)

    # Evitar duplicados
    existing = db.query(MailAlias).filter(
        MailAlias.mail_domain_id == md.id,
        MailAlias.source == data.source,
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El alias '{data.source}@{md.domain_name}' ya existe"
        )

    al = MailAlias(
        mail_domain_id = md.id,
        source         = data.source,
        destination    = data.destination,
    )
    db.add(al)
    db.commit()
    db.refresh(al)

    # Registrar en Postfix
    try:
        from scripts.mail_manager import MailManager
        mgr = MailManager()
        if data.source == "@":
            mgr.set_catch_all(md.domain_name, data.destination)
        else:
            mgr.create_alias(md.domain_name, data.source, data.destination)
    except PermissionError:
        logger.warning("Sin permisos root para crear alias (¿entorno dev?)")
    except Exception as e:
        logger.error(f"Error creando alias en Postfix: {e}")

    return _alias_to_dict(al)


@router.delete("/mail/domains/{domain_id}/aliases/{alias_id}",
               status_code=status.HTTP_204_NO_CONTENT)
async def delete_alias(
    domain_id: int,
    alias_id:  int,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Elimina un alias"""
    _require_mail_enabled()
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)

    al = db.query(MailAlias).filter(
        MailAlias.id == alias_id,
        MailAlias.mail_domain_id == domain_id,
    ).first()
    if not al:
        raise HTTPException(404, "Alias no encontrado")

    source = al.source
    db.delete(al)
    db.commit()

    try:
        from scripts.mail_manager import MailManager
        mgr = MailManager()
        if source == "@":
            mgr.remove_catch_all(md.domain_name)
        else:
            mgr.delete_alias(md.domain_name, source)
    except PermissionError:
        logger.warning("Sin permisos root para eliminar alias (¿entorno dev?)")
    except Exception as e:
        logger.error(f"Error eliminando alias de Postfix: {e}")

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Antispam — configuración y estadísticas por dominio
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/mail/domains/{domain_id}/spam", response_model=SpamSettingsResponse)
async def get_spam_settings(
    domain_id: int,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Obtiene la configuración antispam y estadísticas de un dominio"""
    md = db.query(MailDomain).filter(MailDomain.id == domain_id).first()
    if not md:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    _require_edit(md, current_user)

    stats = SpamStatsResponse()
    try:
        from scripts.rspamd_manager import RspamdManager
        mgr = RspamdManager()
        if mgr.rspamd_available():
            raw = mgr.get_domain_stats(md.domain_name)
            stats = SpamStatsResponse(**raw)
    except Exception:
        pass

    # Umbral efectivo: si el dominio no lo personalizó (None), mostrar el GLOBAL
    # del admin (es el que de verdad se aplica).
    g = _global_spam_thresholds()
    return SpamSettingsResponse(
        spam_tag_threshold=md.spam_tag_threshold if md.spam_tag_threshold is not None else g["tag"],
        spam_reject_threshold=md.spam_reject_threshold if md.spam_reject_threshold is not None else g["reject"],
        whitelist_senders=md.whitelist_senders or "",
        blacklist_senders=md.blacklist_senders or "",
        stats=stats,
    )


def _global_spam_thresholds() -> dict:
    """Umbrales globales del admin (actions.conf) o defaults. {tag, reject}."""
    try:
        from scripts import rspamd_tuning
        a = rspamd_tuning.get_actions()
        return {"tag": a.get("add header", 6.0), "reject": a.get("reject", 15.0)}
    except Exception:
        return {"tag": 6.0, "reject": 15.0}


@router.put("/mail/domains/{domain_id}/spam", response_model=SpamSettingsResponse)
async def update_spam_settings(
    domain_id: int,
    payload: SpamSettingsUpdate,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Actualiza umbrales de spam y listas de remitentes de un dominio"""
    _require_mail_enabled()
    md = db.query(MailDomain).filter(MailDomain.id == domain_id).first()
    if not md:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    _require_edit(md, current_user)

    # Umbrales: si el cliente deja el MISMO valor que el global del admin, lo
    # guardamos como NULL (= "heredar global"), no como personalización. Así el
    # ajuste global del admin sigue aplicando salvo que el cliente ponga otro valor.
    g = _global_spam_thresholds()
    if payload.spam_tag_threshold is not None:
        md.spam_tag_threshold = (None if abs(payload.spam_tag_threshold - g["tag"]) < 0.01
                                 else payload.spam_tag_threshold)
    if payload.spam_reject_threshold is not None:
        md.spam_reject_threshold = (None if abs(payload.spam_reject_threshold - g["reject"]) < 0.01
                                    else payload.spam_reject_threshold)
    if payload.whitelist_senders     is not None: md.whitelist_senders     = payload.whitelist_senders.strip()
    if payload.blacklist_senders     is not None: md.blacklist_senders     = payload.blacklist_senders.strip()
    db.commit()

    # Regenerar toda la config de Rspamd (umbrales/listas + rate-limit)
    _rebuild_rspamd(db)

    return SpamSettingsResponse(
        spam_tag_threshold=md.spam_tag_threshold if md.spam_tag_threshold is not None else g["tag"],
        spam_reject_threshold=md.spam_reject_threshold if md.spam_reject_threshold is not None else g["reject"],
        whitelist_senders=md.whitelist_senders or "",
        blacklist_senders=md.blacklist_senders or "",
    )


@router.get("/mail/spam/stats", response_model=SpamStatsResponse)
async def get_global_spam_stats(current_user=Depends(require_admin)):
    """Estadísticas globales de Rspamd (solo admin)"""
    try:
        from scripts.rspamd_manager import RspamdManager
        return SpamStatsResponse(**RspamdManager().get_global_stats())
    except Exception as e:
        return SpamStatsResponse(error=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Roundcube Webmail — autologin
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/mail/roundcube/status", response_model=RoundcubeStatusResponse)
async def get_roundcube_status(current_user=Depends(require_auth)):
    """
    Indica si Roundcube está instalado y la URL base del webmail.
    El frontend usa esta info para mostrar (o no) el botón de webmail.
    """
    enabled = os.getenv("ROUNDCUBE_ENABLED", "false").lower() == "true"
    url = os.getenv("ROUNDCUBE_URL", "/webmail") if enabled else None
    return RoundcubeStatusResponse(enabled=enabled, url=url, webmail_url=url)


@router.post(
    "/mail/domains/{domain_id}/mailboxes/{mailbox_id}/webmail-token",
    response_model=WebmailTokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_webmail_token(
    domain_id:  int,
    mailbox_id: int,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """
    Genera un token de autologin de un solo uso para abrir Roundcube
    directamente en la sesión del buzón indicado.
    - Validez: 60 segundos.
    - Uso único: el token se invalida tras el primer acceso de Roundcube.
    - Solo disponible si ROUNDCUBE_ENABLED=true en el .env.
    """
    _require_mail_enabled()

    if os.getenv("ROUNDCUBE_ENABLED", "false").lower() != "true":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Roundcube no está instalado en este servidor."
        )

    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)

    mb = db.query(Mailbox).filter(
        Mailbox.id == mailbox_id,
        Mailbox.mail_domain_id == domain_id,
    ).first()
    if not mb:
        raise HTTPException(status_code=404, detail="Buzón no encontrado")

    if not mb.encrypted_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Autologin no disponible para este buzón. "
                "Cambia su contraseña desde el panel para activarlo."
            ),
        )

    # Eliminar tokens anteriores no consumidos de este buzón
    db.query(WebmailToken).filter(
        WebmailToken.mailbox_id == mailbox_id,
        WebmailToken.used == False,
    ).delete(synchronize_session=False)

    # Crear nuevo token (UUID hex de 32 chars, TTL 60s)
    token = uuid.uuid4().hex
    wt = WebmailToken(
        token      = token,
        mailbox_id = mailbox_id,
        expires_at = datetime.utcnow() + timedelta(seconds=60),
    )
    db.add(wt)
    db.commit()

    # Construir URL del webmail del dominio.
    # Si el dominio tiene webmail propio (webmail.dominio.com) con SSL → usarlo.
    # Si no, caer al ROUNDCUBE_URL del .env (ruta relativa al panel como fallback).
    from scripts.webmail_manager import WebmailManager, vhost_name
    import subprocess as _sp
    webmail_domain = f"webmail.{md.domain_name}"
    webmail_ssl = os.path.exists(
        f"/etc/letsencrypt/live/{md.domain_name}/fullchain.pem"
    ) or os.path.exists(
        f"/etc/letsencrypt/live/{webmail_domain}/fullchain.pem"
    )
    vhost_enabled = os.path.exists(
        f"/etc/nginx/sites-enabled/{vhost_name(md.domain_name)}"
    )
    if vhost_enabled:
        scheme = "https" if webmail_ssl else "http"
        roundcube_url = f"{scheme}://{webmail_domain}/"
    else:
        roundcube_url = os.getenv("ROUNDCUBE_URL", "/webmail/")
        if not roundcube_url.endswith("/"):
            roundcube_url += "/"
    full_url = f"{roundcube_url}?svqtoken={token}"

    logger.info(f"Token webmail generado para {mb.full_email} (expira en 60s)")
    return WebmailTokenResponse(token=token, url=full_url, expires_in=60)


@router.get("/internal/webmail-token/{token}")
async def validate_webmail_token(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Endpoint INTERNO exclusivo para el plugin Roundcube (localhost).
    Valida el token, lo marca como usado y devuelve las credenciales IMAP.

    ⚠ Solo accesible desde 127.0.0.1 / ::1.
    No requiere autenticación JWT — la seguridad reside en la restricción de IP.
    """
    # Restringir acceso a localhost únicamente
    client_host = (request.client.host if request.client else "")
    if client_host not in ("127.0.0.1", "::1", "localhost", ""):
        logger.warning(f"Intento de acceso al endpoint interno desde {client_host}")
        raise HTTPException(status_code=403, detail="Acceso denegado")

    # Validar token: no usado + no caducado
    wt = db.query(WebmailToken).filter(
        WebmailToken.token == token,
        WebmailToken.used  == False,
    ).first()

    if not wt:
        raise HTTPException(status_code=404, detail="Token no válido o ya utilizado")

    if datetime.utcnow() > wt.expires_at:
        db.delete(wt)
        db.commit()
        raise HTTPException(status_code=410, detail="Token expirado")

    mb = wt.mailbox
    if not mb or not mb.encrypted_password:
        raise HTTPException(status_code=400, detail="Credenciales no disponibles")

    # Descifrar contraseña
    try:
        plain_password = _decrypt_password(mb.encrypted_password)
    except Exception as e:
        logger.error(f"Error descifrando contraseña del buzón {mb.id}: {e}")
        raise HTTPException(status_code=500, detail="Error interno al descifrar credenciales")

    # Marcar token como usado (consumo único)
    wt.used = True
    db.commit()

    logger.info(f"Token webmail consumido para {mb.full_email}")
    return {
        "username":  mb.full_email,
        "password":  plain_password,
        "imap_host": "localhost",
        "imap_port": 143,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Autoconfig / Autodiscover (sin autenticación — clientes de correo)
# ─────────────────────────────────────────────────────────────────────────────

def _mail_server_hostname() -> str:
    """Hostname del servidor de correo (de /etc/mailname o FQDN del sistema)"""
    try:
        with open("/etc/mailname") as f:
            h = f.read().strip()
            if h:
                return h
    except Exception:
        pass
    return socket.getfqdn()


def _domain_from_request(request: Request) -> str:
    """Extrae el dominio del Host header, quitando prefijos autoconfig./autodiscover."""
    host = request.headers.get("host", "").split(":")[0].lower()
    for prefix in ("autoconfig.", "autodiscover.", "mail."):
        if host.startswith(prefix):
            return host[len(prefix):]
    return host


def _autoconfig_xml(domain: str, mail_host: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<clientConfig version="1.1">
  <emailProvider id="{domain}">
    <domain>{domain}</domain>
    <displayName>Correo en {domain}</displayName>
    <displayShortName>{domain}</displayShortName>
    <incomingServer type="imap">
      <hostname>{mail_host}</hostname>
      <port>993</port>
      <socketType>SSL</socketType>
      <authentication>password-cleartext</authentication>
      <username>%EMAILADDRESS%</username>
    </incomingServer>
    <incomingServer type="imap">
      <hostname>{mail_host}</hostname>
      <port>143</port>
      <socketType>STARTTLS</socketType>
      <authentication>password-cleartext</authentication>
      <username>%EMAILADDRESS%</username>
    </incomingServer>
    <incomingServer type="pop3">
      <hostname>{mail_host}</hostname>
      <port>995</port>
      <socketType>SSL</socketType>
      <authentication>password-cleartext</authentication>
      <username>%EMAILADDRESS%</username>
    </incomingServer>
    <outgoingServer type="smtp">
      <hostname>{mail_host}</hostname>
      <port>587</port>
      <socketType>STARTTLS</socketType>
      <authentication>password-cleartext</authentication>
      <username>%EMAILADDRESS%</username>
    </outgoingServer>
  </emailProvider>
</clientConfig>"""


def _autodiscover_xml(domain: str, mail_host: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Autodiscover xmlns="http://schemas.microsoft.com/exchange/autodiscover/responseschema/2006">
  <Response xmlns="http://schemas.microsoft.com/exchange/autodiscover/outlook/responseschema/2006a">
    <Account>
      <AccountType>email</AccountType>
      <Action>settings</Action>
      <Protocol>
        <Type>IMAP</Type>
        <Server>{mail_host}</Server>
        <Port>993</Port>
        <LoginName>%EMAILADDRESS%</LoginName>
        <DomainRequired>off</DomainRequired>
        <SPA>off</SPA>
        <SSL>on</SSL>
        <AuthRequired>on</AuthRequired>
      </Protocol>
      <Protocol>
        <Type>SMTP</Type>
        <Server>{mail_host}</Server>
        <Port>587</Port>
        <LoginName>%EMAILADDRESS%</LoginName>
        <DomainRequired>off</DomainRequired>
        <SPA>off</SPA>
        <SSL>off</SSL>
        <AuthRequired>on</AuthRequired>
      </Protocol>
    </Account>
  </Response>
</Autodiscover>"""


@router.get("/.well-known/autoconfig/mail/config-v1.1.xml", include_in_schema=False)
@router.get("/mail/config-v1.1.xml", include_in_schema=False)
async def thunderbird_autoconfig(request: Request, db: Session = Depends(get_db)):
    """Autoconfig para Thunderbird y clientes compatibles Mozilla"""
    domain = _domain_from_request(request)
    xml = _autoconfig_xml(domain, _mail_server_hostname())
    return Response(content=xml, media_type="application/xml; charset=utf-8")


@router.post("/autodiscover/autodiscover.xml", include_in_schema=False)
@router.get("/autodiscover/autodiscover.xml", include_in_schema=False)
@router.post("/Autodiscover/Autodiscover.xml", include_in_schema=False)
@router.get("/Autodiscover/Autodiscover.xml", include_in_schema=False)
async def outlook_autodiscover(request: Request, db: Session = Depends(get_db)):
    """Autodiscover para Outlook y clientes Microsoft"""
    domain = _domain_from_request(request)
    xml = _autodiscover_xml(domain, _mail_server_hostname())
    return Response(content=xml, media_type="application/xml; charset=utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Monitoreo de envío — lector de logs Postfix / Dovecot
# ─────────────────────────────────────────────────────────────────────────────

import re
from typing import Optional

# Archivos de log a leer (en orden de preferencia)
_MAIL_LOGS = [
    "/var/log/mail.log",
    "/var/log/maillog",
    "/var/log/mail/mail.log",
]

# El log usa formato ISO 8601: 2026-06-03T19:53:41.983708+02:00 host proceso[pid]: ...
# Capturamos la parte de fecha/hora legible (YYYY-MM-DDTHH:MM:SS)
_TS = r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\S*"

# Enviados: postfix/smtp (salida directa) o postfix/submission/smtp
# Línea ejemplo: 2026-06-03T19:44:34... postfix/submission/smtpd[pid]: QUEUEID: to=<dest>, relay=..., status=sent
_RE_DELIVERY = re.compile(
    r"^" + _TS + r"\s+\S+\s+postfix/(?:\w+/)?smtp[^/\[]*\[\d+\]:\s+"
    r"([A-F0-9]+):\s+to=<([^>]*)>,\s+relay=([^,]+),.*?\bstatus=(\w+)"
)
# Recibidos localmente: postfix/virtual o postfix/lmtp (entrega al buzón Maildir/Dovecot)
_RE_VIRTUAL = re.compile(
    r"^" + _TS + r"\s+\S+\s+postfix/(?:virtual|lmtp)\[\d+\]:\s+"
    r"([A-F0-9]+):\s+to=<([^>]*)>,\s+relay=([^,]+),.*?\bstatus=(\w+)"
)
# from= para asociar remitente al queueid
_RE_FROM = re.compile(
    r"^" + _TS + r"\s+\S+\s+postfix/\S+\[\d+\]:\s+([A-F0-9]+):\s+from=<([^>]*)>"
)
# Rechazados en SMTP: NOQUEUE reject (smtpd). Formato real:
#   NOQUEUE: reject: RCPT from host[ip]: 454 4.7.1 <dest>: motivo; from=<X> to=<Y> ...
# Capturamos el motivo (todo lo previo a "; from=") y, si están, from/to.
_RE_REJECT = re.compile(
    r"^" + _TS + r"\s+\S+\s+postfix/\S*smtpd\[\d+\]:\s+NOQUEUE:\s+reject:\s+"
    r"\w+\s+from\s+\S+:\s+(?P<reason>.*?)(?:;\s*from=<(?P<from>[^>]*)>)?"
    r"(?:\s+to=<(?P<to>[^>]*)>)?(?:\s+proto=.*)?$"
)
# Rechazados por milter (Rspamd rechaza el mensaje ya encolado en postfix/cleanup):
#   QID: milter-reject: END-OF-MESSAGE from host[ip]: 5.7.1 Spam message rejected;
#        from=<X> to=<Y> proto=ESMTP ...
_RE_MILTER_REJECT = re.compile(
    r"^" + _TS + r"\s+\S+\s+postfix/(?:cleanup|\S*smtpd)\[\d+\]:\s+"
    r"(?P<qid>[A-F0-9]+):\s+milter-reject:\s+\S+\s+from\s+\S+:\s+"
    r"(?P<reason>.*?)(?:;\s*from=<(?P<from>[^>]*)>)?"
    r"(?:\s+to=<(?P<to>[^>]*)>)?(?:\s+proto=.*)?$"
)


def _read_mail_log(lines: int = 500) -> list[str]:
    """Lee las últimas N líneas del log de correo (solo el actual)."""
    for path in _MAIL_LOGS:
        if os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    # Leer las últimas ~200 KB para no cargar todo en memoria
                    f.seek(0, 2)
                    size = f.tell()
                    chunk = min(size, 200_000)
                    f.seek(-chunk, 2)
                    raw = f.read(chunk).decode("utf-8", errors="replace")
                return raw.splitlines()[-lines:]
            except Exception as e:
                logger.warning(f"No se pudo leer {path}: {e}")
    return []


def _mail_log_base() -> Optional[str]:
    """Ruta del mail.log activo (el primero que exista)."""
    for path in _MAIL_LOGS:
        if os.path.exists(path):
            return path
    return None


# ── Veredicto de Rspamd (acción + score + símbolos), cruzado por qid ──────────
_RSPAMD_LOGS = [
    "/var/log/rspamd/rspamd.log",
    "/var/log/rspamd.log",
]

# rspamd_task_write_log: ... qid: <ABCDEF>, ip: ..., from: <...>,
#   (default: F (no action): [4.89/15.00] [SYM1(1.50){..},SYM2(1.00){..},...]),
_RE_RSPAMD = re.compile(
    r"qid:\s*<([A-F0-9]+)>.*?\((?:default|[^)]*?):\s*[A-Z]\s*\(([^)]+)\):\s*"
    r"\[([\-\d.]+)/([\-\d.]+)\]\s*\[([^\]]*)\]"
)


def _rspamd_logs_for_date(date_str: str, max_bytes: int = 60_000_000) -> dict:
    """Mapa qid → {action, score, threshold, symbols} para un día, leyendo el log
    de Rspamd (y sus rotados). Solo se queda con el ÚLTIMO veredicto por qid (el
    definitivo: un correo puede pasar por greylist y luego 'no action')."""
    import glob
    import gzip
    base = next((p for p in _RSPAMD_LOGS if os.path.exists(p)), None)
    if not base:
        return {}
    rotated = sorted(glob.glob(base + ".*"),
                     key=lambda p: os.path.getmtime(p), reverse=True)
    # Procesar del más antiguo al más reciente para que el último gane.
    candidates = list(reversed([base] + rotated))
    out: dict[str, dict] = {}
    for path in candidates:
        try:
            opener = gzip.open if path.endswith(".gz") else open
            with opener(path, "rt", encoding="utf-8", errors="replace") as f:
                read = 0
                for line in f:
                    read += len(line)
                    if read > max_bytes:
                        break
                    # El log de rspamd usa "YYYY-MM-DD HH:MM:SS" al inicio.
                    if line[:10] != date_str:
                        continue
                    m = _RE_RSPAMD.search(line)
                    if not m:
                        continue
                    qid, action, score, thr, syms = m.groups()
                    out[qid] = {
                        "action": action.strip(),
                        "score": None if score == "nan" else _safe_float(score),
                        "threshold": _safe_float(thr),
                        "symbols": _top_symbols(syms),
                    }
        except Exception as e:
            logger.warning(f"No se pudo leer {path}: {e}")
    return out


def _safe_float(s):
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


# Traducción de los símbolos de Rspamd más comunes a lenguaje claro (admin).
# Si un símbolo no está aquí, se muestra una versión "humanizada" del nombre.
_SYMBOL_ES = {
    "HFILTER_FROMHOST_NORES_A_OR_MX": "El servidor del remitente no resuelve bien (DNS)",
    "HFILTER_FROMHOST_NORESOLVE_MX": "El dominio del remitente no tiene MX",
    "HFILTER_HELO_IP_A": "El HELO no coincide con la IP del remitente",
    "HFILTER_HELO_NORESOLVE": "El HELO del remitente no resuelve",
    "ARC_REJECT": "Falló la validación ARC (cadena de reenvío)",
    "ARC_NA": "Sin firma ARC",
    "DMARC_POLICY_REJECT": "DMARC del dominio dice rechazar",
    "DMARC_POLICY_QUARANTINE": "DMARC del dominio dice cuarentena",
    "DMARC_POLICY_SOFTFAIL": "DMARC falló (soft)",
    "DMARC_DNSFAIL": "No se pudo comprobar DMARC (DNS)",
    "R_SPF_FAIL": "Falló SPF (IP no autorizada por el dominio)",
    "R_SPF_SOFTFAIL": "SPF dudoso (soft fail)",
    "R_SPF_DNSFAIL": "No se pudo comprobar SPF (DNS)",
    "R_SPF_NA": "El dominio no tiene SPF",
    "R_DKIM_REJECT": "Falló la firma DKIM",
    "R_DKIM_TEMPFAIL": "No se pudo comprobar DKIM (temporal)",
    "R_DKIM_NA": "Sin firma DKIM",
    "FORGED_SENDER": "El remitente visible no coincide con el real",
    "FROM_NEQ_ENVFROM": "El From no coincide con el sobre",
    "MISSING_TO": "Le falta la cabecera 'Para'",
    "MISSING_DATE": "Le falta la cabecera de fecha",
    "MISSING_MID": "Le falta el Message-ID",
    "FAKE_REPLY": "Simula ser una respuesta (Re:) sin serlo",
    "MANY_INVISIBLE_PARTS": "Contiene muchas partes invisibles (típico de spam)",
    "MIME_GOOD": "Estructura del mensaje correcta",
    "BAYES_SPAM": "El filtro aprendido lo cree spam",
    "BAYES_HAM": "El filtro aprendido lo cree legítimo",
    "GREYLIST": "Greylisting (rechazo temporal para verificar)",
    "RBL_SPAMHAUS": "La IP está en lista negra (Spamhaus)",
    "RECEIVED_SPAMHAUS_XBL": "IP en lista negra de Spamhaus",
    "URIBL_BLACK": "Contiene un enlace en lista negra",
    "MID_RHS_NOT_FQDN": "El Message-ID tiene un dominio inválido",
    "URI_COUNT_ODD": "Número inusual de enlaces",
    "EXT_CSS": "Usa CSS externo (común en marketing/spam)",
    "INFO_TO_INFO_LU": "Enviado de info@ a info@ (patrón de spam)",
    "MV_CASE": "Asunto con mayúsculas/minúsculas sospechosas",
    "FROM_EXCESS_QP": "Remitente con codificación rara (típico de spam)",
    "REPLYTO_EXCESS_QP": "Responder-a con codificación rara (típico de spam)",
    "TO_EXCESS_QP": "Destinatario con codificación rara (típico de spam)",
    "SUBJ_EXCESS_QP": "Asunto con codificación rara (típico de spam)",
    "URL_MULTIPLE_AT_SIGNS": "Enlace con varias '@' (ocultación de URL)",
    "URL_QUERY_MULTIPLE_URLS": "Enlace que esconde otras URLs (redirección)",
    "SUSPICIOUS_IMAGES": "Imágenes sospechosas (spam visual)",
    "MIXED_CHARSET": "Mezcla de alfabetos (truco anti-filtro)",
    "PHISHING": "Posible phishing (suplantación)",
    "MID_RHS_WWW": "El Message-ID usa un dominio con 'www' (sospechoso)",
    "HTML_ONLY": "Solo HTML, sin versión de texto (común en spam)",
    "PARTS_DIFFER": "Las versiones texto y HTML no coinciden",
    "BAD_EXTENSION": "Adjunto con extensión peligrosa",
    "HOSTNAME_UNKNOWN": "El servidor del remitente no tiene nombre (DNS inverso)",
    "DATE_IN_PAST": "Fecha del mensaje en el pasado",
    "DATE_IN_FUTURE": "Fecha del mensaje en el futuro",
    "RDNS_NONE": "La IP del remitente no tiene DNS inverso",
    "RCVD_IN_DNSWL_NONE": "Remitente no está en listas blancas",
    "MANY_INVISIBLE_PARTS": "Contiene muchas partes invisibles (típico de spam)",
    "ONCE_RECEIVED": "Cadena de entrega demasiado corta (sospechoso)",
    "R_BAD_CTE_7BIT": "Codificación del cuerpo incorrecta",
    "MIME_HTML_ONLY": "Solo HTML, sin versión de texto (común en spam)",
    "FORGED_RECIPIENTS": "Destinatarios falsificados",
}


def _humanize_symbol(name: str) -> str:
    """Texto claro de un símbolo. Si no está mapeado, limpia el nombre técnico."""
    if name in _SYMBOL_ES:
        return _SYMBOL_ES[name]
    # Fallback: quitar prefijos técnicos y poner legible.
    h = re.sub(r"^(HFILTER_|R_|RBL_|RECEIVED_|URIBL_|MIME_)", "", name)
    return h.replace("_", " ").capitalize()


def _top_symbols(syms_str: str, n: int = 3) -> list:
    """De la lista de símbolos 'SYM(peso){...},...' devuelve los n de mayor peso
    POSITIVO (los que empujan a spam), como [{name, label, weight}]."""
    out = []
    for chunk in syms_str.split("},"):
        m = re.match(r"\s*([A-Z0-9_]+)\(([\-\d.]+)\)", chunk)
        if m:
            w = _safe_float(m.group(2)) or 0.0
            if w > 0:
                out.append({"name": m.group(1), "label": _humanize_symbol(m.group(1)),
                            "weight": w})
    out.sort(key=lambda x: x["weight"], reverse=True)
    return out[:n]


def _read_mail_log_for_date(date_str: str, max_bytes: int = 30_000_000) -> list[str]:
    """Lee las líneas del log de correo cuyo día coincide con date_str (YYYY-MM-DD).

    Recorre el mail.log activo y sus rotados (.1, .2, … y .gz) hasta cubrir la
    fecha pedida. Eficiente: para en cuanto pasa de largo la fecha. Cap de bytes
    por fichero para no agotar memoria con logs enormes.
    """
    import glob
    import gzip
    base = _mail_log_base()
    if not base:
        return []
    # Candidatos: el activo + rotados, ordenados del más reciente al más antiguo.
    rotated = sorted(glob.glob(base + ".*"),
                     key=lambda p: os.path.getmtime(p), reverse=True)
    candidates = [base] + rotated
    out: list[str] = []
    for path in candidates:
        try:
            opener = gzip.open if path.endswith(".gz") else open
            with opener(path, "rt", encoding="utf-8", errors="replace") as f:
                read = 0
                matched_here = False
                for line in f:
                    read += len(line)
                    if read > max_bytes:
                        break
                    if line[:10] == date_str:
                        out.append(line.rstrip("\n"))
                        matched_here = True
            # Si este fichero NO tenía la fecha pero ya teníamos líneas, parar
            # (los más antiguos no la tendrán). Si aún no hay nada, seguir buscando.
            if out and not matched_here:
                break
        except Exception as e:
            logger.warning(f"No se pudo leer {path}: {e}")
    return out


# Un rechazo con código SMTP 4.x es TEMPORAL (greylisting / "Try again later"):
# el servidor legítimo reintenta y normalmente acaba entregándose. Un 5.x es un
# rechazo DEFINITIVO (spam, buzón inexistente, relay denegado). Distinguirlos
# evita que el contador de "Rechazados" se infle con greylisting.
_RE_SMTP_CODE = re.compile(r"\b([45])\.\d+\.\d+\b|\b(4|5)\d\d\b")


def _is_temporary_reject(reason: str) -> bool:
    """True si el motivo del rechazo es un código SMTP 4.x (temporal)."""
    if not reason:
        return False
    m = _RE_SMTP_CODE.search(reason)
    if not m:
        # Sin código explícito: 'Try again later' es la firma del greylisting.
        return "try again later" in reason.lower()
    return (m.group(1) or m.group(2)) == "4"


# SRS reescribe el envelope-from al reenviar: SRS0=hash=tt=dominio.orig=local@svqhost
# Descifrar muestra el remitente REAL en vez de la cadena SRS ilegible.
_RE_SRS = re.compile(r"^SRS[01][=+][^=]+[=+][^=]+[=+]([^=]+)[=+]([^@]+)@", re.IGNORECASE)


def _unsrs(addr: str) -> str:
    """Si la dirección es SRS (SRS0=..=dominio=local@svqhost) devuelve el original
    'local@dominio'; si no, la deja igual."""
    if not addr:
        return addr
    m = _RE_SRS.match(addr)
    return f"{m.group(2)}@{m.group(1)}" if m else addr


def _humanize_sender(sender: str) -> str:
    """Remitente legible para el monitor:
    - '' (envelope vacío) → '(sistema/bounce)': avisos de entrega, rebotes,
      notificaciones automáticas. No tienen remitente de sobre a propósito.
    - SRS0=..=dominio=local@svqhost → 'local@dominio' (remitente original del
      reenvío, descifrado).
    - resto → tal cual.
    """
    if not sender:
        return "(sistema/bounce)"
    return _unsrs(sender)


def _parse_mail_log(raw_lines: list[str], domain_filter: Optional[str] = None,
                    search: Optional[str] = None, max_events: int = 500,
                    rspamd_map: Optional[dict] = None) -> dict:
    """
    Parsea líneas de mail.log (formato ISO 8601 de systemd-journal / rsyslog moderno).
    - sent:     entregados hacia afuera (postfix/smtp)
    - received: entregados al buzón local (postfix/virtual o postfix/lmtp)
    - rejected: rechazados en SMTP (NOQUEUE reject)
    - bounced:  status=bounced
    - deferred: status=deferred
    """
    from_map: dict[str, str] = {}
    events: list[dict] = []
    counts = {"sent": 0, "received": 0, "rejected": 0, "bounced": 0,
              "deferred": 0, "greylisted": 0}

    for line in raw_lines:
        # Acumular from= → queueid para enriquecer entregas posteriores
        m = _RE_FROM.match(line)
        if m:
            _ts, qid, sender = m.groups()
            from_map[qid] = sender
            continue

        # Entrega local al buzón (postfix/virtual o postfix/lmtp → recibido)
        m = _RE_VIRTUAL.match(line)
        if m:
            ts, qid, to_addr, relay, st = m.groups()
            sender = from_map.get(qid, "")
            if domain_filter and domain_filter not in (to_addr + sender):
                continue
            if st == "sent":   # "sent" en postfix/virtual = entregado al maildir
                counts["received"] += 1
                events.append({
                    "ts": ts[:16].replace("T", " "), "type": "received", "status": "received",
                    "from": _humanize_sender(sender), "to": to_addr, "relay": "",
                    "reason": "", "qid": qid,
                })
            continue

        # Entrega saliente (postfix/smtp hacia internet o relay)
        m = _RE_DELIVERY.match(line)
        if m:
            ts, qid, to_addr, relay, st = m.groups()
            sender = from_map.get(qid, "")
            if domain_filter and domain_filter not in (to_addr + sender):
                continue
            kind = st if st in ("sent", "bounced", "deferred") else "sent"
            counts[kind] += 1
            events.append({
                "ts": ts[:16].replace("T", " "), "type": "sent", "status": st,
                "from": _humanize_sender(sender), "to": to_addr,
                "relay": relay.split("[")[0].strip(),
                "reason": "", "qid": qid,
            })
            continue

        # Rechazados por milter (Rspamd ya tiene el qid → cruzamos su veredicto)
        m = _RE_MILTER_REJECT.match(line)
        if m:
            ts = m.group(1)
            qid = m.group("qid") or ""
            reason = (m.group("reason") or "").strip()
            sender = m.group("from") or from_map.get(qid, "")
            to_addr = m.group("to") or ""
            if domain_filter and domain_filter not in (to_addr + sender + line):
                continue
            temp = _is_temporary_reject(reason)
            counts["greylisted" if temp else "rejected"] += 1
            events.append({
                "ts": ts[:16].replace("T", " "),
                "type": "greylisted" if temp else "rejected",
                "status": "greylisted" if temp else "rejected",
                "from": _humanize_sender(sender), "to": _unsrs(to_addr), "relay": "",
                "reason": reason[:120], "qid": qid,
            })
            continue

        # Rechazados en SMTP (NOQUEUE reject)
        m = _RE_REJECT.match(line)
        if m:
            ts = m.group(1)
            reason = (m.group("reason") or "").strip()
            sender = m.group("from") or ""
            to_addr = m.group("to") or ""
            if domain_filter and domain_filter not in (to_addr + sender + line):
                continue
            temp = _is_temporary_reject(reason)
            counts["greylisted" if temp else "rejected"] += 1
            events.append({
                "ts": ts[:16].replace("T", " "),
                "type": "greylisted" if temp else "rejected",
                "status": "greylisted" if temp else "rejected",
                "from": _humanize_sender(sender), "to": _unsrs(to_addr), "relay": "",
                "reason": reason[:120], "qid": "",
            })

    # Enriquecer cada evento con el veredicto de Rspamd (cruzado por qid):
    # acción (no action/greylist/reject…), score [x/umbral] y símbolos top.
    if rspamd_map:
        ACTION_ES = {
            "no action": "Limpio", "greylist": "Greylist",
            "soft reject": "Reintentar", "add header": "Sospechoso",
            "rewrite subject": "Sospechoso", "reject": "Spam (rechazado)",
        }
        for e in events:
            v = rspamd_map.get(e.get("qid", ""))
            if not v:
                continue
            e["spam_action"]    = ACTION_ES.get(v["action"], v["action"])
            e["spam_score"]     = v["score"]
            e["spam_threshold"] = v["threshold"]
            e["spam_symbols"]   = v["symbols"]

    # Búsqueda libre por remitente/destinatario/motivo (sobre TODOS los eventos,
    # antes de recortar, para no perder coincidencias antiguas del día).
    if search:
        q = search.strip().lower()
        events = [e for e in events
                  if q in (e.get("from", "") + e.get("to", "") + e.get("reason", "")).lower()]

    total_events = len(events)
    # Los últimos max_events, más recientes primero
    events = list(reversed(events[-max_events:]))
    return {"counts": counts, "events": events, "total_events": total_events}


@router.get("/mail/logs")
async def get_mail_logs(
    domain: Optional[str] = None,
    lines: int = 500,
    current_user=Depends(require_auth),
):
    """
    Devuelve un resumen del log de correo (Postfix). Parsea el mail.log del
    servidor directamente en Python: rápido, sin procesos externos.
    - domain: filtro opcional (solo eventos donde aparezca ese dominio)
    - lines: cuántas líneas del final del log leer (máx 2000)
    """
    lines = min(lines, 2000)
    raw = _read_mail_log(lines)
    if not raw:
        return {
            "available": False,
            "message": "Log de correo no disponible (¿el servidor de correo está instalado?)",
            "counts": {"sent": 0, "received": 0, "rejected": 0, "bounced": 0, "deferred": 0},
            "events": [],
        }
    result = _parse_mail_log(raw, domain_filter=domain)
    result["available"] = True
    result["log_lines_read"] = len(raw)
    return result


@router.get("/mail/account-alerts")
async def mail_account_alerts(
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Alertas de cuentas de correo mal configuradas (contraseña/usuario erróneo
    que provoca bloqueo por fail2ban), detectadas en los fallos de login del
    journal. Filtra por rol igual que list_mail_domains: admin=todos,
    reseller=sus clientes + propios, usuario=propios."""
    query = db.query(MailDomain)
    if current_user.role == "admin":
        domains = query.all()
    elif current_user.role == "reseller":
        from api.models.models_user import User
        client_ids = [
            u.id for u in db.query(User).filter(User.parent_id == current_user.id).all()
        ]
        domains = query.filter(
            MailDomain.user_id.in_(client_ids + [current_user.id])
        ).all()
    else:
        domains = query.filter(MailDomain.user_id == current_user.id).all()

    try:
        from scripts.mail_auth_alerts import detect_account_issues
        alerts = detect_account_issues(domains, db)
    except Exception as e:
        logger.warning(f"mail_account_alerts: {e}")
        alerts = []
    return {"alerts": alerts, "count": len(alerts)}


# Cache corto del log LEÍDO por fecha (la parte cara: leer/descomprimir MB). El
# filtrado por domain/search se hace en cada petición sobre lo cacheado, que es
# barato. TTL 30s → recargas y cambios de filtro no re-leen el log.
import time as _time
_MONITOR_CACHE: dict[str, tuple] = {}   # day → (expira_ts, raw_lines, rspamd_map)
_MONITOR_TTL = 30


def _monitor_raw_for_day(day: str):
    """Devuelve (raw_lines, rspamd_map) para un día, con cache TTL."""
    now = _time.monotonic()
    hit = _MONITOR_CACHE.get(day)
    if hit and hit[0] > now:
        return hit[1], hit[2]
    raw = _read_mail_log_for_date(day)
    from datetime import date as _date
    if not raw and day == _date.today().isoformat():
        raw = _read_mail_log(2000)
    rspamd_map = _rspamd_logs_for_date(day) if raw else {}
    _MONITOR_CACHE[day] = (now + _MONITOR_TTL, raw, rspamd_map)
    # Limpieza simple: no dejar crecer el cache (días viejos).
    if len(_MONITOR_CACHE) > 8:
        for k in [k for k, v in _MONITOR_CACHE.items() if v[0] <= now]:
            _MONITOR_CACHE.pop(k, None)
    return raw, rspamd_map


@router.get("/mail/monitor")
async def mail_monitor(
    date: Optional[str] = None,
    domain: Optional[str] = None,
    search: Optional[str] = None,
    current_user=Depends(require_admin),
):
    """[Admin] Monitor global de correo: resumen + eventos de TODOS los dominios.

    - date: 'YYYY-MM-DD' (día concreto, lee logs rotados); por defecto, hoy.
    - domain: filtro opcional por dominio.
    - search: texto libre (remitente / destinatario / motivo).
    Estados por evento: enviado / recibido / rechazado / rebotado / diferido.
    El log leído se cachea 30s (el filtrado se aplica sobre lo cacheado).
    """
    from datetime import date as _date
    day = (date or _date.today().isoformat()).strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        raise HTTPException(status_code=400, detail="Fecha inválida (use YYYY-MM-DD).")

    raw, rspamd_map = _monitor_raw_for_day(day)
    if not raw:
        return {
            "available": False, "date": day,
            "message": "No hay registros de correo para esa fecha.",
            "counts": {"sent": 0, "received": 0, "rejected": 0, "bounced": 0, "deferred": 0},
            "events": [], "total_events": 0,
        }
    result = _parse_mail_log(raw, domain_filter=domain, search=search,
                             max_events=500, rspamd_map=rspamd_map)
    result["available"] = True
    result["date"] = day
    return result


@router.get("/mail/domains/{domain_id}/logs")
async def get_domain_mail_logs(
    domain_id: int,
    lines: int = 500,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Monitoreo de envío filtrado al dominio dado."""
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)
    lines = min(lines, 2000)
    raw = _read_mail_log(lines)
    if not raw:
        return {
            "available": False,
            "message": "Log de correo no disponible",
            "counts": {"sent": 0, "received": 0, "rejected": 0, "bounced": 0, "deferred": 0},
            "events": [],
        }
    result = _parse_mail_log(raw, domain_filter=md.domain_name)
    result["available"] = True
    result["domain"] = md.domain_name
    result["log_lines_read"] = len(raw)
    return result


@router.post("/mail/domains/{domain_id}/suspend")
async def suspend_mail_domain_endpoint(
    domain_id: int,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """[Admin] Suspende todo el correo de un dominio (todos sus buzones)."""
    md = _get_mail_domain_or_404(domain_id, db)
    panel_username = md.user.username if md.user else None
    from scripts.suspend_manager import suspend_mail_domain
    res = suspend_mail_domain(md, panel_username, suspend=True, db=db)
    return {"status": "ok", **res}


@router.post("/mail/domains/{domain_id}/unsuspend")
async def unsuspend_mail_domain_endpoint(
    domain_id: int,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """[Admin] Reactiva el correo de un dominio."""
    md = _get_mail_domain_or_404(domain_id, db)
    panel_username = md.user.username if md.user else None
    from scripts.suspend_manager import suspend_mail_domain
    res = suspend_mail_domain(md, panel_username, suspend=False, db=db)
    return {"status": "ok", **res}


# ─────────────────────────────────────────────────────────────────────────────
# Salud de correo del SERVIDOR (deliverability de svqhost.red & reenvíos SRS)
# ─────────────────────────────────────────────────────────────────────────────
# El servidor reescribe (SRS) los reenvíos a "...@<dominio del servidor>". Para
# que Gmail/Outlook los acepten, ESE dominio necesita SPF/DKIM/DMARC/PTR. Como su
# DNS suele ser externo, el panel no puede publicarlos solo: aquí los mostramos
# (con el valor exacto a copiar) y verificamos en vivo cuáles ya están.

@router.get("/mail/server-deliverability")
async def get_server_deliverability(current_user=Depends(require_admin),
                                    db: Session = Depends(get_db)):
    """[Admin] Diagnóstico de autenticación del correo del propio servidor.

    Devuelve, para el dominio del servidor, el estado de SPF/DKIM/DMARC/PTR con
    el valor exacto a publicar en el DNS y si ya está OK. Si el DNS es externo,
    el admin debe copiar los registros que falten en su proveedor.
    """
    _require_mail_enabled()
    from api.models.models_settings import Settings
    s = db.query(Settings).filter(Settings.id == 1).first()
    ipv4 = (s.server_ipv4 if s else None)
    ipv6 = (getattr(s, "panel_ipv6", None) if s else None)
    try:
        from scripts.mail_deliverability import diagnose
        return diagnose(server_ipv4=ipv4, server_ipv6=ipv6)
    except Exception as e:
        logger.error(f"Error en diagnóstico de deliverability: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mail/server-deliverability/generate-dkim")
async def generate_server_dkim(current_user=Depends(require_admin),
                               db: Session = Depends(get_db)):
    """[Admin] Genera (si no existe) la clave DKIM del dominio del servidor.

    Si el DNS del dominio del servidor lo gestiona el panel, intenta publicar el
    TXT automáticamente; si es externo, devuelve el registro para copiar a mano.
    """
    _require_mail_enabled()
    from scripts.mail_deliverability import get_server_mail_domain, SERVER_DKIM_SELECTOR
    domain = get_server_mail_domain()
    try:
        from scripts.dkim_manager import DkimManager
        dk = DkimManager()
        if not dk.dkim_available():
            raise HTTPException(status_code=503, detail="Rspamd/DKIM no disponible")
        info = dk.get_key_info(domain, SERVER_DKIM_SELECTOR) \
               or dk.generate_key(domain, SERVER_DKIM_SELECTOR)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo generar DKIM: {e}")

    # Si la zona la sirve el panel, publicar el TXT como ya se hace por dominio.
    published = False
    try:
        if _dns_add_dkim_record(domain, SERVER_DKIM_SELECTOR,
                                info["dns_record_value"], db):
            published = True
    except Exception as e:
        logger.info(f"DKIM del servidor no auto-publicado (DNS externo?): {e}")

    return {
        "status": "ok",
        "domain": domain,
        "dns_record_name": info["dns_record_name"],
        "dns_record_value": info["dns_record_value"],
        "auto_published": published,
    }
