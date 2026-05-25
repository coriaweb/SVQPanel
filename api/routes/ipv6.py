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
from scripts.ipv6_manager import IPv6Manager

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

    try:
        ipv6_manager.assign_ipv6(interface, data.ipv6_address)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al configurar IPv6 en el sistema: {str(e)}"
        )

    try:
        domain.ipv6 = data.ipv6_address
        db.commit()
        db.refresh(domain)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar IPv6: {str(e)}")

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

    if domain.ipv6:
        interface = _get_interface(db)
        try:
            ipv6_manager.remove_ipv6(interface, domain.ipv6)
        except Exception as e:
            # Log but don't fail — limpiar BD igualmente
            print(f"Warning: no se pudo quitar IPv6 del sistema: {e}")

    domain.ipv6 = None
    db.commit()
    return None
