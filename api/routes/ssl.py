"""
Rutas API para gestión de certificados SSL
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from api.models.database import get_db
from api.models.models_user import User
from api.models.models_domain import Domain
from api.schemas.ssl_schemas import SSLCreate, SSLResponse, SSLToggleRequest, SSLCertInfo
from api.dependencies import require_auth
from scripts.ssl_manager import SSLManager
from scripts.domain_manager import DomainManager

router = APIRouter()


def _domain_ssl_response(domain: Domain, ssl_manager: SSLManager) -> SSLResponse:
    cert_info = None
    if domain.ssl_enabled:
        raw = ssl_manager.get_cert_info(domain.domain_name)
        if raw:
            cert_info = SSLCertInfo(**{k: raw[k] for k in SSLCertInfo.model_fields if k in raw})
    return SSLResponse(
        domain_id=domain.id,
        ssl_enabled=domain.ssl_enabled or False,
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
    domain = db.query(Domain).filter(Domain.id == domain_id).first()
    if not domain:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dominio no encontrado")
    ssl_manager = SSLManager()
    return _domain_ssl_response(domain, ssl_manager)


@router.put("/domains/{domain_id}/ssl/toggle", response_model=SSLResponse)
async def toggle_ssl(
    domain_id: int,
    body: SSLToggleRequest,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """
    Activa o desactiva SSL (Let's Encrypt) para un dominio.
    Regenera el vhost nginx con los parámetros force_https y HSTS.
    """
    domain = db.query(Domain).filter(Domain.id == domain_id).first()
    if not domain:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dominio no encontrado")

    owner = db.query(User).filter(User.id == domain.user_id).first()
    if not owner:
        raise HTTPException(status_code=404, detail="Propietario no encontrado")

    ssl_manager  = SSLManager()
    domain_mgr   = DomainManager()

    try:
        if body.enabled and not domain.ssl_enabled:
            # Activar: lanzar certbot
            email = body.email or "admin@example.com"
            ssl_manager.create_ssl_with_email(domain.domain_name, email)
            expiry = datetime.utcnow() + timedelta(days=90)
            domain.ssl_enabled    = True
            domain.ssl_expires    = expiry
            domain.ssl_renewed_at = datetime.utcnow()
        elif not body.enabled and domain.ssl_enabled:
            # Desactivar: revocar cert
            try:
                ssl_manager.revoke_ssl(domain.domain_name)
            except Exception:
                pass  # aunque falle la revocación, desactivamos en BD
            domain.ssl_enabled = False
            domain.ssl_expires = None

        # Guardar opciones SSL siempre (aunque no cambie el estado enabled)
        domain.force_https  = body.force_https
        domain.hsts_enabled = body.hsts_enabled

        db.commit()
        db.refresh(domain)

        # Regenerar vhost con el nuevo estado SSL
        from scripts import php_ini_manager as phpini
        # Todos los dominios tienen pool dedicado → usar su socket
        php_sock = (phpini.pool_socket_path(domain.domain_name)
                    if phpini.has_pool(domain.domain_name) else None)

        domain_mgr.regenerate_vhost(
            username=owner.username,
            domain_name=domain.domain_name,
            php_version=domain.php_version or "8.2",
            ssl_enabled=domain.ssl_enabled,
            ipv6=domain.ipv6,
            fastcgi_cache_enabled=domain.fastcgi_cache_enabled or False,
            fastcgi_cache_ttl_minutes=domain.fastcgi_cache_ttl_minutes or 60,
            php_socket_override=php_sock,
            template_nginx_extra=domain.template_nginx_extra,
            redirect_to=domain.redirect_to,
            custom_docroot=domain.custom_docroot,
            ipv4=domain.ipv4,
            force_https=domain.force_https,
            hsts=domain.hsts_enabled,
            rate_limit_enabled=domain.rate_limit_enabled or False,
            rate_limit_rps=domain.rate_limit_rps or 10,
            rate_limit_burst=domain.rate_limit_burst or 20,
        )

        return _domain_ssl_response(domain, ssl_manager)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al gestionar SSL: {str(e)}"
        )


@router.post("/domains/{domain_id}/ssl", response_model=SSLResponse, status_code=status.HTTP_201_CREATED)
async def create_ssl(
    domain_id: int,
    ssl: SSLCreate,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Crear certificado SSL para un dominio (legado — usa toggle)"""
    ssl_manager = SSLManager()

    try:
        domain = db.query(Domain).filter(Domain.id == domain_id).first()
        if not domain:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dominio no encontrado")

        ssl_manager.create_ssl(domain.domain_name)

        expiry_date = datetime.utcnow() + timedelta(days=90)
        domain.ssl_enabled    = True
        domain.ssl_certificate = "Let's Encrypt"
        domain.ssl_key         = "Managed by certbot"
        domain.ssl_expires     = expiry_date
        domain.ssl_renewed_at  = datetime.utcnow()

        db.commit()
        db.refresh(domain)

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
async def delete_ssl(
    domain_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Revocar certificado SSL de un dominio"""
    ssl_manager = SSLManager()
    try:
        domain = db.query(Domain).filter(Domain.id == domain_id).first()
        if not domain:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dominio no encontrado")

        ssl_manager.revoke_ssl(domain.domain_name)
        domain.ssl_enabled    = False
        domain.ssl_certificate = None
        domain.ssl_key         = None
        domain.ssl_expires     = None
        db.commit()
        return None
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al revocar certificado SSL: {str(e)}"
        )



@router.post("/domains/{domain_id}/ssl", response_model=SSLResponse, status_code=status.HTTP_201_CREATED)
async def create_ssl(
    domain_id: int,
    ssl: SSLCreate,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Crear certificado SSL para un dominio"""
    ssl_manager = SSLManager()

    try:
        domain = db.query(Domain).filter(Domain.id == domain_id).first()
        if not domain:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dominio no encontrado"
            )

        # Create SSL certificate using certbot
        ssl_manager.create_ssl(ssl.domain_name)

        # Set expiry date (Let's Encrypt certs expire in 90 days)
        expiry_date = datetime.utcnow() + timedelta(days=90)

        domain.ssl_enabled = True
        domain.ssl_certificate = "Let's Encrypt"
        domain.ssl_key = "Managed by certbot"
        domain.ssl_expires = expiry_date
        domain.ssl_renewed_at = datetime.utcnow()

        db.commit()
        db.refresh(domain)

        return {
            "domain_id": domain.id,
            "domain_name": domain.domain_name,
            "ssl_enabled": domain.ssl_enabled,
            "expiry_date": domain.ssl_expires,
            "auto_renewal": True
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al crear certificado SSL: {str(e)}"
        )


@router.get("/domains/{domain_id}/ssl", response_model=SSLResponse)
async def get_ssl(
    domain_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Obtener detalles SSL de un dominio"""
    try:
        domain = db.query(Domain).filter(Domain.id == domain_id).first()
        if not domain:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dominio no encontrado"
            )

        return {
            "domain_id": domain.id,
            "ssl_enabled": domain.ssl_enabled,
            "ssl_expires": domain.ssl_expires,
            "certificate": domain.ssl_certificate[:50] + "..." if domain.ssl_certificate else None,
            "key": domain.ssl_key[:50] + "..." if domain.ssl_key else None
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.delete("/domains/{domain_id}/ssl", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ssl(
    domain_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Revocar certificado SSL de un dominio"""
    ssl_manager = SSLManager()

    try:
        domain = db.query(Domain).filter(Domain.id == domain_id).first()
        if not domain:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dominio no encontrado"
            )

        # Revoke SSL certificate
        ssl_manager.revoke_ssl(domain.domain_name)

        domain.ssl_enabled = False
        domain.ssl_certificate = None
        domain.ssl_key = None
        domain.ssl_expires = None

        db.commit()
        return None
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al revocar certificado SSL: {str(e)}"
        )
