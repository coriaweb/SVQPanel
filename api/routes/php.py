"""
Rutas API para gestión de versiones PHP
"""

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session
from api.models.database import get_db
from api.models.models_user import User
from api.models.models_domain import Domain
from api.dependencies import require_auth, require_admin
from scripts.php_manager import PHPManager, ALL_VERSIONS, DEPRECATED_VERSIONS
from scripts.domain_manager import DomainManager

router = APIRouter()


# ──────────────────────────── Schemas ────────────────────────────────────────

class PHPVersionStatus(BaseModel):
    version: str
    installed: bool
    running: bool
    enabled: bool
    socket: Optional[str] = None
    deprecated: bool = False    # versión sin soporte oficial (EOL)


class PHPVersionsStatusResponse(BaseModel):
    versions: List[PHPVersionStatus]


class PHPVersionsResponse(BaseModel):
    versions: List[str]
    deprecated: List[str] = []   # subconjunto de versions que están EOL


class PHPUpdateRequest(BaseModel):
    php_version: str


# ──────────────────────────── Estado de versiones ────────────────────────────

@router.get("/php/versions/status", response_model=PHPVersionsStatusResponse)
async def get_php_versions_status(
    current_user: User = Depends(require_admin)
):
    """
    [Admin] Obtener estado de todas las versiones PHP:
    instalada, activa (FPM corriendo), habilitada en systemd.
    """
    try:
        manager = PHPManager()
        statuses = manager.get_all_status()
        return {"versions": statuses}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener estado PHP: {str(e)}")


@router.get("/php/versions", response_model=PHPVersionsResponse)
async def get_php_versions(current_user: User = Depends(require_auth)):
    """
    Obtener versiones PHP disponibles (instaladas y corriendo).
    Usadas en los selectores de versión al crear dominios.
    """
    try:
        manager = PHPManager()
        statuses = manager.get_all_status()
        available = [s["version"] for s in statuses if s["running"]]
        # Si no hay ninguna corriendo, devolver todas como fallback (entorno dev)
        if not available:
            available = ALL_VERSIONS
        deprecated = [v for v in available if v in DEPRECATED_VERSIONS]
        return {"versions": available, "deprecated": deprecated}
    except PermissionError:
        # No root — devolver lista estática
        return {"versions": ALL_VERSIONS, "deprecated": DEPRECATED_VERSIONS}
    except Exception:
        # Fallback en caso de error
        return {"versions": ALL_VERSIONS, "deprecated": DEPRECATED_VERSIONS}


# ──────────────────────────── Instalar versión ───────────────────────────────

@router.post("/php/versions/{version}/install")
async def install_php_version(
    version: str,
    current_user: User = Depends(require_admin)
):
    """
    [Admin] Instalar una versión PHP + FPM + extensiones comunes.
    Si ya está instalada, solo habilita y arranca el servicio FPM.
    """
    if version not in ALL_VERSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Versión PHP desconocida: {version}. Versiones soportadas: {', '.join(ALL_VERSIONS)}"
        )
    try:
        manager = PHPManager()
        result = manager.install(version)
        return {
            "success": True,
            "message": f"PHP {version} instalado correctamente",
            "status": result
        }
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al instalar PHP {version}: {str(e)}")


# ──────────────────────────── Habilitar versión ──────────────────────────────

@router.post("/php/versions/{version}/enable")
async def enable_php_version(
    version: str,
    current_user: User = Depends(require_admin)
):
    """
    [Admin] Iniciar y habilitar el servicio PHP-FPM de una versión ya instalada.
    """
    if version not in ALL_VERSIONS:
        raise HTTPException(status_code=400, detail=f"Versión PHP desconocida: {version}")
    try:
        manager = PHPManager()
        if not manager.is_installed(version):
            raise HTTPException(
                status_code=404,
                detail=f"PHP {version} no está instalado. Instálalo primero."
            )
        result = manager.enable(version)
        return {
            "success": True,
            "message": f"PHP {version}-fpm habilitado y arrancado",
            "status": result
        }
    except HTTPException:
        raise
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al habilitar PHP {version}: {str(e)}")


