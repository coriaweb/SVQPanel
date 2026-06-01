"""
Rutas API para gestión de dominios
"""

import os
import socket
import tarfile
import tempfile
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from api.models.database import get_db
from api.models.models_user import User
from api.models.models_domain import Domain
from api.schemas.domain_schemas import DomainCreate, DomainUpdate, DomainResponse
from api.dependencies import require_admin, require_auth
from scripts.domain_manager import DomainManager
from scripts.domain_suspend_manager import DomainSuspendManager
from scripts.utils import get_domain_root

router = APIRouter()


def _get_owned_domain(domain_id: int, db: Session, current_user: User) -> Domain:
    """
    Carga un dominio verificando que el usuario actual tiene acceso a él.
    Evita IDOR: admin ve todos; reseller ve los de sus clientes (parent_id);
    usuario normal solo los suyos. Devuelve 404 si no existe o no es accesible
    (404, no 403, para no revelar la existencia de dominios ajenos).
    """
    _dom = db.query(Domain).filter(Domain.id == domain_id).first()
    if not _dom:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dominio no encontrado")

    role = getattr(current_user, "role", None)
    if role == "admin":
        return _dom
    if role == "reseller":
        client_ids = [u.id for u in db.query(User.id).filter(User.parent_id == current_user.id).all()]
        client_ids.append(current_user.id)
        if _dom.user_id in client_ids:
            return _dom
    elif _dom.user_id == current_user.id:
        return _dom

    # No accesible → 404 (no filtramos existencia de dominios de otros)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dominio no encontrado")


def _apply_builtin_template(domain, slug: str, owner, db: Session):
    """Aplica una plantilla web builtin (por slug) a un dominio y commitea."""
    from api.models.models_template import WebTemplate
    from scripts.template_manager import TemplateManager

    tpl = db.query(WebTemplate).filter(WebTemplate.slug == slug).first()
    if not tpl:
        raise RuntimeError(f"Plantilla '{slug}' no encontrada")
    res = TemplateManager().apply_template(
        domain_row=domain, template_row=tpl, username=owner.username,
    )
    if res.get("status") != "success":
        raise RuntimeError(res.get("error") or "fallo aplicando plantilla")
    db.commit()
    return res


def _get_reserved_domains():
    """Dominios reservados que no se pueden registrar como dominios web"""
    reserved = {"localhost", "localhost.localdomain"}
    try:
        fqdn = socket.getfqdn()
        hostname = socket.gethostname()
        if fqdn:
            reserved.add(fqdn.lower())
        if hostname:
            reserved.add(hostname.lower())
    except Exception:
        pass
    return reserved


