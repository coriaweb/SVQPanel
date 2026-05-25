"""
Rutas API para gestión de IPv6
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from api.models.database import get_db
from api.models.models_user import User
from api.models.models_domain import Domain
from api.schemas.ipv6_schemas import IPv6Assign, IPv6Response
from api.dependencies import require_auth
from api.models.models_user import User as UserModel
from scripts.ipv6_manager import IPv6Manager
from scripts.domain_manager import DomainManager

router = APIRouter()


def _get_interface(db: Session, override: str = None) -> str:
    """Devuelve la interfaz a usar: override > settings > eth0"""
    if override:
        return override
    try:
        from api.models.models_settings import Settings
        s = db.query(Settings).filter(Settings.id == 1).first()
        if s and s.network_interface:
            return s.network_interface
    except Exception:
        pass
    return "eth0"


@router.post("/domains/{domain_id}/ipv6", response_model=IPv6Response, status_code=status.HTTP_201_CREATED)
async def assign_ipv6(
    domain_id: int,
    data: IPv6Assign,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Asignar una dirección IPv6 a un dominio"""
    ipv6_manager = IPv6Manager()

    domain = db.query(Domain).filter(Domain.id == domain_id).first()
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")

    interface = _get_interface(db, data.network_interface)

    # Obtener usuario propietario del dominio
    owner = db.query(UserModel).filter(UserModel.id == domain.user_id).first()
    if not owner:
        raise HTTPException(status_code=404, detail="Propietario del dominio no encontrado")

    # 1. Añadir IPv6 a la interfaz de red
    try:
        ipv6_manager.assign_ipv6(interface, data.ipv6_address)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al añadir IPv6 a la interfaz: {str(e)}"
        )

    # 2. Guardar en BD
    try:
        domain.ipv6 = data.ipv6_address
        db.commit()
        db.refresh(domain)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar IPv6: {str(e)}")

    # 3. Regenerar nginx con la IPv6 para que escuche en esa IP
    try:
        domain_manager = DomainManager()
        domain_manager.update_nginx_ipv6(
            username=owner.username,
            domain_name=domain.domain_name,
            php_version=domain.php_version or "8.2",
            ipv6_address=data.ipv6_address,
            ssl_enabled=domain.ssl_enabled or False
        )
    except Exception as e:
        # nginx falló pero la IP ya está asignada — avisar pero no revertir
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"IPv6 asignada pero error al actualizar nginx: {str(e)}"
        )

    return IPv6Response(
        domain_id=domain.id,
        ipv6_address=domain.ipv6,
        network_interface=interface,
        is_active=True
    )


@router.get("/domains/{domain_id}/ipv6", response_model=IPv6Response)
async def get_ipv6(
    domain_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Obtener dirección IPv6 de un dominio"""
    domain = db.query(Domain).filter(Domain.id == domain_id).first()
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")

    if not domain.ipv6:
        raise HTTPException(status_code=404, detail="El dominio no tiene IPv6 asignado")

    interface = _get_interface(db)
    return IPv6Response(
        domain_id=domain.id,
        ipv6_address=domain.ipv6,
        network_interface=interface,
        is_active=True
    )


@router.delete("/domains/{domain_id}/ipv6", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ipv6(
    domain_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Remover dirección IPv6 de un dominio"""
    ipv6_manager = IPv6Manager()

    domain = db.query(Domain).filter(Domain.id == domain_id).first()
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")

    owner = db.query(UserModel).filter(UserModel.id == domain.user_id).first()
    interface = _get_interface(db)

    if domain.ipv6:
        # 1. Quitar IPv6 de la interfaz
        try:
            ipv6_manager.remove_ipv6(interface, domain.ipv6)
        except Exception as e:
            print(f"Warning: no se pudo quitar IPv6 del sistema: {e}")

        # 2. Regenerar nginx sin IPv6
        if owner:
            try:
                domain_manager = DomainManager()
                domain_manager.update_nginx_ipv6(
                    username=owner.username,
                    domain_name=domain.domain_name,
                    php_version=domain.php_version or "8.2",
                    ipv6_address=None,
                    ssl_enabled=domain.ssl_enabled or False
                )
            except Exception as e:
                print(f"Warning: no se pudo actualizar nginx: {e}")

    domain.ipv6 = None
    db.commit()
    return None
