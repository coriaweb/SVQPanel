"""
Rutas API para gestión de IPv6
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from api.models.database import get_db
from api.models.models_domain import Domain
from api.schemas.ipv6_schemas import IPv6Create, IPv6Response

router = APIRouter()


@router.post("/domains/{domain_id}/ipv6", response_model=IPv6Response, status_code=status.HTTP_201_CREATED)
async def assign_ipv6(domain_id: int, ipv6: IPv6Create, db: Session = Depends(get_db)):
    """Asignar una dirección IPv6 a un dominio"""
    try:
        domain = db.query(Domain).filter(Domain.id == domain_id).first()
        if not domain:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dominio no encontrado"
            )

        domain.ipv6 = ipv6.ipv6

        db.commit()
        db.refresh(domain)

        return {
            "domain_id": domain.id,
            "ipv6": domain.ipv6
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
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
            "ipv6": domain.ipv6
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
