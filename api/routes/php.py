"""
Rutas API para gestión de versiones PHP
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from api.models.database import get_db
from api.models.models_user import User
from api.models.models_domain import Domain
from api.dependencies import require_auth
from scripts.php_manager import PHPManager
from scripts.domain_manager import DomainManager

router = APIRouter()

# Versiones de PHP disponibles
PHP_VERSIONS = ["7.4", "8.0", "8.1", "8.2", "8.3"]


class PHPVersionsResponse(BaseModel):
    versions: list[str]


class PHPUpdateRequest(BaseModel):
    php_version: str


@router.get("/php/versions", response_model=PHPVersionsResponse)
async def get_php_versions(current_user: User = Depends(require_auth)):
    """Obtener versiones de PHP disponibles"""
    return {"versions": PHP_VERSIONS}


@router.put("/domains/{domain_id}/php")
async def update_domain_php(
    domain_id: int,
    request: PHPUpdateRequest,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Cambiar versión de PHP para un dominio"""
    domain_manager = DomainManager()
    php_manager = PHPManager()

    try:
        if request.php_version not in PHP_VERSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Versión PHP inválida. Versiones soportadas: {', '.join(PHP_VERSIONS)}"
            )

        domain = db.query(Domain).filter(Domain.id == domain_id).first()
        if not domain:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dominio no encontrado"
            )

        # Verify PHP version is installed
        if not php_manager.php_version_installed(request.php_version):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"PHP {request.php_version} no está instalado en el servidor"
            )

        # Change PHP version in system
        domain_manager.change_php_version(domain.domain_name, request.php_version)

        domain.php_version = request.php_version
        db.commit()
        db.refresh(domain)

        return {
            "status": "success",
            "data": {
                "domain_id": domain.id,
                "domain_name": domain.domain_name,
                "php_version": domain.php_version
            },
            "message": f"Versión PHP actualizada a {request.php_version}"
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al cambiar PHP: {str(e)}"
        )
