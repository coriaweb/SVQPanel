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

def _mail_domain_to_dict(md: MailDomain, current_user) -> dict:
    return {
        "id":            md.id,
        "user_id":       md.user_id,
        "domain_id":     md.domain_id,
        "domain_name":   md.domain_name,
        "is_active":     md.is_active,
        "dkim_enabled":  md.dkim_enabled,
        "dkim_selector": md.dkim_selector,
        "catch_all":     md.catch_all,
        "max_mailboxes": md.max_mailboxes,
        "send_limit_hour": getattr(md, "send_limit_hour", 1000),
        "mailbox_count": len(md.mailboxes),
        "alias_count":   len(md.aliases),
        "created_at":    md.created_at,
        "updated_at":    md.updated_at,
        "can_edit":      _can_edit(md, current_user),
    }


def _mailbox_to_dict(mb: Mailbox) -> dict:
    return {
        "id":             mb.id,
        "mail_domain_id": mb.mail_domain_id,
        "username":       mb.username,
        "quota_mb":       mb.quota_mb,
        "send_limit_hour": getattr(mb, "send_limit_hour", 200),
        "is_active":      mb.is_active,
        "full_email":     f"{mb.username}@{mb.mail_domain.domain_name}",
        "disk_usage_mb":  0.0,   # calculado aparte para no ralentizar el listado
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

    db.commit()

    # Regenerar el fichero de zona BIND9 si está disponible
    try:
        from scripts.dns_manager import DNSManager
        from api.models.models_dns import DnsRecord as DR
        records = db.query(DR).filter(DR.zone_id == zone.id).all()
        record_dicts = [
            {"record_type": r.record_type, "name": r.name,
             "content": r.content, "ttl": r.ttl, "priority": r.priority}
            for r in records
        ]
        dns_mgr = DNSManager()
        dns_mgr.write_zone_from_records(
            domain_name, zone.serial, record_dicts,
            soa_ns=zone.soa_ns, ttl=zone.ttl or 14400
        )
    except Exception as e:
        logger.warning(f"No se pudo regenerar zona BIND9 tras DKIM: {e}")

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
        mgr.rebuild_from_db(all_domains)
        mgr.rebuild_ratelimit_from_db(all_domains)
    except PermissionError:
        logger.warning("Sin permisos para actualizar Rspamd (¿entorno dev?)")
    except Exception as e:
        logger.error(f"Error actualizando Rspamd: {e}")


def _dns_ensure_mail_record(domain_name: str, db: Session) -> bool:
    """
    Asegura el registro 'mail' (A → IP del servidor) en la zona del panel, para
    que mail.{dominio} resuelva (necesario para el cert TLS y para que los
    clientes conecten). Devuelve True si la zona está en el panel.
    """
    zone = db.query(DnsZone).filter(DnsZone.domain_name == domain_name).first()
    if not zone:
        return False
    # IP del servidor desde settings
    from api.models.models_settings import Settings
    s = db.query(Settings).filter(Settings.id == 1).first()
    server_ip = (s.server_ipv4 if s else None) or zone.ip_address
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

    # El usuario regular solo puede crear dominios de correo para sí mismo
    if current_user.role == "user":
        user_id = current_user.id
    else:
        user_id = current_user.id  # admin/reseller crea bajo sí mismo por defecto

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


def _deactivate_webmail(domain_name: str, db: Session) -> None:
    """Quita el vhost webmail + el registro DNS. Tolerante a fallos."""
    try:
        from scripts.webmail_manager import WebmailManager
        WebmailManager().remove(domain_name)
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

    # Quitar el webmail por dominio (vhost + DNS) antes de borrar la zona/datos
    _deactivate_webmail(domain_name, db)

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
from pydantic import BaseModel as _BM, Field as _F


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
    """Lista los buzones de un dominio de correo"""
    md = _get_mail_domain_or_404(domain_id, db)
    _require_edit(md, current_user)
    return [_mailbox_to_dict(mb) for mb in md.mailboxes]


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

    return SpamSettingsResponse(
        spam_tag_threshold=md.spam_tag_threshold or 6.0,
        spam_reject_threshold=md.spam_reject_threshold or 15.0,
        whitelist_senders=md.whitelist_senders or "",
        blacklist_senders=md.blacklist_senders or "",
        stats=stats,
    )


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

    if payload.spam_tag_threshold    is not None: md.spam_tag_threshold    = payload.spam_tag_threshold
    if payload.spam_reject_threshold is not None: md.spam_reject_threshold = payload.spam_reject_threshold
    if payload.whitelist_senders     is not None: md.whitelist_senders     = payload.whitelist_senders.strip()
    if payload.blacklist_senders     is not None: md.blacklist_senders     = payload.blacklist_senders.strip()
    db.commit()

    # Regenerar toda la config de Rspamd (umbrales/listas + rate-limit)
    _rebuild_rspamd(db)

    return SpamSettingsResponse(
        spam_tag_threshold=md.spam_tag_threshold,
        spam_reject_threshold=md.spam_reject_threshold,
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

    # Usar SIEMPRE la barra final: /webmail/?svqtoken=... entra directo en el
    # location /webmail/ de nginx. Sin la barra, nginx hace 301 a /webmail/ y
    # PIERDE el query string (?svqtoken), por lo que Roundcube no recibe el
    # token y se queda en blanco / vuelve al panel.
    roundcube_url = os.getenv("ROUNDCUBE_URL", "/webmail/")
    if "?" not in roundcube_url and not roundcube_url.endswith("/"):
        roundcube_url += "/"
    sep = "&" if "?" in roundcube_url else "?"
    full_url = f"{roundcube_url}{sep}svqtoken={token}"

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

# Pattern Postfix: fecha hora host postfix/qmgr[pid]: QUEUEID: from=<sender>, size=N, nrcpt=N
_RE_SENT = re.compile(
    r"^(\w{3}\s+\d+\s+\d{2}:\d{2}:\d{2})\s+\S+\s+postfix/smtp(?:s|d)?\[\d+\]:\s+"
    r"([A-F0-9]+):\s+to=<([^>]*)>,\s+relay=([^,]+),.*?status=(\w+)"
)
_RE_RECV = re.compile(
    r"^(\w{3}\s+\d+\s+\d{2}:\d{2}:\d{2})\s+\S+\s+postfix/lmtp\[\d+\]:\s+"
    r"([A-F0-9]+):\s+to=<([^>]*)>,\s+relay=([^,]+),.*?status=(\w+)"
)
_RE_FROM = re.compile(
    r"^(\w{3}\s+\d+\s+\d{2}:\d{2}:\d{2})\s+\S+\s+postfix/\w+\[\d+\]:\s+"
    r"([A-F0-9]+):\s+from=<([^>]*)>"
)
_RE_REJECT = re.compile(
    r"^(\w{3}\s+\d+\s+\d{2}:\d{2}:\d{2})\s+\S+\s+postfix/smtpd\[\d+\]:\s+"
    r"NOQUEUE:\s+reject:\s+RCPT\s+from\s+[^:]+:\s+\d+\s+\S+;\s*(.*)"
)
_RE_IMAP = re.compile(
    r"^(\w{3}\s+\d+\s+\d{2}:\d{2}:\d{2})\s+\S+\s+dovecot:\s+imap(?:-login)?\[\d+\]:\s+(.+)"
)


def _read_mail_log(lines: int = 500) -> list[str]:
    """Lee las últimas N líneas del log de correo."""
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


def _parse_mail_log(raw_lines: list[str], domain_filter: Optional[str] = None) -> dict:
    """
    Parsea líneas de mail.log y devuelve un resumen estructurado:
    - sent: correos enviados (postfix/smtp status=sent)
    - received: correos recibidos (postfix/lmtp status=sent)
    - rejected: rechazados (NOQUEUE reject)
    - bounced: rebotados (status=bounced)
    - deferred: diferidos (status=deferred)
    - events: lista cronológica de los últimos N eventos
    """
    # Mapa queueid → from (para enriquecer eventos de entrega)
    from_map: dict[str, str] = {}
    events: list[dict] = []
    counts = {"sent": 0, "received": 0, "rejected": 0, "bounced": 0, "deferred": 0}

    for line in raw_lines:
        # Acumular from= para asociar al to= posterior
        m = _RE_FROM.match(line)
        if m:
            from_map[m.group(2)] = m.group(3)

        # Enviados (smtp hacia afuera)
        m = _RE_SENT.match(line)
        if m:
            ts, qid, to_addr, relay, st = m.groups()
            sender = from_map.get(qid, "")
            if domain_filter and domain_filter not in (to_addr + sender):
                continue
            kind = st if st in ("sent", "bounced", "deferred") else "sent"
            counts[kind] += 1
            events.append({
                "ts": ts, "type": "sent", "status": st,
                "from": sender, "to": to_addr, "relay": relay.split("[")[0].strip(),
                "qid": qid,
            })
            continue

        # Recibidos (lmtp → Dovecot)
        m = _RE_RECV.match(line)
        if m:
            ts, qid, to_addr, relay, st = m.groups()
            sender = from_map.get(qid, "")
            if domain_filter and domain_filter not in (to_addr + sender):
                continue
            if st == "sent":
                counts["received"] += 1
            events.append({
                "ts": ts, "type": "received", "status": "received",
                "from": sender, "to": to_addr, "relay": "",
                "qid": qid,
            })
            continue

        # Rechazados
        m = _RE_REJECT.match(line)
        if m:
            ts, reason = m.groups()
            if domain_filter and domain_filter not in line:
                continue
            counts["rejected"] += 1
            events.append({
                "ts": ts, "type": "rejected", "status": "rejected",
                "from": "", "to": "", "relay": "",
                "reason": reason[:120],
                "qid": "",
            })

    # Devolver los últimos 200 eventos (más recientes al inicio)
    events = list(reversed(events[-200:]))
    return {"counts": counts, "events": events}


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
