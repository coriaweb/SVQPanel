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

router = APIRouter()


@router.post("/domains", response_model=DomainResponse, status_code=status.HTTP_201_CREATED)
async def create_domain(domain: DomainCreate, db: Session = Depends(get_db)):
    """Crear un nuevo dominio"""
    try:
        user = db.query(User).filter(User.id == domain.user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado"
            )

        db_domain = Domain(
            user_id=domain.user_id,
            domain_name=domain.domain_name,
            php_version=domain.php_version or "8.2",
            public_html=f"/home/user/public_html/{domain.domain_name}"
        )
        db.add(db_domain)
        db.commit()
        db.refresh(db_domain)
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
            detail=str(e)
        )


@router.get("/domains", response_model=list[DomainResponse])
async def list_domains(
    user_id: int = Query(None),
    skip: int = 0,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """Listar dominios (filtrar por user_id si se proporciona)"""
    try:
        query = db.query(Domain)

        if user_id is not None:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Usuario no encontrado"
                )
            query = query.filter(Domain.user_id == user_id)

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
async def get_domain(domain_id: int, db: Session = Depends(get_db)):
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
    db: Session = Depends(get_db)
):
    """Actualizar un dominio"""
    try:
        db_domain = db.query(Domain).filter(Domain.id == domain_id).first()
        if not db_domain:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dominio no encontrado"
            )

        if domain_update.php_version is not None:
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
            detail=str(e)
        )


@router.delete("/domains/{domain_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_domain(domain_id: int, db: Session = Depends(get_db)):
    """Eliminar un dominio"""
    try:
        db_domain = db.query(Domain).filter(Domain.id == domain_id).first()
        if not db_domain:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dominio no encontrado"
            )

        db.delete(db_domain)
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
