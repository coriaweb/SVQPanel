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

    # 3. Regenerar el vhost preservando TODO el estado del dominio (modo Apache
    #    incluido). Usamos el regenerador completo, NO update_nginx_ipv6, que
    #    perdía proxy_to_apache y el resto de directivas → rompía el dominio en
    #    modo Apache+Nginx al asignar IPv6.
    try:
        from api.routes.domains import _regenerate_domain_vhost
        _regenerate_domain_vhost(domain, owner)
    except Exception as e:
        # nginx falló pero la IP ya está asignada — avisar pero no revertir
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"IPv6 asignada pero error al actualizar el vhost: {str(e)}"
        )

    # 4. Sincronizar AAAA en la zona DNS (si el panel la gestiona). No-op si el
    #    dominio usa DNS externo. No revertimos la asignación si esto falla.
    try:
        from api.routes.dns import sync_aaaa_records_for_domain
        sync_aaaa_records_for_domain(domain.domain_name, data.ipv6_address, db)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            f"IPv6 asignada pero no se pudo sincronizar AAAA en DNS: {e}")

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

        # 2. Poner ipv6=None ANTES de regenerar (el regenerador lee domain.ipv6)
        domain.ipv6 = None
        db.commit()
        db.refresh(domain)

        # 3. Regenerar el vhost SIN IPv6, preservando el resto (modo Apache incl.)
        if owner:
            try:
                from api.routes.domains import _regenerate_domain_vhost
                _regenerate_domain_vhost(domain, owner)
            except Exception as e:
                print(f"Warning: no se pudo actualizar el vhost: {e}")

        # 4. Quitar los AAAA de la zona DNS (no-op si DNS externo).
        try:
            from api.routes.dns import sync_aaaa_records_for_domain
            sync_aaaa_records_for_domain(domain.domain_name, None, db)
        except Exception as e:
            print(f"Warning: no se pudieron quitar los AAAA del DNS: {e}")
    else:
        domain.ipv6 = None
        db.commit()
    return None
