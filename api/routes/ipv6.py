"""
Rutas API para gestión de IPv6
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from api.models.database import get_db
from api.models.models_domain import Domain
from api.schemas.ipv6_schemas import IPv6Create, IPv6Response
from scripts.ipv6_manager import IPv6Manager

router = APIRouter()


@router.post("/domains/{domain_id}/ipv6", response_model=IPv6Response, status_code=status.HTTP_201_CREATED)
async def assign_ipv6(domain_id: int, ipv6: IPv6Create, db: Session = Depends(get_db)):
    """Asignar una dirección IPv6 a un dominio"""
    ipv6_manager = IPv6Manager()

    try:
        domain = db.query(Domain).filter(Domain.id == domain_id).first()
        if not domain:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dominio no encontrado"
            )

        # Assign IPv6 in system
        ipv6_manager.assign_ipv6(
            ipv6.network_interface,
            ipv6.ipv6_address
        )

        domain.ipv6 = ipv6.ipv6_address
        domain.ipv6_interface = ipv6.network_interface

        db.commit()
        db.refresh(domain)

        return {
            "domain_id": domain.id,
            "ipv6_address": domain.ipv6,
            "network_interface": domain.ipv6_interface,
            "is_active": True
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al asignar IPv6: {str(e)}"
        )


@router.get("/domains/{domain_id}/ipv6", response_model=IPv6Response)
async def get_ipv6(domain_id: int, db: Session = Depends(get_db)):
    """Obtener dirección IPv6 de un dominio"""
    try:
        domain = db.query(Domain).filter(Domain.id == domain_id).first()
        if not domain:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dominio no encontrado"
            )

        if not domain.ipv6:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El dominio no tiene IPv6 asignado"
            )

        return {
            "domain_id": domain.id,
            "ipv6_address": domain.ipv6,
            "network_interface": domain.ipv6_interface,
            "is_active": True
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.delete("/domains/{domain_id}/ipv6", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ipv6(domain_id: int, db: Session = Depends(get_db)):
    """Remover dirección IPv6 de un dominio"""
    ipv6_manager = IPv6Manager()

    try:
        domain = db.query(Domain).filter(Domain.id == domain_id).first()
        if not domain:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dominio no encontrado"
            )

        if domain.ipv6:
            # Remove IPv6 from system
            ipv6_manager.remove_ipv6(domain.ipv6_interface, domain.ipv6)

        domain.ipv6 = None
        domain.ipv6_interface = None

        db.commit()
        return None
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al remover IPv6: {str(e)}"
        )
