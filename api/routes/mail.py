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
    secret = os.getenv("SECRET_KEY", "svqpanel-insecure-default")
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

    return _mail_domain_to_dict(md, current_user)


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

    if data.catch_all is not None:
        md.catch_all = data.catch_all or None
    if data.max_mailboxes is not None:
        md.max_mailboxes = data.max_mailboxes
    if data.is_active is not None:
        md.is_active = data.is_active

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

    return None


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
    )
    db.add(mb)
    db.commit()
    db.refresh(mb)

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

    db.commit()
    db.refresh(mb)
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

    # Regenerar settings.conf de Rspamd con todos los dominios
    try:
        from scripts.rspamd_manager import RspamdManager
        all_domains = db.query(MailDomain).filter(MailDomain.is_active == True).all()
        RspamdManager().rebuild_from_db(all_domains)
    except PermissionError:
        logger.warning("Sin permisos para actualizar config Rspamd (¿entorno dev?)")
    except Exception as e:
        logger.error(f"Error actualizando Rspamd: {e}")

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

    roundcube_url = os.getenv("ROUNDCUBE_URL", "/webmail")
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