@router.post("/domains", response_model=DomainResponse, status_code=status.HTTP_201_CREATED)
async def create_domain(
    domain: DomainCreate,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Crear un nuevo dominio"""
    domain_manager = DomainManager()

    # Protección: no permitir el hostname del servidor como dominio web
    reserved = _get_reserved_domains()
    if domain.domain_name.lower() in reserved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{domain.domain_name}' es el hostname del servidor y no puede usarse como dominio web"
        )

    try:
        user = db.query(User).filter(User.id == domain.user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado"
            )

        # Validar límite de dominios del usuario (0 = sin límite)
        if user.domains_limit and user.domains_limit > 0:
            current_count = db.query(Domain).filter(Domain.user_id == user.id).count()
            if current_count >= user.domains_limit:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        f"Límite de dominios alcanzado ({current_count}/{user.domains_limit}). "
                        f"Elimina un dominio o sube el plan del usuario."
                    ),
                )

        # Create domain in system (Nginx, directories, etc)
        domain_manager.create_domain(
            user.username,
            domain.domain_name,
            domain.php_version or "8.2"
        )

        db_domain = Domain(
            user_id=domain.user_id,
            domain_name=domain.domain_name,
            php_version=domain.php_version or "8.2",
            public_html=f"/home/{user.username}/web/{domain.domain_name}/public_html"
        )
        db.add(db_domain)
        db.commit()
        db.refresh(db_domain)

        # Crear zona DNS automáticamente si se solicitó
        if domain.dns_enabled:
            try:
                from api.models.models_dns import DnsZone, DnsRecord
                from api.models.models_settings import Settings
                from api.routes.dns import _build_template_records, _get_server_ipv4
                from scripts.dns_manager import DNSManager

                existing_zone = db.query(DnsZone).filter(
                    DnsZone.domain_name == domain.domain_name
                ).first()

                if not existing_zone:
                    ipv4 = _get_server_ipv4(db)
                    try:
                        dns_mgr = DNSManager()
                        serial = dns_mgr.create_zone(domain.domain_name, ipv4=ipv4)
                    except PermissionError:
                        serial = 2026052501

                    zone = DnsZone(domain_name=domain.domain_name, serial=serial)
                    db.add(zone)
                    db.commit()
                    db.refresh(zone)

                    default_records = _build_template_records(domain.domain_name, ipv4)
                    for r in default_records:
                        db.add(DnsRecord(zone_id=zone.id, **r))
                    db.commit()

                    try:
                        all_zones = [z.domain_name for z in db.query(DnsZone).filter(DnsZone.is_active == True).all()]
                        DNSManager().reload_zone(domain.domain_name, all_zones)
                    except PermissionError:
                        pass
            except Exception:
                pass  # DNS no bloquea la creación del dominio

        # Crear dominio de correo si se solicitó y el módulo está activo
        if domain.mail_enabled:
            import os
            if os.getenv("MAIL_ENABLED", "false").lower() == "true":
                try:
                    from api.models.models_mail import MailDomain
                    from scripts.mail_manager import MailManager
                    existing_mail = db.query(MailDomain).filter(
                        MailDomain.domain_name == domain.domain_name
                    ).first()
                    if not existing_mail:
                        mail_domain = MailDomain(
                            user_id=domain.user_id,
                            domain_id=db_domain.id,
                            domain_name=domain.domain_name,
                        )
                        db.add(mail_domain)
                        db.commit()
                        try:
                            MailManager().create_mail_domain(domain.domain_name, user.username)
                        except PermissionError:
                            pass
                except Exception:
                    pass  # Correo no bloquea la creación del dominio

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
            detail=f"Error al crear dominio: {str(e)}"
        )


@router.get("/domains", response_model=list[DomainResponse])
async def list_domains(
    user_id: int = Query(None),
    skip: int = 0,
    limit: int = 10,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Listar dominios según el rol del usuario"""
    try:
        query = db.query(Domain)

        # Filtrar según el rol
        if current_user.role == "admin":
            # Admin ve todos
            if user_id is not None:
                user = db.query(User).filter(User.id == user_id).first()
                if not user:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Usuario no encontrado"
                    )
                query = query.filter(Domain.user_id == user_id)
        elif current_user.role == "reseller":
            # Reseller ve solo sus usuarios y dominios
            # (por ahora, solo ve sus propios dominios - mejora futura)
            query = query.filter(Domain.user_id == current_user.id)
        else:
            # User regular ve solo sus dominios
            query = query.filter(Domain.user_id == current_user.id)

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
async def get_domain(
    domain_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Obtener un dominio por ID"""
    try:
        domain = _get_owned_domain(domain_id, db, current_user)
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
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Actualizar un dominio"""
    domain_manager = DomainManager()

    try:
        db_domain = _get_owned_domain(domain_id, db, current_user)
        if not db_domain:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dominio no encontrado"
            )

        if domain_update.php_version is not None and domain_update.php_version != db_domain.php_version:
            # Change PHP version in system
            domain_manager.change_php_version(db_domain.domain_name, domain_update.php_version)
            db_domain.php_version = domain_update.php_version

            # Recrear SIEMPRE el pool dedicado en la nueva versión (todos los
            # dominios tienen pool con el bloque de seguridad). write_pool hace
            # remove_pool(except_version) → migra de versión. El socket no cambia
            # de ruta, así que el vhost no necesita tocarse para el socket.
            import json
            from scripts import php_ini_manager as phpini
            owner = db.query(User).filter(User.id == db_domain.user_id).first()
            try:
                overrides = json.loads(db_domain.php_ini_overrides) if db_domain.php_ini_overrides else {}
            except (ValueError, TypeError):
                overrides = {}
            if owner:
                phpini.write_pool(db_domain.domain_name, db_domain.php_version,
                                  owner.username, overrides,
                                  relax_hardening=db_domain.php_hardening_relaxed or False)

        if domain_update.is_active is not None:
            db_domain.is_active = domain_update.is_active

        ipv4_changed = False
        if 'ipv4' in domain_update.model_fields_set:
            new_ipv4 = domain_update.ipv4 or None
            if new_ipv4 != db_domain.ipv4:
                db_domain.ipv4 = new_ipv4
                ipv4_changed = True
        if domain_update.ipv6 is not None:
            db_domain.ipv6 = domain_update.ipv6

        # Redirección y docroot personalizado (Fase 16)
        # Se aceptan strings vacíos para "borrar" el valor
        redir_changed   = False
        docroot_changed = False
        if 'redirect_to' in domain_update.model_fields_set:
            new_redir = domain_update.redirect_to or None
            if new_redir != db_domain.redirect_to:
                db_domain.redirect_to = new_redir
                redir_changed = True
        if 'custom_docroot' in domain_update.model_fields_set:
            new_docroot = domain_update.custom_docroot or None
            if new_docroot != db_domain.custom_docroot:
                db_domain.custom_docroot = new_docroot
                docroot_changed = True

        db.commit()
        db.refresh(db_domain)

        # Regenerar vhost si cambió algún parámetro que afecta a nginx
        if redir_changed or docroot_changed or ipv4_changed:
            owner = db.query(User).filter(User.id == db_domain.user_id).first()
            if owner:
                try:
                    from scripts import php_ini_manager as phpini
                    # Todos los dominios tienen pool dedicado → usar su socket
                    php_sock = (phpini.pool_socket_path(db_domain.domain_name)
                                if phpini.has_pool(db_domain.domain_name) else None)
                    domain_manager.regenerate_vhost(
                        username=owner.username,
                        domain_name=db_domain.domain_name,
                        php_version=db_domain.php_version or "8.2",
                        ssl_enabled=db_domain.ssl_enabled or False,
                        ipv6=db_domain.ipv6,
                        fastcgi_cache_enabled=db_domain.fastcgi_cache_enabled or False,
                        fastcgi_cache_ttl_minutes=db_domain.fastcgi_cache_ttl_minutes or 60,
                        php_socket_override=php_sock,
                        template_nginx_extra=db_domain.template_nginx_extra,
                        redirect_to=db_domain.redirect_to,
                        custom_docroot=db_domain.custom_docroot,
                        ipv4=db_domain.ipv4,
                        force_https=db_domain.force_https or False,
                        hsts=db_domain.hsts_enabled or False,
                        rate_limit_enabled=db_domain.rate_limit_enabled or False,
                        rate_limit_rps=db_domain.rate_limit_rps or 10,
                        rate_limit_burst=db_domain.rate_limit_burst or 20,
                    )
                except Exception as vhost_err:
                    # No bloquear la respuesta si falla nginx (log del error)
                    import logging
                    logging.getLogger(__name__).warning(
                        f"regenerate_vhost falló para {db_domain.domain_name}: {vhost_err}"
                    )

        # Actualizar IP de salida SMTP en Postfix si cambió la IPv4
        if ipv4_changed:
            try:
                from scripts import mail_manager as mail_mod
                mm = mail_mod.MailManager()
                if mm.mail_available():
                    if db_domain.ipv4:
                        mm.set_domain_sender_ip(db_domain.domain_name, db_domain.ipv4)
                    else:
                        mm.remove_domain_sender_ip(db_domain.domain_name)
            except Exception as mail_err:
                import logging
                logging.getLogger(__name__).warning(
                    f"set_domain_sender_ip falló para {db_domain.domain_name}: {mail_err}"
                )

        return db_domain
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al actualizar dominio: {str(e)}"
        )


