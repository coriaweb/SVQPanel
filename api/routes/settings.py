"""
Rutas API para configuración del panel
"""

import ipaddress
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from api.models.database import get_db
from api.models.models_settings import Settings
from api.models.models_domain import Domain
from api.schemas.settings_schemas import SettingsUpdate, SettingsResponse
from api.dependencies import require_admin, require_auth

router = APIRouter()


def get_or_create_settings(db: Session) -> Settings:
    """Devuelve la configuración del panel (la crea si no existe)"""
    settings = db.query(Settings).filter(Settings.id == 1).first()
    if not settings:
        settings = Settings(id=1)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def count_used_ipv6(db: Session, ipv6_range: str) -> int:
    """Cuenta cuántas IPs del rango están asignadas a dominios"""
    if not ipv6_range:
        return 0
    try:
        network = ipaddress.IPv6Network(ipv6_range, strict=False)
        domains_with_ipv6 = db.query(Domain).filter(Domain.ipv6 != None).all()
        count = 0
        for domain in domains_with_ipv6:
            try:
                if ipaddress.IPv6Address(domain.ipv6) in network:
                    count += 1
            except ValueError:
                pass
        return count
    except Exception:
        return 0


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(
    current_user=Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Obtener configuración del panel"""
    settings = get_or_create_settings(db)

    # Calcular info IPv6
    result = SettingsResponse.model_validate(settings)
    if settings.ipv6_range:
        try:
            network = ipaddress.IPv6Network(settings.ipv6_range, strict=False)
            # Para /64 son 2^64 IPs — mostramos un número razonable
            prefix = network.prefixlen
            available = min(2 ** (128 - prefix), 2**32)  # cap a ~4 mil millones
            result.ipv6_total_ips = available
            result.ipv6_used_ips = count_used_ipv6(db, settings.ipv6_range)
        except Exception:
            pass

    return result


@router.put("/settings", response_model=SettingsResponse)
async def update_settings(
    data: SettingsUpdate,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Actualizar configuración del panel"""
    settings = get_or_create_settings(db)

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(settings, field, value)

    db.commit()
    db.refresh(settings)

    result = SettingsResponse.model_validate(settings)
    if settings.ipv6_range:
        try:
            network = ipaddress.IPv6Network(settings.ipv6_range, strict=False)
            prefix = network.prefixlen
            result.ipv6_total_ips = min(2 ** (128 - prefix), 2**32)
            result.ipv6_used_ips = count_used_ipv6(db, settings.ipv6_range)
        except Exception:
            pass

    return result


@router.get("/settings/next-ipv6")
async def get_next_ipv6(
    current_user=Depends(require_auth),
    db: Session = Depends(get_db)
):
    """
    Devuelve la siguiente IPv6 disponible del rango configurado.
    Útil para asignar IPs dedicadas a nuevos dominios.
    """
    settings = get_or_create_settings(db)

    if not settings.ipv6_enabled or not settings.ipv6_range:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="IPv6 no está configurado en el panel"
        )

    try:
        network = ipaddress.IPv6Network(settings.ipv6_range, strict=False)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rango IPv6 configurado no es válido"
        )

    # IPs ya usadas
    used = set()
    domains_with_ipv6 = db.query(Domain).filter(Domain.ipv6 != None).all()
    for domain in domains_with_ipv6:
        try:
            addr = ipaddress.IPv6Address(domain.ipv6)
            if addr in network:
                used.add(addr)
        except ValueError:
            pass

    # Buscar la siguiente IP libre (empezamos en ::1, no en ::0 que es la dirección de red)
    hosts = network.hosts()
    next_ip = None
    for i, ip in enumerate(hosts):
        if i == 0:
            continue  # Saltar ::0
        if ip not in used:
            next_ip = str(ip)
            break
        if i > 65535:  # Máximo 64k IPs buscadas
            break

    if not next_ip:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No hay IPs IPv6 disponibles en el rango configurado"
        )

    return {
        "next_ipv6": next_ip,
        "range": settings.ipv6_range,
        "network_interface": settings.network_interface or "eth0",
        "used_count": len(used)
    }
