"""
Rutas API para gestión de certificados SSL
"""

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from api.models.database import get_db
from api.models.models_user import User
from api.models.models_domain import Domain
from api.schemas.ssl_schemas import SSLCreate, SSLResponse, SSLToggleRequest, SSLCertInfo
from api.dependencies import require_auth
from scripts.ssl_manager import SSLManager
from scripts.domain_manager import DomainManager
from scripts import ssl_paths as _ssl_paths, custom_ssl as _custom_ssl

router = APIRouter()

# La validación de email ACME vive en api.utils.validators (sin dependencias,
# testeable). Se reexporta aquí con el nombre interno para no tocar las llamadas.
from api.utils.validators import validate_acme_email as _validate_acme_email


def _owned(domain_id: int, db: Session, user: User) -> Domain:
    """Dominio del usuario (admin: todos; reseller: los de sus clientes). 404 si no.
    Antes estas rutas buscaban solo por id: cualquier usuario autenticado podía
    revocar o renovar el certificado de un dominio ajeno."""
    from api.routes.domains import _get_owned_domain
    return _get_owned_domain(domain_id, db, user)


def _regenerate(domain: Domain, db: Session) -> None:
    """Vhost con TODO el estado del dominio (camino común). Antes se llamaba a
    regenerate_vhost con solo una parte de los ajustes y, al cambiar forzar HTTPS
    o HSTS, se perdían la contraseña de la web, las directivas personalizadas,
    los headers de seguridad, HTTP/3, el modo solo lectura y los bots.

    Regenera también los SUBDOMINIOS que usan el wildcard de este dominio: si el
    certificado del principal cambia de sitio o desaparece (revocar, subir uno
    propio, reemitir sin comodín), su vhost no puede seguir apuntando al viejo.
    Orden: primero los hijos (sus recargas pueden fallar mientras el principal
    aún apunta al certificado anterior), luego el principal (debe validar) y se
    repiten los hijos que fallaron. Si un hijo se queda sin certificado que lo
    cubra, se le desactiva el HTTPS en vez de dejar nginx roto para todos."""
    from api.routes.domains import _regenerate_from_domain
    children = []
    if not domain.is_subdomain:
        children = db.query(Domain).filter(Domain.is_subdomain == True,  # noqa: E712
                                           Domain.parent_domain == domain.domain_name,
                                           Domain.ssl_enabled == True).all()  # noqa: E712
    for child in children:
        if not _ssl_paths.existing_cert(child.domain_name):
            child.ssl_enabled = False
            child.force_https = False
            child.hsts_enabled = False
    if children:
        db.commit()
    failed = []
    for child in children:
        try:
            _regenerate_from_domain(child, db)
        except Exception:
            failed.append(child)
    _regenerate_from_domain(domain, db)
    for child in failed:
        try:
            _regenerate_from_domain(child, db)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"vhost de {child.domain_name} tras cambiar el SSL "
                                              f"de {domain.domain_name}: {e}")


def _domain_ssl_response(domain: Domain, ssl_manager: SSLManager) -> SSLResponse:
    # Leer cert del disco siempre — ssl_enabled en BD puede quedar desincronizado
    raw = ssl_manager.get_cert_info(domain.domain_name)
    cert_info = None
    if raw:
        cert_info = SSLCertInfo(**{k: raw[k] for k in SSLCertInfo.model_fields if k in raw})
    # Si hay cert en disco pero la BD dice false, corregir el flag
    ssl_enabled = domain.ssl_enabled or bool(cert_info)
    return SSLResponse(
        domain_id=domain.id,
        ssl_enabled=ssl_enabled,
        force_https=domain.force_https or False,
        hsts_enabled=domain.hsts_enabled or False,
        ssl_expires=domain.ssl_expires,
        cert_info=cert_info,
    )


