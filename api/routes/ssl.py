"""
Rutas API para gestión de certificados SSL
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime
from api.models.database import get_db
from api.models.models_domain import Domain
from api.schemas.ssl_schemas import SSLCreate, SSLResponse

router = APIRouter()


@router.post("/domains/{domain_id}/ssl", response_model=SSLResponse, status_code=status.HTTP_201_CREATED)
async def create_ssl(domain_id: int, ssl: SSLCreate, db: Session = Depends(get_db)):
    """Crear certificado SSL para un dominio"""
    try:
        domain = db.query(Domain).filter(Domain.id == domain_id).first()
        if not domain:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dominio no encontrado"
            )

        domain.ssl_enabled = True
        domain.ssl_certificate = ssl.certificate
        domain.ssl_key = ssl.key
        domain.ssl_expires = ssl.expires
        domain.ssl_renewed_at = datetime.utcnow()

        db.commit()
        db.refresh(domain)

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
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/domains/{domain_id}/ssl", response_model=SSLResponse)
async def get_ssl(domain_id: int, db: Session = Depends(get_db)):
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
async def delete_ssl(domain_id: int, db: Session = Depends(get_db)):
    """Revocar certificado SSL de un dominio"""
    try:
        domain = db.query(Domain).filter(Domain.id == domain_id).first()
        if not domain:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dominio no encontrado"
            )

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
            detail=str(e)
        )
