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
from api.models.models_user import User as UserModel
from scripts.ipv6_manager import IPv6Manager
from scripts.domain_manager import DomainManager

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


def _owned_domain(domain_id: int, db: Session, user: User) -> Domain:
    """Dominio accesible por el usuario (mismo criterio que /domains: 404 si no).

    Antes estos endpoints buscaban el dominio solo por ID: cualquier cliente con
    sesión podía asignar o quitar la IPv6 de un dominio ajeno (IDOR).
    """
    from api.routes.domains import _get_owned_domain
    return _get_owned_domain(domain_id, db, user)


def _is_admin(user: User) -> bool:
    return bool(getattr(user, "is_admin", False) or getattr(user, "role", "") == "admin")


def _validate_assignable(db: Session, domain: Domain, ipv6: str) -> None:
    """La IPv6 debe ser del rango del servidor y estar libre.

    Sin esto se podía poner en la interfaz CUALQUIER IPv6 (la del gateway, la
    principal del servidor, la de otro dominio…) y dejar la red sin IPv6.
    """
    import ipaddress
    from api.models.models_settings import Settings
    addr = ipaddress.IPv6Address(ipv6)
    s = db.query(Settings).filter(Settings.id == 1).first()
    rng = (getattr(s, "ipv6_range", None) or "").strip() if s else ""
    if not rng:
        raise HTTPException(status_code=409,
            detail="El servidor no tiene un rango IPv6 configurado (Configuración → IPv6).")
    try:
        net = ipaddress.IPv6Network(rng, strict=False)
    except ValueError:
        raise HTTPException(status_code=409, detail=f"Rango IPv6 del servidor no válido: {rng}")
    if addr not in net or addr == net.network_address:
        raise HTTPException(status_code=400,
            detail=f"La IPv6 debe pertenecer al rango del servidor ({net}).")
    try:
        from api.routes.dns import _get_server_ipv6
        main = _get_server_ipv6(db)
        if main and ipaddress.IPv6Address(main) == addr:
            raise HTTPException(status_code=400,
                detail="Esa es la IPv6 principal del servidor: elige otra del rango.")
    except HTTPException:
        raise
    except Exception:
        pass
    other = db.query(Domain).filter(Domain.ipv6 == str(addr), Domain.id != domain.id).first()
    if other:
        raise HTTPException(status_code=409,
            detail=f"Esa IPv6 ya está asignada a {other.domain_name}.")


@router.post("/domains/{domain_id}/ipv6", response_model=IPv6Response, status_code=status.HTTP_201_CREATED)
async def assign_ipv6(
    domain_id: int,
    data: IPv6Assign,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Asignar (o cambiar) la dirección IPv6 de un dominio.

    Si el dominio ya tenía una, la anterior se quita del servidor DESPUÉS de
    poner la nueva (así nunca se queda sin IPv6 a medias)."""
    ipv6_manager = IPv6Manager()

    domain = _owned_domain(domain_id, db, current_user)
    _validate_assignable(db, domain, data.ipv6_address)
    previous = domain.ipv6 if domain.ipv6 and domain.ipv6 != data.ipv6_address else None

    # La interfaz solo la elige el admin (un cliente podría apuntar a otra).
    interface = _get_interface(db, data.network_interface if _is_admin(current_user) else None)

    # Obtener usuario propietario del dominio
    owner = db.query(UserModel).filter(UserModel.id == domain.user_id).first()
    if not owner:
        raise HTTPException(status_code=404, detail="Propietario del dominio no encontrado")

    # 1. Añadir IPv6 a la interfaz de red
    try:
        ipv6_manager.assign_ipv6(interface, data.ipv6_address)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al añadir IPv6 a la interfaz: {str(e)}"
        )

    # 2. Guardar en BD
    try:
        domain.ipv6 = data.ipv6_address
        db.commit()
        db.refresh(domain)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar IPv6: {str(e)}")

    # 3. Regenerar el vhost preservando TODO el estado del dominio (modo Apache
    #    incluido). Usamos el regenerador completo, NO update_nginx_ipv6, que
    #    perdía proxy_to_apache y el resto de directivas → rompía el dominio en
    #    modo Apache+Nginx al asignar IPv6.
    try:
        from api.routes.domains import _regenerate_domain_vhost
        _regenerate_domain_vhost(domain, owner)
    except Exception as e:
        # nginx falló pero la IP ya está asignada — avisar pero no revertir
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"IPv6 asignada pero error al actualizar el vhost: {str(e)}"
        )

    # 4. Sincronizar AAAA en la zona DNS (si el panel la gestiona). No-op si el
    #    dominio usa DNS externo. No revertimos la asignación si esto falla.
    try:
        from api.routes.dns import sync_aaaa_records_for_domain
        sync_aaaa_records_for_domain(domain.domain_name, data.ipv6_address, db)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            f"IPv6 asignada pero no se pudo sincronizar AAAA en DNS: {e}")

    # 5. Cambio de IPv6: quitar la anterior del servidor (ya no la usa nadie)
    if previous:
        try:
            ipv6_manager.remove_ipv6(interface, previous)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"No se pudo quitar la IPv6 anterior {previous} del sistema: {e}")

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
    domain = _owned_domain(domain_id, db, current_user)

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

    domain = _owned_domain(domain_id, db, current_user)

    owner = db.query(UserModel).filter(UserModel.id == domain.user_id).first()
    interface = _get_interface(db)

    if domain.ipv6:
        # 1. Quitar IPv6 de la interfaz
        try:
            ipv6_manager.remove_ipv6(interface, domain.ipv6)
        except Exception as e:
            print(f"Warning: no se pudo quitar IPv6 del sistema: {e}")

        # 2. Poner ipv6=None ANTES de regenerar (el regenerador lee domain.ipv6)
        domain.ipv6 = None
        db.commit()
        db.refresh(domain)

        # 3. Regenerar el vhost SIN IPv6, preservando el resto (modo Apache incl.)
        if owner:
            try:
                from api.routes.domains import _regenerate_domain_vhost
                _regenerate_domain_vhost(domain, owner)
            except Exception as e:
                print(f"Warning: no se pudo actualizar el vhost: {e}")

        # 4. Quitar los AAAA de la zona DNS (no-op si DNS externo).
        try:
            from api.routes.dns import sync_aaaa_records_for_domain
            sync_aaaa_records_for_domain(domain.domain_name, None, db)
        except Exception as e:
            print(f"Warning: no se pudieron quitar los AAAA del DNS: {e}")
    else:
        domain.ipv6 = None
        db.commit()
    return None