@router.get("/domains/{domain_id}/ssl", response_model=SSLResponse)
async def get_ssl(
    domain_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Obtener estado SSL y detalles del certificado de un dominio"""
    domain = _owned(domain_id, db, current_user)
    ssl_manager = SSLManager()
    return _domain_ssl_response(domain, ssl_manager)


@router.put("/domains/{domain_id}/ssl/toggle", response_model=SSLResponse)
def toggle_ssl(
    domain_id: int,
    body: SSLToggleRequest,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """
    Activa o desactiva SSL (Let's Encrypt) para un dominio.
    Regenera el vhost nginx con los parámetros force_https y HSTS.
    """
    domain = _owned(domain_id, db, current_user)

    owner = db.query(User).filter(User.id == domain.user_id).first()
    if not owner:
        raise HTTPException(status_code=404, detail="Propietario no encontrado")

    ssl_manager  = SSLManager()
    domain_mgr   = DomainManager()

    try:
        if body.enabled and not domain.ssl_enabled:
            # Activar: lanzar certbot (primera emisión)
            # Prioridad: email del body → email del usuario en BD → error
            raw_email = (body.email or "").strip() or (current_user.email or "").strip()
            email = _validate_acme_email(raw_email)
            ssl_manager.create_ssl_with_email(domain.domain_name, email,
                                            include_www=not domain.is_subdomain)
            expiry = datetime.utcnow() + timedelta(days=90)
            domain.ssl_enabled    = True
            domain.ssl_expires    = expiry
            domain.ssl_renewed_at = datetime.utcnow()
            # Auto-activar force_https al emitir cert por primera vez
            if not body.force_https:
                domain.force_https = True
        elif body.enabled and domain.ssl_enabled:
            # Cert ya existe — solo actualizar opciones y regenerar vhost
            # El botón "Renovar" explícito es el único que debe llamar a certbot
            pass
        elif not body.enabled and domain.ssl_enabled:
            # Desactivar: revocar cert
            try:
                if _ssl_paths.has_le(domain.domain_name):
                    ssl_manager.revoke_ssl(domain.domain_name)
            except Exception:
                pass  # aunque falle la revocación, desactivamos en BD
            _custom_ssl.remove(domain.domain_name)
            domain.ssl_enabled = False
            domain.ssl_expires = None

        # Guardar opciones SSL siempre (aunque no cambie el estado enabled)
        domain.force_https  = body.force_https
        domain.hsts_enabled = body.hsts_enabled

        db.commit()
        db.refresh(domain)

        # Regenerar vhost con el nuevo estado SSL (todo el estado del dominio)
        _regenerate(domain, db)

        return _domain_ssl_response(domain, ssl_manager)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al gestionar SSL: {str(e)}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Emisión con progreso real: POST lanza el job en background (fases + salida de
# certbot en vivo) y la UI hace polling en el GET. Ver api/utils/ssl_jobs.py.
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/domains/{domain_id}/ssl/issue", status_code=status.HTTP_202_ACCEPTED)
async def start_ssl_issue(
    domain_id: int,
    body: SSLToggleRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Lanza la emisión del certificado en background y devuelve el job."""
    from api.utils import ssl_jobs

    domain = _owned(domain_id, db, current_user)
    if ssl_jobs.job_running("web", domain_id):
        raise HTTPException(status_code=409, detail="Ya hay una emisión SSL en curso para este dominio.")

    raw_email = (body.email or "").strip() or (current_user.email or "").strip()
    email = _validate_acme_email(raw_email)
    if body.wildcard:
        from scripts import acme_dns
        if domain.is_subdomain:
            raise HTTPException(400, detail="El certificado wildcard se pide para el dominio principal "
                                            "(cubre todos sus subdominios).")
        if not acme_dns.can_validate(db, domain.domain_name):
            raise HTTPException(400, detail=(
                f"El wildcard se valida creando un registro TXT en la zona DNS de {domain.domain_name}, "
                "y esa zona no está en este panel: el dominio tiene que usar nuestros DNS."))
    if _ssl_paths.has_custom(domain.domain_name):
        raise HTTPException(400, detail="Este dominio usa un certificado propio. Quítalo antes de "
                                        "emitir uno de Let's Encrypt.")

    steps = (ssl_jobs.wildcard_steps if body.wildcard else ssl_jobs.web_steps)(domain.domain_name)
    ssl_jobs.job_init("web", domain_id, steps)
    background_tasks.add_task(ssl_jobs.run_web_issue, domain_id, email, body.hsts_enabled,
                              bool(body.wildcard))
    return {"status": "success", "job": ssl_jobs.job_status("web", domain_id)}


@router.get("/domains/{domain_id}/ssl/issue")
async def get_ssl_issue_status(
    domain_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Estado del job de emisión (polling de la UI). job=null si nunca hubo."""
    from api.utils import ssl_jobs
    return {"status": "success", "job": ssl_jobs.job_status("web", domain_id)}


@router.post("/domains/{domain_id}/ssl/renew", response_model=SSLResponse)
def renew_ssl(
    domain_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Renueva el certificado SSL existente con certbot --force-renew"""
    domain = _owned(domain_id, db, current_user)
    if not domain.ssl_enabled:
        raise HTTPException(status_code=400, detail="El dominio no tiene SSL activo")
    if _ssl_paths.has_custom(domain.domain_name):
        raise HTTPException(status_code=400, detail=(
            "Es un certificado propio: no lo renueva Let's Encrypt. Cuando tu proveedor te dé "
            "el nuevo, súbelo igual que el actual."))
    _parent = _ssl_paths.inherited_from(domain.domain_name)
    if _parent:
        raise HTTPException(status_code=400, detail=(
            f"Este subdominio usa el certificado wildcard de {_parent}: se renueva con él "
            "(renuévalo desde la ficha de ese dominio)."))

    ssl_manager = SSLManager()
    try:
        ssl_manager.renew_ssl(domain.domain_name)
        domain.ssl_renewed_at = datetime.utcnow()
        db.commit()
        db.refresh(domain)
        return _domain_ssl_response(domain, ssl_manager)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al renovar SSL: {str(e)}"
        )


@router.post("/domains/{domain_id}/ssl", response_model=SSLResponse, status_code=status.HTTP_201_CREATED)
def create_ssl(
    domain_id: int,
    ssl: SSLCreate,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Crear certificado SSL para un dominio (legado — usa toggle)"""
    ssl_manager = SSLManager()

    try:
        domain = _owned(domain_id, db, current_user)

        raw_email = (getattr(ssl, 'email', None) or "").strip() or (current_user.email or "").strip()
        email = _validate_acme_email(raw_email)
        ssl_manager.create_ssl_with_email(domain.domain_name, email,
                                            include_www=not domain.is_subdomain)

        expiry_date = datetime.utcnow() + timedelta(days=90)
        domain.ssl_enabled     = True
        domain.ssl_certificate = "Let's Encrypt"
        domain.ssl_key         = "Managed by certbot"
        domain.ssl_expires     = expiry_date
        domain.ssl_renewed_at  = datetime.utcnow()

        db.commit()
        db.refresh(domain)

        # Regenerar vhost nginx con SSL activo (todo el estado del dominio)
        try:
            _regenerate(domain, db)
        except Exception as vhost_err:
            import logging
            logging.getLogger(__name__).warning(f"regenerate_vhost SSL falló: {vhost_err}")

        return _domain_ssl_response(domain, ssl_manager)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al crear certificado SSL: {str(e)}"
        )


@router.delete("/domains/{domain_id}/ssl", status_code=status.HTTP_204_NO_CONTENT)
def delete_ssl(
    domain_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Revocar certificado SSL de un dominio"""
    domain = _owned(domain_id, db, current_user)
    ssl_manager = SSLManager()
    try:
        if _ssl_paths.has_le(domain.domain_name):
            ssl_manager.revoke_ssl(domain.domain_name)
        _custom_ssl.remove(domain.domain_name)
        domain.ssl_enabled    = False
        domain.ssl_certificate = None
        domain.ssl_key         = None
        domain.ssl_expires     = None
        domain.force_https     = False
        db.commit()
        _regenerate(domain, db)
        return None
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al revocar certificado SSL: {str(e)}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Certificado PROPIO (subido): ver scripts/custom_ssl.py
# ─────────────────────────────────────────────────────────────────────────────

class CustomCertRequest(BaseModel):
    certificate: str = Field(..., max_length=_custom_ssl.MAX_PEM)
    private_key: str = Field(..., max_length=_custom_ssl.MAX_PEM)
    chain:       Optional[str] = Field("", max_length=_custom_ssl.MAX_PEM)


def _rebuild_mail_tls(db: Session) -> None:
    from api.utils.ssl_jobs import _rebuild_mail_tls as _r
    _r(db)


@router.post("/domains/{domain_id}/ssl/custom", response_model=SSLResponse)
def upload_custom_cert(domain_id: int, body: CustomCertRequest,
                       current_user: User = Depends(require_auth), db: Session = Depends(get_db)):
    """Instala un certificado propio. Se valida entero antes de tocar nada y, si
    nginx no lo acepta, se vuelve al estado anterior."""
    domain = _owned(domain_id, db, current_user)
    if getattr(domain, "mail_dns_only", False):
        raise HTTPException(400, detail="Este dominio no tiene web en este servidor (solo correo/DNS).")
    try:
        info = _custom_ssl.validate(domain.domain_name, body.certificate, body.private_key,
                                    body.chain or "", is_subdomain=bool(domain.is_subdomain))
    except _custom_ssl.CertError as e:
        raise HTTPException(400, detail=str(e))

    prev = {"ssl_enabled": domain.ssl_enabled, "ssl_expires": domain.ssl_expires,
            "ssl_certificate": domain.ssl_certificate}
    _custom_ssl.install(domain.domain_name, info)
    domain.ssl_enabled = True
    domain.ssl_expires = info["not_after"].replace(tzinfo=None)
    domain.ssl_certificate = "Propio"
    db.commit()
    try:
        _regenerate(domain, db)
    except Exception as e:
        _custom_ssl.restore_previous(domain.domain_name)
        for k, v in prev.items():
            setattr(domain, k, v)
        db.commit()
        try:
            _regenerate(domain, db)
        except Exception:
            pass
        raise HTTPException(422, detail=f"nginx no ha aceptado el certificado; se ha dejado el anterior: {e}")
    _rebuild_mail_tls(db)
    resp = _domain_ssl_response(domain, SSLManager())
    resp.warnings = info["warnings"]
    return resp


@router.delete("/domains/{domain_id}/ssl/custom", response_model=SSLResponse)
def remove_custom_cert(domain_id: int, current_user: User = Depends(require_auth),
                       db: Session = Depends(get_db)):
    """Quita el certificado propio. Si el dominio tenía uno de Let's Encrypt,
    vuelve a él; si no, se queda sin HTTPS."""
    domain = _owned(domain_id, db, current_user)
    if not _custom_ssl.remove(domain.domain_name):
        raise HTTPException(404, detail="Este dominio no tiene un certificado propio")
    if _ssl_paths.has_le(domain.domain_name):
        domain.ssl_certificate = "Let's Encrypt"
        info = SSLManager().get_cert_info(domain.domain_name) or {}
        try:
            domain.ssl_expires = datetime.strptime(info.get("not_after", ""), "%b %d %H:%M:%S %Y %Z")
        except ValueError:
            pass
    else:
        domain.ssl_enabled = False
        domain.ssl_expires = None
        domain.ssl_certificate = None
        domain.force_https = False
        domain.hsts_enabled = False
    db.commit()
    _regenerate(domain, db)
    _rebuild_mail_tls(db)
    return _domain_ssl_response(domain, SSLManager())
