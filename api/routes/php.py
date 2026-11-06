"""
Rutas API para gestión de versiones PHP
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status, BackgroundTasks
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

class PHPDomainRef(BaseModel):
    id: int
    name: str


class PHPVersionStatus(BaseModel):
    version: str
    installed: bool
    running: bool
    enabled: bool
    socket: Optional[str] = None
    deprecated: bool = False           # versión sin soporte oficial (EOL)
    domains_count: int = 0             # nº de dominios que usan esta versión
    domains: List[PHPDomainRef] = []   # cuáles (para saber a quién migrar)


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
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    [Admin] Obtener estado de todas las versiones PHP: instalada, activa (FPM
    corriendo), habilitada en systemd, y qué dominios usan cada versión
    (para saber a quién migrar antes de actualizar/desinstalar una versión).
    """
    try:
        manager = PHPManager()
        statuses = manager.get_all_status()
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener estado PHP: {str(e)}")

    # Dominios por versión (los solo-correo/DNS no corren PHP: fuera)
    usage = {}
    try:
        rows = (db.query(Domain.php_version, Domain.id, Domain.domain_name)
                  .filter(Domain.mail_dns_only.isnot(True))
                  .order_by(Domain.domain_name).all())
        for ver, did, name in rows:
            usage.setdefault(ver, []).append({"id": did, "name": name})
    except Exception:
        pass  # sin BD (dev): solo estado del sistema
    for s in statuses:
        refs = usage.get(s["version"], [])
        s["domains_count"] = len(refs)
        s["domains"] = refs

    return {"versions": statuses}


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


# ──────────────────────────── Límites globales (php.ini) ─────────────────────

class PHPLimitsUpdate(BaseModel):
    limits: dict


def _domains_on(db: Session, version: str):
    return (db.query(Domain).filter(Domain.php_version == version)
              .filter(Domain.mail_dns_only.isnot(True))
              .order_by(Domain.domain_name).all())


def _above_new_limits(db: Session, version: str, limits: dict) -> list:
    """Dominios con un valor PROPIO por encima del global (lo conservan: el
    pool lo fija con php_admin_value, pero ya no podrían volver a guardarlo)."""
    import json
    from scripts.php_ini_manager import parse_php_size
    from scripts.php_manager import GLOBAL_LIMITS
    is_size = {k: t == "size" for k, t, *_ in GLOBAL_LIMITS}
    out = []
    for d in _domains_on(db, version):
        try:
            ov = json.loads(d.php_ini_overrides) if d.php_ini_overrides else {}
        except (ValueError, TypeError):
            continue
        over = []
        for key, val in limits.items():
            mine = ov.get(key)
            if mine is None:
                continue
            try:
                bigger = (parse_php_size(mine) > parse_php_size(val)) if is_size.get(key) \
                    else int(mine) > int(val)
            except (ValueError, TypeError):
                continue
            if bigger:
                over.append(f"{key}={mine}")
        if over:
            out.append({"id": d.id, "name": d.domain_name, "values": over})
    return out


def _regen_vhosts_async(version: str) -> bool:
    """Regenera en segundo plano los vhosts de esa versión (client_max_body_size
    de nginx). En una unidad systemd propia, no en un hilo del panel (con 1
    worker, un hilo colgado lo tumba todo)."""
    import subprocess
    import time
    cmd = ["/opt/svqpanel/venv/bin/python", "-m", "api.cli", "regenerate_all_vhosts",
           "--php-version", version]
    try:
        r = subprocess.run(["systemd-run", "--no-block", "--collect", "--quiet",
                            f"--unit=svqpanel-regen-php{version.replace('.', '')}-{int(time.time())}",
                            "--working-directory=/opt/svqpanel"] + cmd,
                           capture_output=True, text=True, timeout=20)
        return r.returncode == 0
    except Exception:
        return False


@router.get("/php/versions/{version}/limits")
async def get_php_global_limits(
    version: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """[Admin] Límites globales del php.ini de FPM de una versión: el techo que
    cada dominio puede pedir y lo que heredan los dominios sin valor propio."""
    import os
    from scripts.php_manager import GLOBAL_LIMITS, read_global_limits
    if version not in ALL_VERSIONS:
        raise HTTPException(status_code=400, detail=f"Versión PHP desconocida: {version}")
    if not os.path.isfile(f"/etc/php/{version}/fpm/php.ini"):
        raise HTTPException(status_code=404, detail=f"PHP {version} no está instalado")
    domains = _domains_on(db, version)
    return {
        "version": version,
        "limits": read_global_limits(version),
        "spec": [{"key": k, "type": t, "min": mn, "max": mx, "label": lbl}
                 for k, t, mn, mx, lbl, _ in GLOBAL_LIMITS],
        "domains_count": len(domains),
    }


@router.put("/php/versions/{version}/limits")
async def set_php_global_limits(
    version: str,
    payload: PHPLimitsUpdate,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """[Admin] Cambia los límites globales del php.ini de FPM de una versión.
    Valida, comprueba con php-fpm -t (deshace si falla) y recarga FPM. Si cambia
    la subida/POST, regenera en segundo plano los vhosts de esa versión (nginx)."""
    import os
    from scripts.php_manager import (validate_global_limits, check_limits_coherence,
                                     read_global_limits, set_global_limits)
    from api.utils.security_audit import log_audit
    if version not in ALL_VERSIONS:
        raise HTTPException(status_code=400, detail=f"Versión PHP desconocida: {version}")
    if not os.path.isfile(f"/etc/php/{version}/fpm/php.ini"):
        raise HTTPException(status_code=404, detail=f"PHP {version} no está instalado")

    values, errors = validate_global_limits(payload.limits)
    current = read_global_limits(version)
    errors += check_limits_coherence({**current, **values})
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    values = {k: v for k, v in values.items() if current.get(k) != v}
    if not values:
        return {"success": True, "changes": [], "limits": current,
                "message": "No había nada que cambiar"}

    try:
        changes = set_global_limits(version, values)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"No se pudo escribir el php.ini: {e}")

    log_audit(db, user=current_user, category="php", action="global_limits",
              target=f"PHP {version}: " + "; ".join(changes), request=request)

    regen = False
    if {"upload_max_filesize", "post_max_size"} & set(values) and _domains_on(db, version):
        regen = _regen_vhosts_async(version)
    return {
        "success": True,
        "changes": changes,
        "limits": read_global_limits(version),
        "regenerating_vhosts": regen,
        "domains_above": _above_new_limits(db, version, values),
        "message": f"Límites de PHP {version} actualizados",
    }


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

    # Permisos: admin todo, reseller los suyos y los de sus clientes, user los suyos.
    # (Antes solo se comprobaba al rol "user": un reseller podía cambiar el PHP de
    # CUALQUIER dominio del servidor.)
    from api.utils.scope import can_manage_owner
    if not can_manage_owner(db, current_user, domain.user_id):
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

    # Si el dominio tiene el wp-cron optimizado, su CronJob lleva el PHP con el
    # que se creó. Sin esto se queda en la versión vieja y, si esa ya no cumple
    # el mínimo de WordPress, el wp-cron del sitio deja de ejecutarse EN SILENCIO
    # (con DISABLE_WP_CRON=true tampoco dispara por visitas).
    from scripts import wp_manager as _wpm
    _wpm.sync_wp_cron_php(domain, db)

    return {
        "status": "success",
        "data": {
            "domain_id": domain.id,
            "domain_name": domain.domain_name,
            "php_version": domain.php_version
        },
        "message": f"Versión PHP actualizada a {request.php_version}"
    }
