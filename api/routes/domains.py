"""
Rutas API para gestión de dominios
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from api.models.database import get_db
from api.models.models_user import User
from api.models.models_domain import Domain
from api.schemas.domain_schemas import DomainCreate, DomainUpdate, DomainResponse
from api.dependencies import require_admin, require_auth
from scripts.domain_manager import DomainManager

router = APIRouter()


@router.post("/domains", response_model=DomainResponse, status_code=status.HTTP_201_CREATED)
async def create_domain(
    domain: DomainCreate,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Crear un nuevo dominio"""
    domain_manager = DomainManager()

    try:
        user = db.query(User).filter(User.id == domain.user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado"
            )

        # Create domain in system (Nginx, directories, etc)
        domain_manager.create_domain(
            user.username,
            domain.domain_name,
            domain.php_version or "8.2"
        )

        db_domain = Domain(
            user_id=domain.user_id,
            domain_name=domain.domain_name,
            php_version=domain.php_version or "8.2",
            public_html=f"/home/{user.username}/web/{domain.domain_name}/public_html"
        )
        db.add(db_domain)
        db.commit()
        db.refresh(db_domain)

        # Crear zona DNS automáticamente si se solicitó
        if domain.dns_enabled:
            try:
                from api.models.models_dns import DnsZone, DnsRecord
                from api.models.models_settings import Settings
                from api.routes.dns import _build_template_records, _get_server_ipv4
                from scripts.dns_manager import DNSManager

                existing_zone = db.query(DnsZone).filter(
                    DnsZone.domain_name == domain.domain_name
                ).first()

                if not existing_zone:
                    ipv4 = _get_server_ipv4(db)
                    try:
                        dns_mgr = DNSManager()
                        serial = dns_mgr.create_zone(domain.domain_name, ipv4=ipv4)
                    except PermissionError:
                        serial = 2026052501

                    zone = DnsZone(domain_name=domain.domain_name, serial=serial)
                    db.add(zone)
                    db.commit()
                    db.refresh(zone)

                    default_records = _build_template_records(domain.domain_name, ipv4)
                    for r in default_records:
                        db.add(DnsRecord(zone_id=zone.id, **r))
                    db.commit()

                    try:
                        all_zones = [z.domain_name for z in db.query(DnsZone).filter(DnsZone.is_active == True).all()]
                        DNSManager().reload_zone(domain.domain_name, all_zones)
                    except PermissionError:
                        pass
            except Exception:
                pass  # DNS no bloquea la creación del dominio

        return db_domain
    except HTTPException:
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El dominio ya existe"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al crear dominio: {str(e)}"
        )


@router.get("/domains", response_model=list[DomainResponse])
async def list_domains(
    user_id: int = Query(None),
    skip: int = 0,
    limit: int = 10,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Listar dominios según el rol del usuario"""
    try:
        query = db.query(Domain)

        # Filtrar según el rol
        if current_user.role == "admin":
            # Admin ve todos
            if user_id is not None:
                user = db.query(User).filter(User.id == user_id).first()
                if not user:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Usuario no encontrado"
                    )
                query = query.filter(Domain.user_id == user_id)
        elif current_user.role == "reseller":
            # Reseller ve solo sus usuarios y dominios
            # (por ahora, solo ve sus propios dominios - mejora futura)
            query = query.filter(Domain.user_id == current_user.id)
        else:
            # User regular ve solo sus dominios
            query = query.filter(Domain.user_id == current_user.id)

        domains = query.offset(skip).limit(limit).all()
        return domains
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/domains/{domain_id}", response_model=DomainResponse)
async def get_domain(
    domain_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Obtener un dominio por ID"""
    try:
        domain = db.query(Domain).filter(Domain.id == domain_id).first()
        if not domain:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dominio no encontrado"
            )
        return domain
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.put("/domains/{domain_id}", response_model=DomainResponse)
async def update_domain(
    domain_id: int,
    domain_update: DomainUpdate,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Actualizar un dominio"""
    domain_manager = DomainManager()

    try:
        db_domain = db.query(Domain).filter(Domain.id == domain_id).first()
        if not db_domain:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dominio no encontrado"
            )

        if domain_update.php_version is not None and domain_update.php_version != db_domain.php_version:
            # Change PHP version in system
            domain_manager.change_php_version(db_domain.domain_name, domain_update.php_version)
            db_domain.php_version = domain_update.php_version

        if domain_update.is_active is not None:
            db_domain.is_active = domain_update.is_active
        if domain_update.ipv4 is not None:
            db_domain.ipv4 = domain_update.ipv4
        if domain_update.ipv6 is not None:
            db_domain.ipv6 = domain_update.ipv6

        db.commit()
        db.refresh(db_domain)
        return db_domain
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al actualizar dominio: {str(e)}"
        )


@router.delete("/domains/{domain_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_domain(
    domain_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Eliminar un dominio"""
    domain_manager = DomainManager()

    try:
        db_domain = db.query(Domain).filter(Domain.id == domain_id).first()
        if not db_domain:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dominio no encontrado"
            )

        # Obtener username del propietario para borrar el directorio
        owner = db.query(User).filter(User.id == db_domain.user_id).first()
        username = owner.username if owner else None

        # Delete domain from system
        domain_manager.delete_domain(db_domain.domain_name, username=username)

        db.delete(db_domain)
        db.commit()
        return None
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al eliminar dominio: {str(e)}"
        )