# ──────────────────────────── Deshabilitar versión ───────────────────────────

@router.post("/php/versions/{version}/disable")
async def disable_php_version(
    version: str,
    current_user: User = Depends(require_admin)
):
    """
    [Admin] Parar y deshabilitar el servicio PHP-FPM (los paquetes se mantienen).
    """
    if version not in ALL_VERSIONS:
        raise HTTPException(status_code=400, detail=f"Versión PHP desconocida: {version}")
    try:
        manager = PHPManager()
        if not manager.is_installed(version):
            raise HTTPException(status_code=404, detail=f"PHP {version} no está instalado.")
        result = manager.disable(version)
        return {
            "success": True,
            "message": f"PHP {version}-fpm detenido y deshabilitado",
            "status": result
        }
    except HTTPException:
        raise
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al deshabilitar PHP {version}: {str(e)}")


# ──────────────────────────── Desinstalar versión ────────────────────────────

@router.delete("/php/versions/{version}")
async def uninstall_php_version(
    version: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    [Admin] Desinstalar completamente una versión PHP.
    Verifica antes que no haya dominios activos usando esa versión.
    """
    if version not in ALL_VERSIONS:
        raise HTTPException(status_code=400, detail=f"Versión PHP desconocida: {version}")

    # Verificar que ningún dominio use esta versión
    domains_using = db.query(Domain).filter(Domain.php_version == version).count()
    if domains_using > 0:
        raise HTTPException(
            status_code=409,
            detail=f"No se puede desinstalar PHP {version}: {domains_using} dominio(s) la usan. Cambia su versión PHP primero."
        )

    try:
        manager = PHPManager()
        result = manager.uninstall(version)
        return {
            "success": True,
            "message": f"PHP {version} desinstalado",
            "status": result
        }
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al desinstalar PHP {version}: {str(e)}")


# ──────────────────────────── Extensiones por versión ────────────────────────

@router.get("/php/versions/{version}/extensions")
async def list_php_extensions(
    version: str,
    current_user: User = Depends(require_admin)
):
    """
    [Admin] Todas las extensiones (paquetes php{ver}-*) disponibles en apt para
    una versión, con descripción, si están instaladas y si están protegidas.
    """
    if version not in ALL_VERSIONS:
        raise HTTPException(status_code=400, detail=f"Versión PHP desconocida: {version}")
    try:
        manager = PHPManager()
        return {"version": version, "extensions": manager.list_extensions(version)}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listando extensiones: {e}")


@router.post("/php/versions/{version}/extensions/{ext}")
async def install_php_extension(
    version: str,
    ext: str,
    current_user: User = Depends(require_admin)
):
    """[Admin] Instala el paquete php{ver}-{ext} y recarga FPM."""
    if version not in ALL_VERSIONS:
        raise HTTPException(status_code=400, detail=f"Versión PHP desconocida: {version}")
    try:
        manager = PHPManager()
        manager.install_extension(version, ext)
        return {"success": True, "message": f"php{version}-{ext} instalado"}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error instalando php{version}-{ext}: {e}")


@router.delete("/php/versions/{version}/extensions/{ext}")
async def remove_php_extension(
    version: str,
    ext: str,
    current_user: User = Depends(require_admin)
):
    """[Admin] Desinstala el paquete php{ver}-{ext} (los protegidos no) y recarga FPM."""
    if version not in ALL_VERSIONS:
        raise HTTPException(status_code=400, detail=f"Versión PHP desconocida: {version}")
    try:
        manager = PHPManager()
        manager.remove_extension(version, ext)
        return {"success": True, "message": f"php{version}-{ext} desinstalado"}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error desinstalando php{version}-{ext}: {e}")


# ──────────────────────────── Cambiar PHP de un dominio ──────────────────────

@router.put("/domains/{domain_id}/php")
async def update_domain_php(
    domain_id: int,
    request: PHPUpdateRequest,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Cambiar versión de PHP para un dominio"""
    if request.php_version not in ALL_VERSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Versión PHP inválida. Versiones soportadas: {', '.join(ALL_VERSIONS)}"
        )

    domain = db.query(Domain).filter(Domain.id == domain_id).first()
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")

    # Permisos: admin ve todo, reseller ve los suyos, user ve los suyos
    if current_user.role == "user" and domain.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes permisos sobre este dominio")

    # Verificar que PHP esté instalado y activo
    try:
        php_manager = PHPManager()
        if not php_manager.is_installed(request.php_version):
            raise HTTPException(
                status_code=400,
                detail=f"PHP {request.php_version} no está instalado en el servidor"
            )
        if not php_manager.is_running(request.php_version):
            raise HTTPException(
                status_code=400,
                detail=f"PHP {request.php_version} está instalado pero el servicio FPM no está activo"
            )
    except PermissionError:
        # Sin root (dev) — no validamos
        pass

    # Persistir la versión ANTES de regenerar (el vhost/pool se generan a partir
    # del estado del dominio).
    domain.php_version = request.php_version
    db.commit()
    db.refresh(domain)

    # Cambio REAL de versión:
    #  1) write_pool crea el pool dedicado en la versión nueva y BORRA el de la
    #     vieja (remove_pool except_version) — antes esto no se hacía y el dominio
    #     seguía corriendo con el pool de la versión anterior.
    #  2) regenerate_vhost reescribe el vhost (nginx y/o Apache) apuntando al
    #     socket del pool nuevo. El regex viejo de change_php_version no tocaba el
    #     socket dedicado ni el vhost de Apache.
    try:
        from scripts import php_ini_manager as phpini
        from api.models.models_user import User as _User
        owner = db.query(_User).filter(_User.id == domain.user_id).first()
        overrides = {}
        if domain.php_ini_overrides:
            import json
            try:
                overrides = json.loads(domain.php_ini_overrides) or {}
            except (ValueError, TypeError):
                overrides = {}
        fpm_tuning = None
        if domain.fpm_pool_overrides:
            import json
            try:
                fpm_tuning = json.loads(domain.fpm_pool_overrides)
            except (ValueError, TypeError):
                fpm_tuning = None
        ok, msg = phpini.write_pool(domain.domain_name, request.php_version,
                                    owner.username, overrides,
                                    relax_hardening=bool(domain.php_hardening_relaxed),
                                    fpm_tuning=fpm_tuning)
        if not ok:
            raise HTTPException(status_code=500,
                detail=f"No se pudo crear el pool PHP {request.php_version}: {msg}")
        php_socket = phpini.pool_socket_path(domain.domain_name)
        DomainManager().regenerate_vhost(
            owner.username, domain.domain_name, request.php_version,
            ssl_enabled=domain.ssl_enabled, ipv6=domain.ipv6, ipv4=domain.ipv4,
            php_socket_override=php_socket,
            template_nginx_extra=domain.template_nginx_extra,
            custom_nginx_config=domain.custom_nginx_config,
            custom_apache_config=domain.custom_apache_config,
            redirect_to=domain.redirect_to, custom_docroot=domain.custom_docroot,
            force_https=domain.force_https or False, hsts=domain.hsts_enabled or False,
            canonical_domain=domain.canonical_domain or "www",
        )
    except HTTPException:
        raise
    except PermissionError:
        pass  # Entorno dev sin root
    except Exception as e:
        raise HTTPException(status_code=500,
            detail=f"Versión actualizada en BD pero falló la aplicación: {e}")

    return {
        "status": "success",
        "data": {
            "domain_id": domain.id,
            "domain_name": domain.domain_name,
            "php_version": domain.php_version
        },
        "message": f"Versión PHP actualizada a {request.php_version}"
    }
