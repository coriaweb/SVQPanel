"""
Rutas API para gestión de dominios
"""

import os
import socket
import tarfile
import tempfile
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field as _Field
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


def _fpm_tuning_of(domain) -> dict:
    """Parsea el JSON de tuning FPM de un dominio. {} si no tiene (= preset medium)."""
    import json
    raw = getattr(domain, "fpm_pool_overrides", None)
    if not raw:
        return {}
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {}
    except (ValueError, TypeError):
        return {}


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

        # Seguridad: separación administración / hosting. Un administrador NO
        # puede ser propietario de dominios — su cuenta corre como root del
        # sistema y alojar sitios (PHP, CMS, plugins) bajo ella ampliaría la
        # superficie de ataque. Los dominios deben pertenecer a cuentas cliente.
        if user.role == "admin" or user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Un administrador no puede ser propietario de dominios. "
                    "Asigna el dominio a una cuenta de cliente."
                ),
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

        # Dominio "solo correo/DNS": NO se crea hosting web (vhost, pool PHP,
        # estructura de directorios). Su registro A apunta a otro servidor; aquí
        # solo se aloja correo y/o zona DNS. Para el resto del flujo se comporta
        # como un dominio normal, pero sin tocar el webserver.
        mail_dns_only = bool(getattr(domain, "mail_dns_only", False))

        # Create domain in system (Nginx, directories, etc) — salvo solo-correo/DNS
        if not mail_dns_only:
            domain_manager.create_domain(
                user.username,
                domain.domain_name,
                domain.php_version or "8.2"
            )

        # Autorellenar IPv4 con la IP principal del servidor si no se especificó
        ipv4_assigned = getattr(domain, 'ipv4', None)
        if not ipv4_assigned:
            try:
                from api.models.models_settings import Settings as _Settings
                _s = db.query(_Settings).filter(_Settings.id == 1).first()
                ipv4_assigned = (_s.server_ipv4 or None) if _s else None
            except Exception:
                ipv4_assigned = None

        # ¿Es en realidad un SUBDOMINIO? Lo es si su zona padre ya está en el
        # panel (gestion.zococoria.es y existe la zona zococoria.es). Se puede
        # forzar con domain.is_subdomain, pero por defecto se autodetecta.
        from api.routes.dns import find_parent_zone
        parent_zone = find_parent_zone(db, domain.domain_name)
        is_subdomain = bool(getattr(domain, "is_subdomain", False)) or parent_zone is not None
        parent_name = parent_zone.domain_name if parent_zone else None

        db_domain = Domain(
            user_id=domain.user_id,
            domain_name=domain.domain_name,
            php_version=domain.php_version or "8.2",
            # Un dominio solo-correo/DNS no tiene web → public_html vacío.
            public_html=("" if mail_dns_only
                         else f"/home/{user.username}/web/{domain.domain_name}/public_html"),
            ipv4=ipv4_assigned,
            ipv6=getattr(domain, 'ipv6', None) or None,
            is_subdomain=is_subdomain,
            parent_domain=parent_name,
            mail_dns_only=mail_dns_only,
            # Un subdominio no tiene variante www → sin redirección canónica.
            canonical_domain="none" if is_subdomain else "www",
        )
        db.add(db_domain)
        db.commit()
        db.refresh(db_domain)

        # Crear zona DNS automáticamente si se solicitó
        if domain.dns_enabled:
            try:
                from api.models.models_dns import DnsZone, DnsRecord
                from api.models.models_settings import Settings
                from api.routes.dns import (_build_template_records, _get_server_ipv4,
                                            apply_subdomain_dns)
                from scripts.dns_manager import DNSManager

                # Subdominio con padre en el panel → registro A/AAAA en la zona
                # padre (no zona separada). Si apply devuelve 'own', no había
                # padre gestionada y caemos a crear zona propia (como un dominio).
                handled_as_sub = False
                if is_subdomain and parent_name:
                    res = apply_subdomain_dns(db, domain.domain_name,
                                              ipv4=ipv4_assigned,
                                              ipv6=getattr(domain, "ipv6", None) or None)
                    handled_as_sub = (res == "parent")
                    if not handled_as_sub:
                        # La padre dejó de estar gestionada entre medias: lo
                        # tratamos como dominio normal (zona propia).
                        db_domain.is_subdomain = False
                        db_domain.parent_domain = None
                        db.commit()

                existing_zone = db.query(DnsZone).filter(
                    DnsZone.domain_name == domain.domain_name
                ).first()

                if not handled_as_sub and not existing_zone:
                    ipv4 = _get_server_ipv4(db)
                    try:
                        dns_mgr = DNSManager()
                        serial = dns_mgr.create_zone(domain.domain_name, ipv4=ipv4)
                    except PermissionError:
                        serial = 2026052501

                    # ip_address: necesario para que la lista de zonas muestre la
                    # IP (si no, sale "—"). Coherente con el endpoint create_zone.
                    zone = DnsZone(domain_name=domain.domain_name, serial=serial,
                                   ip_address=ipv4)
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

        # Aplicar el límite de correo NO autenticado (PHP/web) al usuario del
        # nuevo dominio: así un sitio hackeado no puede enviar sin tope aunque el
        # dominio no tenga correo configurado. Tolerante a fallos (dev/sin root).
        try:
            from api.routes.mail import _rebuild_rspamd
            _rebuild_rspamd(db)
        except Exception:
            pass

        # Liberar memoria de subprocesos (nginx, PHP-FPM, chown...) retenida
        # temporalmente por Python. Sin esto, el spike de ~800MB al crear un
        # dominio puede persistir hasta el siguiente GC automático.
        import gc; gc.collect()
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
    limit: int = 1000,
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

        domains = query.order_by(Domain.domain_name).offset(skip).limit(limit).all()
        return domains
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/domains/wp-protection-overview")
async def get_wp_protection_overview(
    current_user: User = Depends(require_admin),
    db:           Session = Depends(get_db),
):
    """
    Vista admin: TODOS los dominios del servidor con su estado de protección
    WordPress + los hits de ataque CACHEADOS en BD (los refresca un cron cada 3h,
    ventana 24h). Lee solo de BD → instantáneo, no escanea los access.log en vivo.
    Solo admin.
    """
    from scripts.wp_attack_detector import DEFAULT_THRESHOLD

    domains = db.query(Domain).filter(Domain.is_active == True).all()  # noqa: E712
    user_ids = {d.user_id for d in domains}
    users = {u.id: u.username for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}

    rows = []
    last_check = None
    for d in domains:
        xh = int(d.wp_xmlrpc_hits or 0)
        wh = int(d.wp_wplogin_hits or 0)
        # "bajo ataque" = supera el umbral en un vector que NO está ya mitigado.
        sx = (xh >= DEFAULT_THRESHOLD) and not d.xmlrpc_blocked
        sl = (wh >= DEFAULT_THRESHOLD) and (d.wp_login_ratelimit or 0) == 0
        targets = (["xmlrpc"] if sx else []) + (["wp-login"] if sl else [])
        if d.wp_attack_checked_at and (last_check is None or d.wp_attack_checked_at > last_check):
            last_check = d.wp_attack_checked_at
        rows.append({
            "domain_id":          d.id,
            "domain":             d.domain_name,
            "owner":              users.get(d.user_id, ""),
            "xmlrpc_blocked":     bool(d.xmlrpc_blocked),
            "wp_login_ratelimit": int(d.wp_login_ratelimit or 0),
            "xmlrpc_hits":        xh,
            "wplogin_hits":       wh,
            "under_attack":       bool(sx or sl),
            "targets":            targets,
        })
    rows.sort(key=lambda r: (not r["under_attack"],
                             -(r["xmlrpc_hits"] + r["wplogin_hits"]),
                             r["domain"]))  # ataques arriba, luego más hits
    return {
        "domains":    rows,
        "threshold":  DEFAULT_THRESHOLD,
        "checked_at": last_check.isoformat() if last_check else None,
    }