@router.delete("/domains/{domain_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_domain(
    domain_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Eliminar un dominio"""
    domain_manager = DomainManager()

    try:
        db_domain = _get_owned_domain(domain_id, db, current_user)
        if not db_domain:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dominio no encontrado"
            )

        # Obtener username del propietario para borrar el directorio
        owner = db.query(User).filter(User.id == db_domain.user_id).first()
        username = owner.username if owner else None

        # Si tiene IPv6, quitarla de la interfaz de red antes de borrar
        if db_domain.ipv6:
            try:
                from scripts.ipv6_manager import IPv6Manager
                from api.models.models_settings import Settings
                settings = db.query(Settings).filter(Settings.id == 1).first()
                interface = (settings.network_interface if settings and settings.network_interface else "eth0")
                IPv6Manager().remove_ipv6(interface, db_domain.ipv6)
            except Exception as e:
                # No bloqueamos el borrado si falla quitar la IPv6
                print(f"Warning: no se pudo quitar IPv6 {db_domain.ipv6} de la interfaz: {e}")

        # Delete domain from system (nginx config + directorios)
        domain_manager.delete_domain(db_domain.domain_name, username=username)

        # Limpiar pool PHP dedicado y zona de cache si existían
        try:
            from scripts import php_ini_manager as phpini
            from scripts.utils import remove_fastcgi_cache_zone
            phpini.remove_pool(db_domain.domain_name)
            remove_fastcgi_cache_zone(db_domain.domain_name)
        except Exception as e:
            print(f"Warning: limpieza pool/cache de {db_domain.domain_name}: {e}")

        db.delete(db_domain)
        db.commit()
        return None
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al eliminar dominio: {str(e)}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Logs y disco por dominio (Fase 13.3)
# ─────────────────────────────────────────────────────────────────────────────
def _domain_owner_dir(domain: Domain, db: Session) -> str:
    """Devuelve /home/{owner}/web/{dominio}"""
    owner = db.query(User).filter(User.id == domain.user_id).first()
    if not owner:
        raise HTTPException(status_code=404, detail="Propietario del dominio no encontrado")
    return f"/home/{owner.username}/web/{domain.domain_name}"


def _check_access(current_user: User, domain: Domain, db: Session) -> None:
    if current_user.role == "admin":
        return
    if domain.user_id == current_user.id:
        return
    if current_user.role == "reseller":
        owner = db.query(User).filter(User.id == domain.user_id).first()
        if owner and owner.parent_id == current_user.id:
            return
    raise HTTPException(status_code=403, detail="No tienes acceso a este dominio")


@router.get("/domains/{domain_id}/logs")
async def get_domain_logs(
    domain_id:   int,
    log_type:    str = Query("access", pattern="^(access|error)$", alias="type"),
    lines:       int = Query(200, ge=1, le=5000),
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """
    Devuelve las últimas N líneas del log nginx (access o error) del dominio.
    Path: /home/{user}/web/{dominio}/logs/nginx.{access|error}.log
    """
    import os
    from collections import deque

    domain = _get_owned_domain(domain_id, db, current_user)
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    _check_access(current_user, domain, db)

    base = _domain_owner_dir(domain, db)
    log_path = os.path.join(base, "logs", f"nginx.{log_type}.log")

    if not os.path.isfile(log_path):
        return {
            "domain":   domain.domain_name,
            "type":     log_type,
            "path":     log_path,
            "exists":   False,
            "lines":    [],
            "message":  "El archivo de log aún no existe (sin tráfico todavía)",
        }

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            tail = deque(f, maxlen=lines)
        return {
            "domain":   domain.domain_name,
            "type":     log_type,
            "path":     log_path,
            "exists":   True,
            "lines":    [l.rstrip("\n") for l in tail],
            "count":    len(tail),
        }
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Error leyendo log: {e}")


@router.put("/domains/{domain_id}/cache")
async def set_domain_cache(
    domain_id:   int,
    payload:     dict,
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """
    Activa/desactiva FastCGI cache para un dominio.
    Body: {"enabled": bool, "ttl_minutes": int}
    """
    enabled = bool(payload.get("enabled", False))
    ttl_minutes = int(payload.get("ttl_minutes") or 60)
    if ttl_minutes < 1 or ttl_minutes > 1440:
        raise HTTPException(status_code=400, detail="ttl_minutes fuera de rango (1-1440)")

    domain = _get_owned_domain(domain_id, db, current_user)
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    _check_access(current_user, domain, db)

    owner = db.query(User).filter(User.id == domain.user_id).first()
    if not owner:
        raise HTTPException(status_code=500, detail="Propietario del dominio no encontrado")

    # Si el dominio tiene php.ini propio, preservar su socket dedicado
    from scripts import php_ini_manager as phpini
    php_socket = phpini.pool_socket_path(domain.domain_name) if phpini.has_pool(domain.domain_name) else None

    try:
        DomainManager().set_fastcgi_cache(
            username=owner.username,
            domain_name=domain.domain_name,
            php_version=domain.php_version,
            enabled=enabled,
            ttl_minutes=ttl_minutes,
            ssl_enabled=domain.ssl_enabled,
            ipv6=domain.ipv6,
            php_socket_override=php_socket,
            ipv4=domain.ipv4,
            force_https=domain.force_https or False,
            hsts=domain.hsts_enabled or False,
            rate_limit_enabled=domain.rate_limit_enabled or False,
            rate_limit_rps=domain.rate_limit_rps or 10,
            rate_limit_burst=domain.rate_limit_burst or 20,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error aplicando cache: {e}")

    domain.fastcgi_cache_enabled = enabled
    domain.fastcgi_cache_ttl_minutes = ttl_minutes
    db.commit()
    db.refresh(domain)
    return {
        "status": "ok",
        "domain": domain.domain_name,
        "fastcgi_cache_enabled": domain.fastcgi_cache_enabled,
        "fastcgi_cache_ttl_minutes": domain.fastcgi_cache_ttl_minutes,
    }


@router.put("/domains/{domain_id}/rate-limit")
async def set_domain_rate_limit(
    domain_id:    int,
    payload:      dict,
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """
    Activa/desactiva el rate limiting (anti-abuso) de un dominio.
    Body: {"enabled": bool, "rps": int, "burst": int}. Al superar el límite,
    nginx responde 429.
    """
    enabled = bool(payload.get("enabled", False))
    rps   = int(payload.get("rps")   or 10)
    burst = int(payload.get("burst") or 20)
    if rps < 1 or rps > 1000:
        raise HTTPException(status_code=400, detail="rps fuera de rango (1-1000)")
    if burst < 0 or burst > 1000:
        raise HTTPException(status_code=400, detail="burst fuera de rango (0-1000)")

    domain = _get_owned_domain(domain_id, db, current_user)
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    _check_access(current_user, domain, db)

    owner = db.query(User).filter(User.id == domain.user_id).first()
    if not owner:
        raise HTTPException(status_code=500, detail="Propietario del dominio no encontrado")

    from scripts import php_ini_manager as phpini
    php_socket = phpini.pool_socket_path(domain.domain_name) if phpini.has_pool(domain.domain_name) else None

    try:
        DomainManager().regenerate_vhost(
            username=owner.username,
            domain_name=domain.domain_name,
            php_version=domain.php_version,
            ssl_enabled=domain.ssl_enabled,
            ipv6=domain.ipv6,
            fastcgi_cache_enabled=domain.fastcgi_cache_enabled,
            fastcgi_cache_ttl_minutes=domain.fastcgi_cache_ttl_minutes,
            php_socket_override=php_socket,
            template_nginx_extra=domain.template_nginx_extra,
            redirect_to=domain.redirect_to,
            custom_docroot=domain.custom_docroot,
            ipv4=domain.ipv4,
            force_https=domain.force_https or False,
            hsts=domain.hsts_enabled or False,
            rate_limit_enabled=enabled,
            rate_limit_rps=rps,
            rate_limit_burst=burst,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error aplicando rate limit: {e}")

    domain.rate_limit_enabled = enabled
    domain.rate_limit_rps     = rps
    domain.rate_limit_burst   = burst
    db.commit()
    db.refresh(domain)
    return {
        "status": "ok",
        "domain": domain.domain_name,
        "rate_limit_enabled": domain.rate_limit_enabled,
        "rate_limit_rps":     domain.rate_limit_rps,
        "rate_limit_burst":   domain.rate_limit_burst,
    }


@router.post("/domains/{domain_id}/cache/purge")
async def purge_domain_cache(
    domain_id:   int,
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """Vacía el directorio de cache FastCGI del dominio."""
    from scripts.utils import purge_fastcgi_cache

    domain = _get_owned_domain(domain_id, db, current_user)
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    _check_access(current_user, domain, db)

    freed = purge_fastcgi_cache(domain.domain_name)
    return {
        "status":      "purged",
        "domain":      domain.domain_name,
        "freed_bytes": freed,
        "freed_mb":    freed // (1024 * 1024),
    }


@router.get("/domains/{domain_id}/php-config")
async def get_domain_php_config(
    domain_id:   int,
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """
    Devuelve los overrides php.ini actuales del dominio, los valores por
    defecto del servidor y el catálogo de directivas editables.
    """
    import json
    from scripts import php_ini_manager as phpini

    domain = _get_owned_domain(domain_id, db, current_user)
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    _check_access(current_user, domain, db)

    overrides = {}
    if domain.php_ini_overrides:
        try:
            overrides = json.loads(domain.php_ini_overrides)
        except (ValueError, TypeError):
            overrides = {}

    return {
        "domain":        domain.domain_name,
        "php_version":   domain.php_version,
        "overrides":     overrides,
        "server_defaults": phpini.server_defaults(domain.php_version),
        "directives":    phpini.PHP_INI_DIRECTIVES,
        "has_pool":      phpini.has_pool(domain.domain_name) is not None,
    }


@router.put("/domains/{domain_id}/php-config")
async def set_domain_php_config(
    domain_id:   int,
    payload:     dict,
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """
    Aplica overrides php.ini para el dominio. Body: {"overrides": {...}}.
    Lista vacía = pool solo con el bloque de seguridad (el pool dedicado es
    permanente; nunca se borra aquí, solo en delete_domain).
    """
    import json
    from scripts import php_ini_manager as phpini

    overrides = payload.get("overrides") or {}
    if not isinstance(overrides, dict):
        raise HTTPException(status_code=400, detail="overrides debe ser un objeto")

    domain = _get_owned_domain(domain_id, db, current_user)
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    _check_access(current_user, domain, db)

    owner = db.query(User).filter(User.id == domain.user_id).first()
    if not owner:
        raise HTTPException(status_code=500, detail="Propietario no encontrado")

    # Filtrar vacíos
    overrides = {k: str(v).strip() for k, v in overrides.items() if str(v).strip() != ""}

    if overrides:
        ok, errors = phpini.validate_overrides(domain.php_version, overrides)
        if not ok:
            raise HTTPException(status_code=400, detail="; ".join(errors))

    # Reescribir SIEMPRE el pool (con o sin overrides; el bloque de seguridad
    # y el socket dedicado se mantienen). El pool solo se borra en delete_domain.
    ok, msg = phpini.write_pool(
        domain.domain_name, domain.php_version, owner.username, overrides,
        relax_hardening=domain.php_hardening_relaxed or False,
    )
    if not ok:
        raise HTTPException(status_code=500, detail=f"Error escribiendo pool PHP: {msg}")
    php_socket = phpini.pool_socket_path(domain.domain_name)

    # Regenerar vhost preservando TODO el estado del dominio
    try:
        DomainManager().regenerate_vhost(
            username=owner.username,
            domain_name=domain.domain_name,
            php_version=domain.php_version,
            ssl_enabled=domain.ssl_enabled,
            ipv6=domain.ipv6,
            fastcgi_cache_enabled=domain.fastcgi_cache_enabled,
            fastcgi_cache_ttl_minutes=domain.fastcgi_cache_ttl_minutes,
            php_socket_override=php_socket,
            template_nginx_extra=domain.template_nginx_extra,
            redirect_to=domain.redirect_to,
            custom_docroot=domain.custom_docroot,
            ipv4=domain.ipv4,
            force_https=domain.force_https or False,
            hsts=domain.hsts_enabled or False,
            rate_limit_enabled=domain.rate_limit_enabled or False,
            rate_limit_rps=domain.rate_limit_rps or 10,
            rate_limit_burst=domain.rate_limit_burst or 20,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error regenerando vhost: {e}")

    domain.php_ini_overrides = json.dumps(overrides) if overrides else None
    db.commit()

    return {
        "status":    "ok",
        "domain":    domain.domain_name,
        "overrides": overrides,
        "dedicated_pool": True,
    }


@router.put("/domains/{domain_id}/php-hardening")
async def set_domain_php_hardening(
    domain_id:    int,
    payload:      dict,
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """
    Relaja o restaura el hardening PHP de un dominio. Body: {"relaxed": bool}.
    relaxed=True permite exec/system/shell_exec/... SOLO en este dominio (su
    pool aislado); open_basedir y el resto del hardening se mantienen.
    Es seguro para el sistema (solo afecta a este pool), así que lo pueden
    activar admin y propietario.
    """
    from scripts import php_ini_manager as phpini
    import json

    relaxed = bool(payload.get("relaxed", False))

    domain = _get_owned_domain(domain_id, db, current_user)
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    _check_access(current_user, domain, db)

    owner = db.query(User).filter(User.id == domain.user_id).first()
    if not owner:
        raise HTTPException(status_code=500, detail="Propietario no encontrado")

    try:
        overrides = json.loads(domain.php_ini_overrides) if domain.php_ini_overrides else {}
    except (ValueError, TypeError):
        overrides = {}

    # Reescribir el pool con el nuevo nivel de hardening
    ok, msg = phpini.write_pool(
        domain.domain_name, domain.php_version, owner.username, overrides,
        relax_hardening=relaxed,
    )
    if not ok:
        raise HTTPException(status_code=500, detail=f"Error escribiendo pool PHP: {msg}")

    # Regenerar vhost (socket dedicado) preservando estado
    try:
        DomainManager().regenerate_vhost(
            username=owner.username,
            domain_name=domain.domain_name,
            php_version=domain.php_version,
            ssl_enabled=domain.ssl_enabled,
            ipv6=domain.ipv6,
            fastcgi_cache_enabled=domain.fastcgi_cache_enabled,
            fastcgi_cache_ttl_minutes=domain.fastcgi_cache_ttl_minutes,
            php_socket_override=phpini.pool_socket_path(domain.domain_name),
            template_nginx_extra=domain.template_nginx_extra,
            redirect_to=domain.redirect_to,
            custom_docroot=domain.custom_docroot,
            ipv4=domain.ipv4,
            force_https=domain.force_https or False,
            hsts=domain.hsts_enabled or False,
            rate_limit_enabled=domain.rate_limit_enabled or False,
            rate_limit_rps=domain.rate_limit_rps or 10,
            rate_limit_burst=domain.rate_limit_burst or 20,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error regenerando vhost: {e}")

    domain.php_hardening_relaxed = relaxed
    db.commit()
    db.refresh(domain)
    return {
        "status": "ok",
        "domain": domain.domain_name,
        "php_hardening_relaxed": domain.php_hardening_relaxed,
    }


@router.get("/domains/{domain_id}/disk")
async def get_domain_disk(
    domain_id:   int,
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """
    Devuelve el tamaño en disco del directorio del dominio:
        /home/{user}/web/{dominio}/public_html (solo web)
        + total del dominio entero (incluye logs, tmp...)
    """
    import os
    import subprocess

    domain = _get_owned_domain(domain_id, db, current_user)
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    _check_access(current_user, domain, db)

    base = _domain_owner_dir(domain, db)

    def _du_bytes(path: str) -> int:
        if not os.path.isdir(path):
            return 0
        try:
            r = subprocess.run(
                ["/usr/bin/du", "-sb", "--apparent-size", path],
                capture_output=True, text=True, timeout=60,
            )
            if r.returncode != 0:
                return 0
            return int(r.stdout.split()[0])
        except (subprocess.TimeoutExpired, ValueError, IndexError, FileNotFoundError):
            return 0

    public_bytes = _du_bytes(os.path.join(base, "public_html"))
    total_bytes  = _du_bytes(base)
    logs_bytes   = _du_bytes(os.path.join(base, "logs"))

    return {
        "domain":           domain.domain_name,
        "public_html_mb":   public_bytes // (1024 * 1024),
        "public_html_bytes": public_bytes,
        "logs_mb":          logs_bytes // (1024 * 1024),
        "logs_bytes":       logs_bytes,
        "total_mb":         total_bytes // (1024 * 1024),
        "total_bytes":      total_bytes,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Suspensión individual de dominio
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/domains/{domain_id}/download")
async def download_domain_site(
    domain_id:    int,
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """
    Genera al momento un .tar.gz con los archivos del dominio y lo sirve como
    descarga (web: public_html, private, logs). Usa tarfile (Python) para no
    depender del PATH del servicio. El temporal se borra tras el envío.
    """
    domain = _get_owned_domain(domain_id, db, current_user)
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    _check_access(current_user, domain, db)

    owner = db.query(User).filter(User.id == domain.user_id).first()
    if not owner:
        raise HTTPException(status_code=404, detail="Propietario del dominio no encontrado")

    domain_root = get_domain_root(owner.username, domain.domain_name)
    if not os.path.isdir(domain_root):
        raise HTTPException(status_code=404, detail="No se encontraron archivos del dominio en disco")

    member = os.path.basename(domain_root)           # {domain}
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{domain.domain_name}_{stamp}.tar.gz"

    fd, tmp_path = tempfile.mkstemp(prefix="svqsite_", suffix=".tar.gz")
    os.close(fd)
    try:
        with tarfile.open(tmp_path, "w:gz", compresslevel=6) as tar:
            tar.add(domain_root, arcname=member)
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise HTTPException(status_code=500, detail=f"No se pudo generar el archivo: {e}")

    return FileResponse(
        tmp_path,
        media_type="application/gzip",
        filename=filename,
        background=BackgroundTask(lambda: os.path.exists(tmp_path) and os.remove(tmp_path)),
    )


@router.post("/domains/{domain_id}/suspend")
async def suspend_domain(
    domain_id:    int,
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """Suspende un dominio individualmente (admin o propietario)"""
    domain = _get_owned_domain(domain_id, db, current_user)
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    _check_access(current_user, domain, db)

    if domain.is_suspended:
        return {"status": "ok", "message": "El dominio ya estaba suspendido"}

    try:
        from datetime import datetime
        mgr = DomainSuspendManager()
        result = mgr.suspend_domain(domain.domain_name)
        domain.is_suspended = True
        domain.is_active    = False
        db.commit()
        return {"status": "success", "message": result["message"]}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/domains/{domain_id}/unsuspend")
async def unsuspend_domain(
    domain_id:    int,
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """Reactiva un dominio suspendido (admin o propietario)"""
    domain = _get_owned_domain(domain_id, db, current_user)
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    _check_access(current_user, domain, db)

    if not domain.is_suspended:
        return {"status": "ok", "message": "El dominio no estaba suspendido"}

    try:
        mgr = DomainSuspendManager()
        result = mgr.unsuspend_domain(domain.domain_name)
        if not result["success"]:
            raise HTTPException(status_code=500, detail=result["message"])
        domain.is_suspended = False
        domain.is_active    = True
        db.commit()
        return {"status": "success", "message": result["message"]}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Autoinstalador de aplicaciones (WordPress, …)
# ─────────────────────────────────────────────────────────────────────────────
from pydantic import BaseModel, Field as _Field


class AppInstallRequest(BaseModel):
    app: str = _Field(..., description="Slug de la app: wordpress, laravel, nextcloud")
    admin_user: str = _Field("admin", min_length=2, max_length=60)
    # admin_password/email solo son obligatorios para apps con setup de admin
    # (wordpress, nextcloud). Laravel no los usa. Validamos en el endpoint.
    admin_password: Optional[str] = _Field(None, max_length=128)
    admin_email: Optional[str] = _Field(None, max_length=160)


@router.post("/domains/{domain_id}/install-app")
async def install_app(
    domain_id:    int,
    payload:      AppInstallRequest,
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """
    Instala una aplicación web (1 clic) en el docroot del dominio.
    De momento: WordPress. Crea BD MariaDB + descarga + configura + instala.
    """
    domain = _get_owned_domain(domain_id, db, current_user)
    owner = db.query(User).filter(User.id == domain.user_id).first()
    if not owner:
        raise HTTPException(status_code=409, detail="El dominio no tiene propietario")

    app = (payload.app or "").lower().strip()
    from scripts.app_installer import AppInstaller, SUPPORTED_APPS, RequirementsError
    if app not in SUPPORTED_APPS:
        raise HTTPException(status_code=400, detail=f"App no soportada: {app}")

    # Apps con cuenta de administrador requieren contraseña (mín. 8)
    if app in ("wordpress", "nextcloud"):
        if not payload.admin_password or len(payload.admin_password) < 8:
            raise HTTPException(status_code=400,
                                detail="La contraseña de administrador es obligatoria (mínimo 8 caracteres)")
        if app == "wordpress" and not payload.admin_email:
            raise HTTPException(status_code=400,
                                detail="El email de administrador es obligatorio para WordPress")

    # Docroot real del dominio
    docroot = domain.custom_docroot or get_domain_root(owner.username, domain.domain_name) + "/public_html"

    # Reutilizar el ejecutor MariaDB del módulo de bases de datos
    from api.routes.databases import _run_mariadb, MARIADB_ENABLED
    if not MARIADB_ENABLED:
        raise HTTPException(status_code=503, detail="MariaDB no está habilitado; es necesario para instalar apps")

    installer = AppInstaller(run_sql=_run_mariadb)

    try:
        if app == "wordpress":
            result = installer.install_wordpress(
                domain=domain.domain_name,
                owner=owner.username,
                docroot=docroot,
                admin_user=payload.admin_user,
                admin_pass=payload.admin_password,
                admin_email=payload.admin_email,
            )
        elif app == "laravel":
            result = installer.install_laravel(
                domain=domain.domain_name,
                owner=owner.username,
                docroot=docroot,
            )
            # Laravel sirve desde /public. Lo resuelve la plantilla nginx
            # 'laravel' (docroot_subdir='public'): aplicarla regenera el vhost
            # con el root correcto, sin tocar el custom_docroot del dominio.
            try:
                _apply_builtin_template(domain, "laravel", owner, db)
            except Exception as ve:
                result["warning"] = f"Laravel instalado; aplica la plantilla 'laravel' para servir desde /public: {ve}"
        elif app == "nextcloud":
            result = installer.install_nextcloud(
                domain=domain.domain_name,
                owner=owner.username,
                docroot=docroot,
                admin_user=payload.admin_user,
                admin_pass=payload.admin_password,
                php_version=domain.php_version,
            )
            # Nextcloud requiere reglas nginx específicas (bloquear /data, /config,
            # .well-known, front controller). Aplicar la plantilla 'nextcloud'.
            try:
                _apply_builtin_template(domain, "nextcloud", owner, db)
            except Exception as ve:
                result["warning"] = f"Nextcloud instalado; aplica la plantilla 'nextcloud' manualmente: {ve}"
        else:
            raise HTTPException(status_code=400, detail=f"Instalador de '{app}' aún no disponible")
    except HTTPException:
        raise
    except RequirementsError as e:
        # Requisitos no cumplidos (versión/extensiones PHP, dominio no vacío…):
        # error de usuario, mensaje legible sin prefijo de fallo interno.
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error instalando {app}: {e}")

    return {"status": "success", "message": f"{SUPPORTED_APPS[app]['name']} instalado", "data": result}