@router.get("/domains/wp-attack-alerts")
async def get_wp_attack_alerts(
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """
    Avisos para el dashboard: dominios del usuario que están recibiendo un ataque
    de fuerza bruta a WordPress (xmlrpc/wp-login) y NO tienen aún la protección
    activada. El frontend muestra un banner con botón para activarla.

    Solo reporta dominios DESPROTEGIDOS bajo ataque (los ya protegidos no generan
    aviso, aunque sigan recibiendo el ataque: ya está mitigado).

    OJO: este endpoint debe declararse ANTES de GET /domains/{domain_id}, o
    FastAPI intentaría parsear "wp-attack-alerts" como domain_id (int) → 422.
    """
    from concurrent.futures import ThreadPoolExecutor
    from scripts.wp_attack_detector import analyze_domain

    # Dominios accesibles según rol (mismo criterio que list_domains).
    q = db.query(Domain).filter(Domain.is_active == True)  # noqa: E712
    if current_user.role != "admin":
        q = q.filter(Domain.user_id == current_user.id)
    domains = q.all()

    # Mapa user_id → username (una consulta) para construir la ruta del log.
    user_ids = {d.user_id for d in domains}
    users = {u.id: u.username for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}

    # Solo analizamos los que aún NO están totalmente protegidos (si ya bloqueó
    # xmlrpc y tiene rate-limit, no hay nada que avisar).
    candidates = [
        d for d in domains
        if not (d.xmlrpc_blocked and (d.wp_login_ratelimit or 0) > 0)
        and users.get(d.user_id)
    ]

    def _check(d):
        res = analyze_domain(users[d.user_id], d.domain_name)
        if not res["under_attack"]:
            return None
        # No avisar de un vector que ya está mitigado en este dominio.
        targets = []
        if "xmlrpc" in res["attack_targets"] and not d.xmlrpc_blocked:
            targets.append("xmlrpc")
        if "wp-login" in res["attack_targets"] and (d.wp_login_ratelimit or 0) == 0:
            targets.append("wp-login")
        if not targets:
            return None
        return {
            "domain_id":   d.id,
            "domain":      d.domain_name,
            "xmlrpc_hits": res["xmlrpc_hits"],
            "wplogin_hits": res["wplogin_hits"],
            "window_min":  res["window_min"],
            "targets":     targets,
        }

    alerts = []
    if candidates:
        with ThreadPoolExecutor(max_workers=min(8, len(candidates))) as ex:
            for r in ex.map(_check, candidates):
                if r:
                    alerts.append(r)

    return {"alerts": alerts}


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

        # Un dominio solo-correo/DNS no tiene web → no se le cambia PHP/vhost.
        if getattr(db_domain, "mail_dns_only", False) and domain_update.php_version is not None \
                and domain_update.php_version != db_domain.php_version:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Este dominio es solo correo/DNS (sin web): no tiene PHP que cambiar.",
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
                                  relax_hardening=db_domain.php_hardening_relaxed or False,
                                  fpm_tuning=_fpm_tuning_of(db_domain))

        if domain_update.is_active is not None:
            db_domain.is_active = domain_update.is_active

        ipv4_changed = False
        if 'ipv4' in domain_update.model_fields_set:
            new_ipv4 = domain_update.ipv4 or None
            if new_ipv4 != db_domain.ipv4:
                db_domain.ipv4 = new_ipv4
                ipv4_changed = True

        ipv6_changed = False
        if 'ipv6' in domain_update.model_fields_set:
            new_ipv6 = domain_update.ipv6 or None
            if new_ipv6 != db_domain.ipv6:
                db_domain.ipv6 = new_ipv6
                ipv6_changed = True

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

        # Modo solo-lectura HTTP
        readonly_changed = False
        if domain_update.readonly_mode_enabled is not None:
            if domain_update.readonly_mode_enabled != db_domain.readonly_mode_enabled:
                db_domain.readonly_mode_enabled = domain_update.readonly_mode_enabled
                readonly_changed = True
        if 'allowed_mutation_ips' in domain_update.model_fields_set:
            new_ips = domain_update.allowed_mutation_ips or None
            if new_ips != db_domain.allowed_mutation_ips:
                db_domain.allowed_mutation_ips = new_ips
                readonly_changed = True

        # Headers de seguridad HTTP
        sec_headers_changed = False
        if domain_update.security_headers_enabled is not None:
            if domain_update.security_headers_enabled != db_domain.security_headers_enabled:
                db_domain.security_headers_enabled = domain_update.security_headers_enabled
                sec_headers_changed = True

        # HTTP/3 (QUIC)
        http3_changed = False
        if domain_update.http3_enabled is not None:
            if domain_update.http3_enabled != db_domain.http3_enabled:
                db_domain.http3_enabled = domain_update.http3_enabled
                http3_changed = True

        db.commit()
        db.refresh(db_domain)

        # Regenerar vhost si cambió algún parámetro que afecta a nginx. Los
        # dominios solo correo/DNS no tienen vhost → nunca se regenera.
        if (not getattr(db_domain, "mail_dns_only", False)) and \
           (redir_changed or docroot_changed or ipv4_changed or ipv6_changed or readonly_changed or sec_headers_changed or http3_changed):
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
                        custom_nginx_config=db_domain.custom_nginx_config,
                        custom_apache_config=db_domain.custom_apache_config,
                        redirect_to=db_domain.redirect_to,
                        custom_docroot=db_domain.custom_docroot,
                        ipv4=db_domain.ipv4,
                        force_https=db_domain.force_https or False,
                        hsts=db_domain.hsts_enabled or False,
                        rate_limit_enabled=db_domain.rate_limit_enabled or False,
                        rate_limit_rps=db_domain.rate_limit_rps or 10,
                        rate_limit_burst=db_domain.rate_limit_burst or 20,
                        readonly_mode_enabled=db_domain.readonly_mode_enabled or False,
                        allowed_mutation_ips=db_domain.allowed_mutation_ips,
                        blocked_user_agents=__import__('json').loads(db_domain.blocked_user_agents) if db_domain.blocked_user_agents else [],
                        security_headers_enabled=db_domain.security_headers_enabled or False,
                        http3_enabled=db_domain.http3_enabled or False,
                        canonical_domain=db_domain.canonical_domain or "www",
                    )
                except Exception as vhost_err:
                    import logging
                    logging.getLogger(__name__).warning(
                        f"regenerate_vhost falló para {db_domain.domain_name}: {vhost_err}"
                    )

        # Levantar/bajar la IPv6 en la interfaz de red cuando cambia
        if ipv6_changed:
            try:
                from scripts.ipv6_manager import IPv6Manager as _IPv6Mgr
                from api.models.models_settings import Settings as _Settings
                _s = db.query(_Settings).filter(_Settings.id == 1).first()
                _iface = (_s.network_interface or "eth0") if _s else "eth0"
                _mgr = _IPv6Mgr()
                if db_domain.ipv6:
                    # Añadir la nueva IP a la interfaz (idempotente si ya existe)
                    _prefix = _s.ipv6_range.split("/")[1] if _s and _s.ipv6_range and "/" in _s.ipv6_range else "64"
                    _mgr.assign_ipv6(_iface, f"{db_domain.ipv6}/{_prefix}")
                # Si la IP anterior existía y es distinta, quitarla
                # (no guardamos la anterior, así que solo quitamos si new=None)
                # La IP anterior ya no está en db_domain — la lógica de remove
                # queda en manos del usuario desde la pestaña IPv6 si lo necesita
            except Exception as _ipv6_err:
                import logging
                logging.getLogger(__name__).warning(
                    f"No se pudo configurar IPv6 en interfaz para {db_domain.domain_name}: {_ipv6_err}"
                )

        # Actualizar IP de salida SMTP en Postfix si cambió la IPv4. Reaplicamos
        # según la preferencia del dominio (ipv4/ipv6), leyendo su MailDomain.
        if ipv4_changed:
            try:
                from scripts import mail_manager as mail_mod
                mm = mail_mod.MailManager()
                if mm.mail_available():
                    if db_domain.ipv4:
                        from api.models.models_mail import MailDomain
                        _md = db.query(MailDomain).filter(
                            MailDomain.domain_name == db_domain.domain_name).first()
                        if _md:
                            from api.routes.mail import _apply_domain_sender_ip
                            _apply_domain_sender_ip(_md, db)
                        else:
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

        # Delete domain from system (nginx config + directorios) — salvo los
        # dominios solo-correo/DNS, que nunca tuvieron web (vhost/pool/dirs).
        if not getattr(db_domain, "mail_dns_only", False):
            domain_manager.delete_domain(db_domain.domain_name, username=username)
            # Limpiar pool PHP dedicado y zona de cache si existían
            try:
                from scripts import php_ini_manager as phpini
                from scripts.utils import remove_fastcgi_cache_zone
                phpini.remove_pool(db_domain.domain_name)
                remove_fastcgi_cache_zone(db_domain.domain_name)
            except Exception as e:
                print(f"Warning: limpieza pool/cache de {db_domain.domain_name}: {e}")

        # Deshacer el resto de lo que crea el alta: zona DNS y dominio de correo
        # del MISMO nombre. Reutiliza los helpers del orquestador de borrado
        # (misma lógica que la cascada al borrar usuario y que DELETE /dns,/mail).
        dns_warnings = []
        try:
            from scripts.user_purge import purge_dns_zones, purge_mail_domains
            from api.models.models_mail import MailDomain
            mail_domains = (db.query(MailDomain)
                            .filter(MailDomain.domain_name == db_domain.domain_name)
                            .all())
            purge_mail_domains(db, mail_domains, username, dns_warnings)
            # Si es subdominio, quitar su A/AAAA de la zona padre (no tiene zona
            # propia que purgar). Si no, purgar su zona como un dominio normal.
            if getattr(db_domain, "is_subdomain", False):
                try:
                    from api.routes.dns import remove_subdomain_dns
                    remove_subdomain_dns(db, db_domain.domain_name)
                except Exception as e:
                    dns_warnings.append(f"subdominio DNS: {e}")
            else:
                purge_dns_zones(db, {db_domain.domain_name}, dns_warnings)
            # Por si hubo webmail sin fila MailDomain (o quedó de antes):
            try:
                from scripts.webmail_manager import WebmailManager
                WebmailManager().destroy(db_domain.domain_name)
            except Exception:
                pass
        except Exception as e:
            print(f"Warning: limpieza DNS/correo de {db_domain.domain_name}: {e}")
        if dns_warnings:
            print(f"Warning: avisos limpieza DNS/correo: {dns_warnings}")

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
    Devuelve las últimas N líneas del log (access o error) del dominio.
    En modo Apache+Nginx, los errores PHP (500, fatal de WordPress…) van al log de
    APACHE, no al de nginx. Por eso combinamos AMBOS logs si existen: nginx.{type}
    + apache.{type}. Path: /home/{user}/web/{dominio}/logs/{nginx,apache}.{type}.log
    """
    import os
    from collections import deque

    domain = _get_owned_domain(domain_id, db, current_user)
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    _check_access(current_user, domain, db)

    base = _domain_owner_dir(domain, db)
    logs_dir = os.path.join(base, "logs")
    candidates = [
        ("nginx",  os.path.join(logs_dir, f"nginx.{log_type}.log")),
        ("apache", os.path.join(logs_dir, f"apache.{log_type}.log")),
    ]
    existing = [(src, p) for src, p in candidates if os.path.isfile(p)]

    if not existing:
        return {
            "domain":   domain.domain_name,
            "type":     log_type,
            "path":     candidates[0][1],
            "exists":   False,
            "lines":    [],
            "message":  "El archivo de log aún no existe (sin tráfico todavía)",
        }

    try:
        merged = []
        for src, p in existing:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                # Prefijar con el origen solo cuando hay más de un log (modo dual),
                # para que se distinga de dónde viene cada línea.
                prefix = f"[{src}] " if len(existing) > 1 else ""
                for line in deque(f, maxlen=lines):
                    merged.append(prefix + line.rstrip("\n"))
        # Quedarnos con las últimas N del conjunto combinado.
        tail = merged[-lines:]
        return {
            "domain":   domain.domain_name,
            "type":     log_type,
            "path":     ", ".join(p for _, p in existing),
            "exists":   True,
            "lines":    tail,
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
            security_headers_enabled=domain.security_headers_enabled or False,
            http3_enabled=domain.http3_enabled or False,
            canonical_domain=domain.canonical_domain or "www",
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
            custom_nginx_config=domain.custom_nginx_config,
            custom_apache_config=domain.custom_apache_config,
            redirect_to=domain.redirect_to,
            custom_docroot=domain.custom_docroot,
            ipv4=domain.ipv4,
            force_https=domain.force_https or False,
            hsts=domain.hsts_enabled or False,
            rate_limit_enabled=enabled,
            rate_limit_rps=rps,
            rate_limit_burst=burst,
            security_headers_enabled=domain.security_headers_enabled or False,
            http3_enabled=domain.http3_enabled or False,
            canonical_domain=domain.canonical_domain or "www",
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


@router.put("/domains/{domain_id}/bad-bots")
async def set_domain_bad_bots(
    domain_id:    int,
    payload:      dict,
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """
    Actualiza los user-agents bloqueados a nivel de dominio.
    Body: {"patterns": ["zgrab", "nikto", ...]}
    Los patrones se inyectan como bloques `if` en el vhost nginx del dominio.
    """
    import json
    patterns = payload.get("patterns", [])
    if not isinstance(patterns, list):
        raise HTTPException(status_code=400, detail="patterns debe ser una lista")
    patterns = [str(p).strip() for p in patterns if str(p).strip()]

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
            custom_nginx_config=domain.custom_nginx_config,
            custom_apache_config=domain.custom_apache_config,
            redirect_to=domain.redirect_to,
            custom_docroot=domain.custom_docroot,
            ipv4=domain.ipv4,
            force_https=domain.force_https or False,
            hsts=domain.hsts_enabled or False,
            rate_limit_enabled=domain.rate_limit_enabled or False,
            rate_limit_rps=domain.rate_limit_rps or 10,
            rate_limit_burst=domain.rate_limit_burst or 20,
            readonly_mode_enabled=domain.readonly_mode_enabled or False,
            allowed_mutation_ips=domain.allowed_mutation_ips,
            blocked_user_agents=patterns,
            security_headers_enabled=domain.security_headers_enabled or False,
            http3_enabled=domain.http3_enabled or False,
            canonical_domain=domain.canonical_domain or "www",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error aplicando bloqueo de bots: {e}")

    domain.blocked_user_agents = json.dumps(patterns) if patterns else None
    db.commit()
    return {
        "status": "ok",
        "domain": domain.domain_name,
        "blocked_patterns": patterns,
    }


def _regenerate_from_domain(domain: Domain, db: Session) -> None:
    """Regenera el vhost de un dominio con TODO su estado actual de la BD.
    regenerate_vhost lee xmlrpc_blocked/wp_login_ratelimit de la BD, así que basta
    con haber hecho commit del cambio antes de llamar aquí."""
    owner = db.query(User).filter(User.id == domain.user_id).first()
    if not owner:
        raise HTTPException(status_code=500, detail="Propietario del dominio no encontrado")
    from scripts import php_ini_manager as phpini
    php_socket = phpini.pool_socket_path(domain.domain_name) if phpini.has_pool(domain.domain_name) else None
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
        custom_nginx_config=domain.custom_nginx_config,
        custom_apache_config=domain.custom_apache_config,
        redirect_to=domain.redirect_to,
        custom_docroot=domain.custom_docroot,
        ipv4=domain.ipv4,
        force_https=domain.force_https or False,
        hsts=domain.hsts_enabled or False,
        rate_limit_enabled=domain.rate_limit_enabled or False,
        rate_limit_rps=domain.rate_limit_rps or 10,
        rate_limit_burst=domain.rate_limit_burst or 20,
        readonly_mode_enabled=domain.readonly_mode_enabled or False,
        allowed_mutation_ips=domain.allowed_mutation_ips,
        blocked_user_agents=json.loads(domain.blocked_user_agents) if domain.blocked_user_agents else [],
        security_headers_enabled=domain.security_headers_enabled or False,
        http3_enabled=domain.http3_enabled or False,
        canonical_domain=domain.canonical_domain or "www",
        # xmlrpc_blocked y wp_login_ratelimit se leen de la BD dentro de regenerate_vhost
    )


@router.get("/domains/{domain_id}/wp-protection")
async def get_domain_wp_protection(
    domain_id:    int,
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """
    Estado de protección WordPress del dominio + análisis de ataque en curso.
    Lo consume el pane "Seguridad" del gestor WordPress en la ficha del dominio.
    """
    domain = _get_owned_domain(domain_id, db, current_user)
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    _check_access(current_user, domain, db)

    # Lee los hits CACHEADOS en BD (los refresca el cron cada 3h, ventana 24h).
    # NO analiza el log en vivo → el pane carga instantáneo (antes escaneaba hasta
    # 20 MB de access.log en cada apertura y hacía lento el pane de Seguridad).
    from scripts.wp_attack_detector import DEFAULT_THRESHOLD
    xh = int(domain.wp_xmlrpc_hits or 0)
    wh = int(domain.wp_wplogin_hits or 0)
    still_xmlrpc = (xh >= DEFAULT_THRESHOLD) and not domain.xmlrpc_blocked
    still_login  = (wh >= DEFAULT_THRESHOLD) and (domain.wp_login_ratelimit or 0) == 0
    attack = {
        "under_attack":   bool(still_xmlrpc or still_login),
        "xmlrpc_hits":    xh,
        "wplogin_hits":   wh,
        "threshold":      DEFAULT_THRESHOLD,
        "attack_targets": (["xmlrpc"] if still_xmlrpc else []) + (["wp-login"] if still_login else []),
        "checked_at":     domain.wp_attack_checked_at.isoformat() if domain.wp_attack_checked_at else None,
    }

    return {
        "xmlrpc_blocked":     bool(domain.xmlrpc_blocked),
        "wp_login_ratelimit": int(domain.wp_login_ratelimit or 0),
        "attack":             attack,
    }


@router.put("/domains/{domain_id}/wp-protection")
async def set_domain_wp_protection(
    domain_id:    int,
    payload:      dict,
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """
    Protección anti fuerza bruta de WordPress por dominio. El cliente (dueño) o el
    admin lo activan, típicamente tras el aviso de ataque en su dashboard.
    Body: {"xmlrpc_blocked": bool, "wp_login_ratelimit": int}  (ambos opcionales)
      - xmlrpc_blocked: True → nginx devuelve 444 a /xmlrpc.php (corta amplificación).
      - wp_login_ratelimit: peticiones/min por IP a /wp-login.php (0 = sin límite).
        Recomendado 3 (una persona necesita 1-2; un bot mete miles).
    """
    domain = _get_owned_domain(domain_id, db, current_user)
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    _check_access(current_user, domain, db)

    changed = False
    if "xmlrpc_blocked" in payload:
        domain.xmlrpc_blocked = bool(payload["xmlrpc_blocked"])
        changed = True
    if "wp_login_ratelimit" in payload:
        try:
            rl = int(payload["wp_login_ratelimit"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="wp_login_ratelimit debe ser un entero")
        if rl < 0 or rl > 600:
            raise HTTPException(status_code=400, detail="wp_login_ratelimit fuera de rango (0-600)")
        domain.wp_login_ratelimit = rl
        changed = True

    if not changed:
        raise HTTPException(status_code=400, detail="Nada que cambiar")

    db.commit()  # commit ANTES de regenerar: regenerate_vhost lee estos campos de la BD
    try:
        _regenerate_from_domain(domain, db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error aplicando protección WordPress: {e}")

    return {
        "status": "ok",
        "domain": domain.domain_name,
        "xmlrpc_blocked": domain.xmlrpc_blocked,
        "wp_login_ratelimit": domain.wp_login_ratelimit,
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
        fpm_tuning=_fpm_tuning_of(domain),
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
            custom_nginx_config=domain.custom_nginx_config,
            custom_apache_config=domain.custom_apache_config,
            redirect_to=domain.redirect_to,
            custom_docroot=domain.custom_docroot,
            ipv4=domain.ipv4,
            force_https=domain.force_https or False,
            hsts=domain.hsts_enabled or False,
            rate_limit_enabled=domain.rate_limit_enabled or False,
            rate_limit_rps=domain.rate_limit_rps or 10,
            rate_limit_burst=domain.rate_limit_burst or 20,
            security_headers_enabled=domain.security_headers_enabled or False,
            http3_enabled=domain.http3_enabled or False,
            canonical_domain=domain.canonical_domain or "www",
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


# ─────────────────────────────────────────────────────────────────────────────
# Tuning de recursos del pool PHP-FPM por dominio (Fase 21)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/domains/{domain_id}/fpm-config")
async def get_domain_fpm_config(
    domain_id:    int,
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """
    Devuelve el tuning FPM actual del dominio, los presets disponibles, los caps
    del servidor y las directivas pm.* efectivas que se aplicarían.
    """
    from scripts import php_ini_manager as phpini

    domain = _get_owned_domain(domain_id, db, current_user)
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    _check_access(current_user, domain, db)

    tuning = _fpm_tuning_of(domain)
    return {
        "domain":     domain.domain_name,
        "tuning":     tuning,                          # {"preset":..,"manual":{..}} o {}
        "effective":  phpini.resolve_fpm_tuning(tuning),  # directivas pm.* resultantes
        "presets":    phpini.FPM_PRESETS,
        "default_preset": phpini.FPM_DEFAULT_PRESET,
        "caps": {
            "pm.max_children": phpini.FPM_MAX_CHILDREN_CAP,
            "pm.max_requests": phpini.FPM_MAX_REQUESTS_CAP,
        },
    }


@router.put("/domains/{domain_id}/fpm-config")
async def set_domain_fpm_config(
    domain_id:    int,
    payload:      dict,
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """
    Aplica el tuning de recursos del pool FPM del dominio.
    Body: {"preset":"low|medium|high", "manual":{"pm.max_children":12,...}}.
    Body vacío / {"preset":"medium"} → valores por defecto. Reescribe el pool.
    """
    import json
    from scripts import php_ini_manager as phpini

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload debe ser un objeto")

    # Normalizar el tuning de entrada: solo preset + manual con claves conocidas.
    tuning = {}
    if payload.get("preset"):
        tuning["preset"] = payload["preset"]
    manual = payload.get("manual") or {}
    if manual:
        tuning["manual"] = {k: v for k, v in manual.items() if k in phpini._FPM_TUNABLE}

    ok, errors = phpini.validate_fpm_tuning(tuning)
    if not ok:
        raise HTTPException(status_code=400, detail="; ".join(errors))

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

    # Reescribir el pool con el nuevo tuning (preserva php.ini overrides + hardening).
    ok, msg = phpini.write_pool(
        domain.domain_name, domain.php_version, owner.username, overrides,
        relax_hardening=domain.php_hardening_relaxed or False,
        fpm_tuning=tuning or None,
    )
    if not ok:
        raise HTTPException(status_code=500, detail=f"Error escribiendo pool PHP: {msg}")

    # Persistir. Guardamos {} → NULL (= preset medium por defecto).
    domain.fpm_pool_overrides = json.dumps(tuning) if tuning else None
    db.commit()

    return {
        "status":    "ok",
        "domain":    domain.domain_name,
        "tuning":    tuning,
        "effective": phpini.resolve_fpm_tuning(tuning),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Redis dedicado por dominio (caché de objetos)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/domains/{domain_id}/redis")
async def get_domain_redis(
    domain_id:    int,
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """Estado de la instancia Redis dedicada del dominio (para la UI)."""
    from scripts import redis_manager

    domain = _get_owned_domain(domain_id, db, current_user)
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    _check_access(current_user, domain, db)

    owner = db.query(User).filter(User.id == domain.user_id).first()
    if not owner:
        raise HTTPException(status_code=500, detail="Propietario no encontrado")

    status = redis_manager.instance_status(owner.username, domain.domain_name)
    status["domain"] = domain.domain_name
    # La verdad operativa es el sistema; la BD puede ir por detrás si algo
    # falló a medias. Devolvemos también lo que cree la BD para diagnosticar.
    status["db_enabled"] = domain.redis_enabled or False
    status["db_maxmemory_mb"] = domain.redis_maxmemory_mb or 64
    return status


@router.put("/domains/{domain_id}/redis")
async def set_domain_redis(
    domain_id:    int,
    payload:      dict,
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """
    Activa/desactiva la instancia Redis dedicada del dominio.
    Body: {"enabled": bool, "maxmemory_mb": 64}. La instancia corre como el
    usuario del dominio, con socket unix en private/ (solo su PHP puede
    conectar) y maxmemory acotado por el techo del servidor.
    """
    from scripts import redis_manager

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload debe ser un objeto")
    enabled = bool(payload.get("enabled", False))
    maxmemory = redis_manager.clamp_maxmemory(
        payload.get("maxmemory_mb", redis_manager.DEFAULT_MAXMEMORY_MB))

    domain = _get_owned_domain(domain_id, db, current_user)
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    _check_access(current_user, domain, db)
    if domain.mail_dns_only:
        raise HTTPException(status_code=422,
                            detail="Dominio solo correo/DNS: no tiene hosting web")

    owner = db.query(User).filter(User.id == domain.user_id).first()
    if not owner:
        raise HTTPException(status_code=500, detail="Propietario no encontrado")

    if enabled and not redis_manager.redis_available():
        raise HTTPException(
            status_code=422,
            detail="redis-server no está instalado en el servidor")

    try:
        if enabled:
            status = redis_manager.enable_instance(
                owner.username, domain.domain_name, maxmemory)
        else:
            status = redis_manager.disable_instance(
                owner.username, domain.domain_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error aplicando Redis: {e}")

    domain.redis_enabled = enabled
    domain.redis_maxmemory_mb = maxmemory
    db.commit()

    status["domain"] = domain.domain_name
    status["db_enabled"] = enabled
    status["db_maxmemory_mb"] = maxmemory
    return status


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
        fpm_tuning=_fpm_tuning_of(domain),
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
            custom_nginx_config=domain.custom_nginx_config,
            custom_apache_config=domain.custom_apache_config,
            redirect_to=domain.redirect_to,
            custom_docroot=domain.custom_docroot,
            ipv4=domain.ipv4,
            force_https=domain.force_https or False,
            hsts=domain.hsts_enabled or False,
            rate_limit_enabled=domain.rate_limit_enabled or False,
            rate_limit_rps=domain.rate_limit_rps or 10,
            rate_limit_burst=domain.rate_limit_burst or 20,
            security_headers_enabled=domain.security_headers_enabled or False,
            http3_enabled=domain.http3_enabled or False,
            canonical_domain=domain.canonical_domain or "www",
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


def _regenerate_domain_vhost(domain, owner):
    """Regenera el vhost del dominio preservando TODO su estado actual.

    Punto único para reconstruir el vhost desde el objeto Domain (incluye las
    directivas personalizadas). Lanza la excepción de regenerate_vhost si falla
    la validación (nginx -t / apache configtest), para que el endpoint pueda
    revertir.
    """
    import json as _json
    from scripts import php_ini_manager as _phpini
    _mgr = DomainManager()
    _httpauth = None
    if getattr(domain, "httpauth_enabled", False) and domain.httpauth_user:
        _httpauth = {
            "user": domain.httpauth_user,
            "realm": "Zona restringida",
            "file": _mgr.htpasswd_path(owner.username, domain.domain_name),
        }
    return _mgr.regenerate_vhost(
        username=owner.username,
        domain_name=domain.domain_name,
        php_version=domain.php_version or "8.2",
        ssl_enabled=domain.ssl_enabled or False,
        ipv6=domain.ipv6,
        fastcgi_cache_enabled=domain.fastcgi_cache_enabled or False,
        fastcgi_cache_ttl_minutes=domain.fastcgi_cache_ttl_minutes or 60,
        php_socket_override=_phpini.pool_socket_path(domain.domain_name),
        template_nginx_extra=domain.template_nginx_extra,
        custom_nginx_config=domain.custom_nginx_config,
        custom_apache_config=domain.custom_apache_config,
        redirect_to=domain.redirect_to,
        custom_docroot=domain.custom_docroot,
        ipv4=domain.ipv4,
        force_https=domain.force_https or False,
        hsts=domain.hsts_enabled or False,
        rate_limit_enabled=domain.rate_limit_enabled or False,
        rate_limit_rps=domain.rate_limit_rps or 10,
        rate_limit_burst=domain.rate_limit_burst or 20,
        readonly_mode_enabled=domain.readonly_mode_enabled or False,
        allowed_mutation_ips=domain.allowed_mutation_ips,
        blocked_user_agents=_json.loads(domain.blocked_user_agents) if domain.blocked_user_agents else [],
        security_headers_enabled=domain.security_headers_enabled or False,
        http3_enabled=domain.http3_enabled or False,
        httpauth=_httpauth,
        canonical_domain=domain.canonical_domain or "www",
    )


class CustomConfigRequest(BaseModel):
    custom_nginx_config:  Optional[str] = _Field(None, max_length=20000)
    custom_apache_config: Optional[str] = _Field(None, max_length=20000)


_CANONICAL_CHOICES = ("www", "non-www", "none")


class CanonicalRequest(BaseModel):
    # www → fuerza www.dominio | non-www → fuerza dominio sin www | none → sin redirección
    canonical_domain: str = _Field(..., pattern="^(www|non-www|none)$")


@router.put("/domains/{domain_id}/canonical")
async def update_canonical_domain(
    domain_id:    int,
    payload:      CanonicalRequest,
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """Define el dominio canónico (www / non-www / none) y regenera el vhost con
    la redirección 301 correspondiente. Si la validación del vhost falla, revierte
    al valor anterior y devuelve 422."""
    domain = _get_owned_domain(domain_id, db, current_user)
    owner = db.query(User).filter(User.id == domain.user_id).first()
    if not owner:
        raise HTTPException(status_code=409, detail="El dominio no tiene propietario")

    if payload.canonical_domain not in _CANONICAL_CHOICES:
        raise HTTPException(status_code=400, detail="Valor de canonical_domain no válido")

    prev = domain.canonical_domain
    domain.canonical_domain = payload.canonical_domain
    db.commit()
    db.refresh(domain)

    try:
        _regenerate_domain_vhost(domain, owner)
    except Exception as e:
        domain.canonical_domain = prev
        db.commit()
        try:
            _regenerate_domain_vhost(domain, owner)
        except Exception:
            pass
        raise HTTPException(status_code=422, detail=f"No se pudo aplicar el dominio canónico: {e}")

    return {"status": "success", "canonical_domain": domain.canonical_domain}


# Tokens que delatan que el usuario pegó un vhost completo (no un fragmento):
# nuestras directivas se inyectan DENTRO del server{}/VirtualHost.
_FORBIDDEN_NGINX = ("server ", "server{", "http ", "http{")
_FORBIDDEN_APACHE = ("<virtualhost", "</virtualhost")


@router.put("/domains/{domain_id}/custom-config")
async def update_custom_config(
    domain_id:    int,
    payload:      CustomConfigRequest,
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """Guarda directivas nginx/apache personalizadas del dominio y regenera el
    vhost. Valida (nginx -t / apache configtest vía regenerate_vhost); si falla,
    revierte al valor anterior y devuelve 422 con el error."""
    domain = _get_owned_domain(domain_id, db, current_user)
    owner = db.query(User).filter(User.id == domain.user_id).first()
    if not owner:
        raise HTTPException(status_code=409, detail="El dominio no tiene propietario")

    nginx_cfg = (payload.custom_nginx_config or "").strip() or None
    apache_cfg = (payload.custom_apache_config or "").strip() or None

    # Sanitización: no permitir pegar un vhost completo (solo fragmentos).
    if nginx_cfg:
        low = nginx_cfg.lower()
        if any(tok in low for tok in _FORBIDDEN_NGINX):
            raise HTTPException(status_code=400, detail=(
                "No incluyas bloques 'server {' ni 'http {': pega solo directivas "
                "(p. ej. location, add_header…), se inyectan dentro del server del dominio."))
    if apache_cfg:
        low = apache_cfg.lower()
        if any(tok in low for tok in _FORBIDDEN_APACHE):
            raise HTTPException(status_code=400, detail=(
                "No incluyas <VirtualHost>: pega solo directivas, se inyectan dentro "
                "del VirtualHost del dominio."))

    # Guardar valores anteriores para poder revertir si la validación falla.
    prev_nginx = domain.custom_nginx_config
    prev_apache = domain.custom_apache_config

    domain.custom_nginx_config = nginx_cfg
    domain.custom_apache_config = apache_cfg
    db.commit()
    db.refresh(domain)

    try:
        _regenerate_domain_vhost(domain, owner)
    except Exception as e:
        # Revertir: restaurar los valores anteriores y regenerar con ellos.
        domain.custom_nginx_config = prev_nginx
        domain.custom_apache_config = prev_apache
        db.commit()
        try:
            _regenerate_domain_vhost(domain, owner)
        except Exception:
            pass
        raise HTTPException(status_code=422, detail=(
            f"La configuración no es válida y se ha descartado: {e}"))

    return {"status": "success", "data": {
        "custom_nginx_config": domain.custom_nginx_config,
        "custom_apache_config": domain.custom_apache_config,
    }}


class HttpauthRequest(BaseModel):
    enabled:  bool = False
    user:     Optional[str] = _Field(None, max_length=64)
    password: Optional[str] = _Field(None, max_length=128)


@router.put("/domains/{domain_id}/httpauth")
async def update_httpauth(
    domain_id:    int,
    payload:      HttpauthRequest,
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """Activa/desactiva la protección con contraseña (auth básica) del dominio.

    Gestiona el fichero .htpasswd y regenera el vhost (valida y revierte si falla).
    """
    import re as _re
    domain = _get_owned_domain(domain_id, db, current_user)
    owner = db.query(User).filter(User.id == domain.user_id).first()
    if not owner:
        raise HTTPException(status_code=409, detail="El dominio no tiene propietario")

    mgr = DomainManager()
    prev = {
        "enabled": domain.httpauth_enabled,
        "user": domain.httpauth_user,
        "hash": domain.httpauth_pass_hash,
    }

    if payload.enabled:
        user = (payload.user or "").strip()
        if not _re.match(r"^[A-Za-z0-9._-]{2,64}$", user):
            raise HTTPException(status_code=400,
                detail="Usuario no válido (2-64 caracteres: letras, números, . _ -).")
        if payload.password:
            if len(payload.password) < 4:
                raise HTTPException(status_code=400,
                    detail="La contraseña debe tener al menos 4 caracteres.")
            try:
                pass_hash = mgr.write_htpasswd(owner.username, domain.domain_name, user, payload.password)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"No pude crear el .htpasswd: {e}")
        else:
            # Sin password nuevo: conservar el hash existente (cambio de usuario o
            # re-activación). Si no hay hash previo, es obligatorio.
            if not domain.httpauth_pass_hash:
                raise HTTPException(status_code=400, detail="Indica una contraseña.")
            pass_hash = domain.httpauth_pass_hash
            try:
                mgr.write_htpasswd_hash(owner.username, domain.domain_name, user, pass_hash)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"No pude actualizar el .htpasswd: {e}")
        domain.httpauth_enabled = True
        domain.httpauth_user = user
        domain.httpauth_pass_hash = pass_hash
    else:
        domain.httpauth_enabled = False
        mgr.remove_htpasswd(owner.username, domain.domain_name)
        # Conservamos user/hash en BD por si reactiva (no recordar la pass otra vez).

    db.commit()
    db.refresh(domain)

    try:
        _regenerate_domain_vhost(domain, owner)
    except Exception as e:
        # Revertir estado y vhost.
        domain.httpauth_enabled = prev["enabled"]
        domain.httpauth_user = prev["user"]
        domain.httpauth_pass_hash = prev["hash"]
        if prev["enabled"] and prev["hash"] and prev["user"]:
            mgr.write_htpasswd_hash(owner.username, domain.domain_name, prev["user"], prev["hash"])
        else:
            mgr.remove_htpasswd(owner.username, domain.domain_name)
        db.commit()
        try:
            _regenerate_domain_vhost(domain, owner)
        except Exception:
            pass
        raise HTTPException(status_code=422, detail=f"No se pudo aplicar la protección: {e}")

    return {"status": "success", "data": {
        "httpauth_enabled": domain.httpauth_enabled,
        "httpauth_user": domain.httpauth_user,
    }}


def _disk_payload(domain) -> dict:
    """Construye la respuesta de peso a partir de los bytes cacheados en BD."""
    public_bytes = domain.disk_public_html_bytes or 0
    logs_bytes   = domain.disk_logs_bytes or 0
    total_bytes  = domain.disk_total_bytes or 0
    return {
        "domain":            domain.domain_name,
        "public_html_mb":    public_bytes // (1024 * 1024),
        "public_html_bytes": public_bytes,
        "logs_mb":           logs_bytes // (1024 * 1024),
        "logs_bytes":        logs_bytes,
        "total_mb":          total_bytes // (1024 * 1024),
        "total_bytes":       total_bytes,
        "calculated_at":     domain.disk_calculated_at.isoformat() if domain.disk_calculated_at else None,
    }


def compute_domain_disk(domain, db: Session) -> dict:
    """
    Calcula el peso real en disco (du -sb) del dominio y lo PERSISTE en BD.
    Caro (recorre todo el árbol): se llama desde el cron 2/día o bajo demanda
    (botón refrescar), NO en cada carga de la lista de dominios.
    """
    import os
    import subprocess
    from datetime import datetime

    base = _domain_owner_dir(domain, db)

    def _du_bytes(path: str) -> int:
        if not os.path.isdir(path):
            return 0
        try:
            r = subprocess.run(
                ["/usr/bin/du", "-sb", "--apparent-size", path],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode != 0:
                return 0
            return int(r.stdout.split()[0])
        except (subprocess.TimeoutExpired, ValueError, IndexError, FileNotFoundError):
            return 0

    public_bytes = _du_bytes(os.path.join(base, "public_html"))
    total_bytes  = _du_bytes(base)
    logs_bytes   = _du_bytes(os.path.join(base, "logs"))

    domain.disk_public_html_bytes = public_bytes
    domain.disk_logs_bytes        = logs_bytes
    domain.disk_total_bytes       = total_bytes
    domain.disk_calculated_at     = datetime.utcnow()
    db.commit()
    db.refresh(domain)
    return _disk_payload(domain)


@router.get("/domains/{domain_id}/disk")
async def get_domain_disk(
    domain_id:   int,
    refresh:     bool = False,
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """
    Peso en disco del dominio (public_html / logs / total).

    Por defecto devuelve el valor CACHEADO en BD (instantáneo). Con ?refresh=true
    recalcula con du (caro) y persiste el nuevo valor — para el botón "refrescar"
    de un dominio concreto. Los dominios solo-correo/DNS no tienen web → 0.
    """
    domain = _get_owned_domain(domain_id, db, current_user)
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    _check_access(current_user, domain, db)

    if getattr(domain, "mail_dns_only", False):
        return _disk_payload(domain)   # sin web: ceros (o lo último cacheado)

    if refresh:
        return compute_domain_disk(domain, db)
    return _disk_payload(domain)


# ─────────────────────────────────────────────────────────────────────────────
# Suspensión individual de dominio
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/domains/{domain_id}/stats")
async def domain_stats(
    domain_id:    int,
    current_user: User = Depends(require_auth),
    db:           Session = Depends(get_db),
):
    """Informe de visitas (GoAccess) del dominio, generado bajo demanda.

    Devuelve un HTML autocontenido (el frontend lo embebe en un iframe). El
    temporal se borra tras el envío.
    """
    domain = _get_owned_domain(domain_id, db, current_user)
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    _check_access(current_user, domain, db)
    owner = db.query(User).filter(User.id == domain.user_id).first()
    if not owner:
        raise HTTPException(status_code=404, detail="Propietario del dominio no encontrado")

    from scripts.web_stats import generate_goaccess_report, WebStatsError
    try:
        html_path = generate_goaccess_report(owner.username, domain.domain_name)
    except WebStatsError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generando estadísticas: {e}")

    return FileResponse(
        html_path,
        media_type="text/html",
        background=BackgroundTask(lambda: os.path.exists(html_path) and os.remove(html_path)),
    )


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


class AppInstallRequest(BaseModel):
    app: str = _Field(..., description="Slug de la app: wordpress, laravel, nextcloud")
    admin_user: str = _Field("admin", min_length=2, max_length=60)
    # admin_password/email solo son obligatorios para apps con setup de admin
    # (wordpress, nextcloud). Laravel no los usa. Validamos en el endpoint.
    admin_password: Optional[str] = _Field(None, max_length=128)
    admin_email: Optional[str] = _Field(None, max_length=160)
    # Idioma de WordPress (locale wp-cli, p. ej. es_ES). Default español; se
    # valida/normaliza en el instalador. Ignorado por el resto de apps.
    locale: Optional[str] = _Field(None, max_length=10)


@router.get("/apps/wordpress/locales")
async def wordpress_locales(current_user: User = Depends(require_auth)):
    """Idiomas disponibles para instalar WordPress (es_ES es el por defecto)."""
    from scripts.app_installer import WP_LOCALES, WP_DEFAULT_LOCALE
    return {
        "default": WP_DEFAULT_LOCALE,
        "locales": [{"code": c, "label": l} for c, l in WP_LOCALES.items()],
    }


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
    if getattr(domain, "mail_dns_only", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este dominio es solo correo/DNS (sin web): no se pueden instalar aplicaciones.",
        )
    owner = db.query(User).filter(User.id == domain.user_id).first()
    if not owner:
        raise HTTPException(status_code=409, detail="El dominio no tiene propietario")

    app = (payload.app or "").lower().strip()
    from scripts.app_installer import AppInstaller, SUPPORTED_APPS, RequirementsError
    if app not in SUPPORTED_APPS:
        raise HTTPException(status_code=400, detail=f"App no soportada: {app}")

    # Apps con cuenta de administrador requieren contraseña (mín. 8)
    if app in ("wordpress", "nextcloud", "prestashop"):
        if not payload.admin_password or len(payload.admin_password) < 8:
            raise HTTPException(status_code=400,
                                detail="La contraseña de administrador es obligatoria (mínimo 8 caracteres)")
        # WordPress y PrestaShop necesitan email (PrestaShop entra con el email)
        if app in ("wordpress", "prestashop") and not payload.admin_email:
            raise HTTPException(status_code=400,
                                detail=f"El email de administrador es obligatorio para {SUPPORTED_APPS[app]['name']}")

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
                locale=payload.locale or "es_ES",
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
        elif app == "prestashop":
            result = installer.install_prestashop(
                domain=domain.domain_name,
                owner=owner.username,
                docroot=docroot,
                admin_user=payload.admin_user,
                admin_pass=payload.admin_password,
                admin_email=payload.admin_email,
                php_version=domain.php_version,
            )
            try:
                _apply_builtin_template(domain, "prestashop", owner, db)
            except Exception as ve:
                result["warning"] = f"PrestaShop instalado; aplica la plantilla 'prestashop' manualmente: {ve}"
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

    # Registrar la BD creada por el instalador en el panel (client_databases)
    # El instalador devuelve la BD en result["db"] (WordPress/Laravel) o en result directamente
    _db_info = result.get("db") or result
    if _db_info.get("db_name") and _db_info.get("db_user"):
        try:
            from api.models.models_client_db import ClientDatabase
            from api.routes.databases import _hash_password, _encrypt_password
            existing = db.query(ClientDatabase).filter(
                ClientDatabase.db_name == _db_info["db_name"]
            ).first()
            if not existing:
                _pw = _db_info.get("db_pass", "")
                _suffix = _db_info["db_name"].split("_", 1)[-1] if "_" in _db_info["db_name"] else _db_info["db_name"]
                _usuffix = _db_info["db_user"].split("_", 1)[-1] if "_" in _db_info["db_user"] else _db_info["db_user"]
                client_db = ClientDatabase(
                    user_id=owner.id,
                    domain_id=domain.id,
                    db_name=_db_info["db_name"],
                    db_name_suffix=_suffix,
                    db_user=_db_info["db_user"],
                    db_user_suffix=_usuffix,
                    db_password_hash=_hash_password(_pw),
                    db_password_enc=_encrypt_password(_pw),
                    is_active=True,
                )
                db.add(client_db)
                db.commit()
        except Exception as reg_err:
            import logging
            logging.getLogger(__name__).warning(f"No se pudo registrar BD en panel: {reg_err}")

    return {"status": "success", "message": f"{SUPPORTED_APPS[app]['name']} instalado", "data": result}


# ─────────────────────────────────────────────────────────────────────────────
# Gestión de WordPress instalado (estilo WP Toolkit)
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_docroot_owner(domain_id: int, db: Session, current_user: User):
    """Devuelve (domain, owner_username, docroot) validando propiedad."""
    domain = _get_owned_domain(domain_id, db, current_user)
    owner = db.query(User).filter(User.id == domain.user_id).first()
    if not owner:
        raise HTTPException(status_code=409, detail="El dominio no tiene propietario")
    docroot = domain.custom_docroot or get_domain_root(owner.username, domain.domain_name) + "/public_html"
    return domain, owner.username, docroot


def _wp_guard(docroot: str, owner: str):
    """Lanza 409 si en el docroot no hay un WordPress gestionable."""
    from scripts.wp_manager import detect_app
    det = detect_app(docroot, owner)
    if det.get("app") != "wordpress":
        raise HTTPException(status_code=409,
                            detail="Este dominio no tiene una instalación de WordPress.")


class WpActionRequest(BaseModel):
    kind:       Optional[str] = _Field(None, description="plugin|theme")
    name:       Optional[str] = _Field(None, max_length=120)
    activate:   Optional[bool] = None
    enable:     Optional[bool] = None
    user_login: Optional[str] = _Field(None, max_length=120)
    password:   Optional[str] = _Field(None, max_length=128)
    url:        Optional[str] = _Field(None, max_length=200)


@router.get("/domains/{domain_id}/app")
async def get_domain_app(domain_id: int,
                         current_user: User = Depends(require_auth),
                         db: Session = Depends(get_db)):
    """Detecta qué app hay instalada en el dominio (y si es gestionable)."""
    _domain, owner, docroot = _resolve_docroot_owner(domain_id, db, current_user)
    from scripts.wp_manager import detect_app
    return {"status": "success", "data": detect_app(docroot, owner)}


@router.get("/domains/{domain_id}/wp/info")
async def wp_get_info(domain_id: int,
                      updates: bool = False,
                      current_user: User = Depends(require_auth),
                      db: Session = Depends(get_db)):
    """Resumen del WordPress. ?updates=1 incluye el chequeo de actualizaciones
    (consulta a wordpress.org, más lento); por defecto se omite para que la
    carga inicial sea rápida."""
    _domain, owner, docroot = _resolve_docroot_owner(domain_id, db, current_user)
    _wp_guard(docroot, owner)
    from scripts.wp_manager import wp_info, WpError
    try:
        return {"status": "success", "data": wp_info(docroot, owner, with_updates=updates)}
    except WpError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/domains/{domain_id}/wp/updates")
async def wp_get_updates(domain_id: int,
                         current_user: User = Depends(require_auth),
                         db: Session = Depends(get_db)):
    """Solo el resumen de actualizaciones pendientes (consulta la red)."""
    _domain, owner, docroot = _resolve_docroot_owner(domain_id, db, current_user)
    _wp_guard(docroot, owner)
    from scripts.wp_manager import wp_updates_summary, WpError
    try:
        return {"status": "success", "data": wp_updates_summary(docroot, owner)}
    except WpError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/domains/{domain_id}/wp/{kind}s")
async def wp_list_items(domain_id: int, kind: str,
                        current_user: User = Depends(require_auth),
                        db: Session = Depends(get_db)):
    """Lista plugins o temas (kind = 'plugin' | 'theme')."""
    if kind not in ("plugin", "theme"):
        raise HTTPException(status_code=400, detail="kind debe ser plugin o theme")
    _domain, owner, docroot = _resolve_docroot_owner(domain_id, db, current_user)
    _wp_guard(docroot, owner)
    from scripts.wp_manager import wp_list, WpError
    try:
        return {"status": "success", "data": wp_list(docroot, owner, kind)}
    except WpError as e:
        raise HTTPException(status_code=422, detail=str(e))


class WpCliRequest(BaseModel):
    command: str = _Field(..., max_length=2000,
                          description="Comando wp-cli, con o sin el 'wp' inicial")


# OJO: declarado ANTES de /wp/{action} para que 'cli' no caiga en la ruta genérica.
@router.post("/domains/{domain_id}/wp/cli")
async def wp_cli_console(domain_id: int,
                         payload: WpCliRequest,
                         request: Request,
                         current_user: User = Depends(require_auth),
                         db: Session = Depends(get_db)):
    """
    Consola WP-CLI del dominio (estilo Plesk). Ejecuta el comando SIEMPRE como
    el usuario del dominio (mismo privilegio que su propio PHP; nunca root).
    Flags que salen del dominio (--path/--ssh/--http/--require/--exec) y
    comandos interactivos están bloqueados. Cada comando queda en el audit log.
    """
    from scripts.wp_manager import wp_cli_run, WpError
    from api.utils.security_audit import log_audit

    domain, owner, docroot = _resolve_docroot_owner(domain_id, db, current_user)
    _wp_guard(docroot, owner)
    try:
        data = wp_cli_run(docroot, owner, payload.command)
    except WpError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error ejecutando wp-cli: {e}")

    log_audit(db, user=current_user, category="wpcli", action="run",
              target=domain.domain_name, after={"command": data["command"],
                                                "rc": data["rc"]},
              request=request, success=data["rc"] == 0,
              error=None if data["rc"] == 0 else (data["stderr"] or "")[:500])
    return {"status": "success", "data": data}


@router.post("/domains/{domain_id}/wp/{action}")
async def wp_action(domain_id: int, action: str,
                    payload: WpActionRequest,
                    current_user: User = Depends(require_auth),
                    db: Session = Depends(get_db)):
    """Ejecuta una acción de gestión sobre el WordPress del dominio."""
    _domain, owner, docroot = _resolve_docroot_owner(domain_id, db, current_user)
    _wp_guard(docroot, owner)
    import scripts.wp_manager as wpm
    from scripts.wp_manager import WpError
    try:
        if action == "update-core":
            data = wpm.wp_update_core(docroot, owner)
        elif action == "update-items":
            if payload.kind not in ("plugin", "theme"):
                raise HTTPException(status_code=400, detail="kind debe ser plugin o theme")
            data = wpm.wp_update_items(docroot, owner, payload.kind, payload.name)
        elif action == "toggle-item":
            if payload.kind not in ("plugin", "theme") or not payload.name:
                raise HTTPException(status_code=400, detail="kind y name son obligatorios")
            data = wpm.wp_toggle_item(docroot, owner, payload.kind, payload.name,
                                      bool(payload.activate))
        elif action == "delete-item":
            if payload.kind not in ("plugin", "theme") or not payload.name:
                raise HTTPException(status_code=400, detail="kind y name son obligatorios")
            data = wpm.wp_delete_item(docroot, owner, payload.kind, payload.name)
        elif action == "flush-permalinks":
            data = wpm.wp_flush_permalinks(docroot, owner)
        elif action == "maintenance":
            data = wpm.wp_maintenance(docroot, owner, bool(payload.enable))
        elif action == "regenerate-salts":
            data = wpm.wp_regenerate_salts(docroot, owner)
        elif action == "flush-cache":
            data = wpm.wp_flush_cache(docroot, owner)
        elif action == "admin-users":
            data = {"users": wpm.wp_admin_users(docroot, owner)}
        elif action == "reset-password":
            if not payload.user_login:
                raise HTTPException(status_code=400, detail="user_login es obligatorio")
            data = wpm.wp_reset_password(docroot, owner, payload.user_login, payload.password)
        elif action == "set-url":
            if not payload.url:
                raise HTTPException(status_code=400, detail="url es obligatoria")
            data = wpm.wp_set_url(docroot, owner, payload.url)
        elif action == "login-link":
            if not payload.user_login:
                raise HTTPException(status_code=400, detail="user_login es obligatorio")
            data = wpm.wp_login_link(docroot, owner, payload.user_login)
        else:
            raise HTTPException(status_code=400, detail=f"Acción no soportada: {action}")
        return {"status": "success", "data": data}
    except HTTPException:
        raise
    except WpError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en acción WP: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Composer — dependencias PHP del proyecto del cliente (require/remove/update/…)
# El binario composer es del sistema (solo admin lo actualiza vía self-update);
# aquí SOLO se gestionan las dependencias del docroot, como el usuario del dominio.
# ─────────────────────────────────────────────────────────────────────────────
class ComposerActionRequest(BaseModel):
    package: Optional[str] = _Field(None, max_length=180,
                                    description="vendor/paquete, p. ej. phpmailer/phpmailer")
    dev:     Optional[bool] = False


@router.get("/domains/{domain_id}/composer/status")
async def composer_get_status(domain_id: int,
                              current_user: User = Depends(require_auth),
                              db: Session = Depends(get_db)):
    """Estado de Composer en el docroot: composer.json/lock/vendor + versión."""
    _domain, owner, docroot = _resolve_docroot_owner(domain_id, db, current_user)
    from scripts.composer_manager import composer_status, ComposerError
    try:
        return {"status": "success", "data": composer_status(docroot, owner)}
    except ComposerError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/domains/{domain_id}/composer/packages")
async def composer_get_packages(domain_id: int,
                                current_user: User = Depends(require_auth),
                                db: Session = Depends(get_db)):
    """Paquetes instalados (vendor/) con su versión."""
    _domain, owner, docroot = _resolve_docroot_owner(domain_id, db, current_user)
    from scripts.composer_manager import composer_packages, ComposerError
    try:
        return {"status": "success", "data": composer_packages(docroot, owner)}
    except ComposerError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/domains/{domain_id}/composer/{action}")
async def composer_action(domain_id: int, action: str,
                          payload: ComposerActionRequest,
                          current_user: User = Depends(require_auth),
                          db: Session = Depends(get_db)):
    """Ejecuta una acción Composer sobre el proyecto del dominio.

    action: require | remove | update | install
    Body: {package?: "vendor/nombre", dev?: bool}
      - require/remove: package obligatorio.
      - update: package opcional (sin él, actualiza todo el proyecto).
      - install: instala lo declarado en composer.json/lock.
    """
    _domain, owner, docroot = _resolve_docroot_owner(domain_id, db, current_user)
    import scripts.composer_manager as cm
    from scripts.composer_manager import ComposerError
    try:
        if action == "require":
            if not payload.package:
                raise HTTPException(status_code=400, detail="package es obligatorio")
            data = cm.composer_require(docroot, owner, payload.package, bool(payload.dev))
        elif action == "remove":
            if not payload.package:
                raise HTTPException(status_code=400, detail="package es obligatorio")
            data = cm.composer_remove(docroot, owner, payload.package)
        elif action == "update":
            data = cm.composer_update(docroot, owner, payload.package or None)
        elif action == "install":
            data = cm.composer_install(docroot, owner)
        else:
            raise HTTPException(status_code=400, detail=f"Acción no soportada: {action}")
        return {"status": "success", "data": data}
    except HTTPException:
        raise
    except ComposerError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en acción Composer: {e}")
