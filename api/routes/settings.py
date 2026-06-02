"""
Rutas API para configuración del panel
"""

import ipaddress
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from api.models.database import get_db
from api.models.models_settings import Settings
from api.models.models_domain import Domain
from api.schemas.settings_schemas import SettingsUpdate, SettingsResponse, IssuePanelSSLRequest
from api.dependencies import require_admin, require_auth

router = APIRouter()


def _timedatectl_bin():
    """
    Ruta absoluta a timedatectl. El servicio systemd corre con PATH reducido
    (solo el venv), así que invocar 'timedatectl' a secas da FileNotFoundError.
    Devuelve None si no existe (entorno de desarrollo sin systemd).
    """
    import os, shutil
    for path in ("/usr/bin/timedatectl", "/bin/timedatectl", "/usr/sbin/timedatectl"):
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return shutil.which("timedatectl")


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


@router.post("/settings/issue-ssl")
async def issue_panel_ssl(
    data: IssuePanelSSLRequest,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Emite un certificado Let's Encrypt para el hostname del panel y configura
    nginx para servirlo por HTTPS.
    """
    from scripts.panel_ssl_manager import PanelSSLManager

    settings = get_or_create_settings(db)

    try:
        mgr = PanelSSLManager()
        result = mgr.issue_ssl(data.hostname, data.email, data.force_https)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se necesitan privilegios de root para emitir el certificado"
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    # Actualizar BD
    settings.panel_hostname = data.hostname
    settings.ssl_panel_enabled = True
    settings.force_https = data.force_https
    if result.get("expires"):
        try:
            settings.ssl_panel_expires = datetime.fromisoformat(result["expires"])
        except Exception:
            pass
    db.commit()
    db.refresh(settings)

    return {
        "success": True,
        "hostname": data.hostname,
        "ssl_enabled": True,
        "force_https": data.force_https,
        "expires": result.get("expires"),
        "message": f"Certificado SSL emitido correctamente para {data.hostname}"
    }


@router.post("/settings/revoke-ssl")
async def revoke_panel_ssl(
    current_user=Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Revoca el certificado SSL del panel y vuelve a HTTP simple.
    """
    from scripts.panel_ssl_manager import PanelSSLManager

    settings = get_or_create_settings(db)

    if not settings.panel_hostname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No hay hostname configurado para el panel"
        )

    try:
        mgr = PanelSSLManager()
        mgr.revoke_ssl(settings.panel_hostname)
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se necesitan privilegios de root para revocar el certificado"
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    settings.ssl_panel_enabled = False
    settings.ssl_panel_expires = None
    settings.force_https = False
    db.commit()
    db.refresh(settings)

    return {
        "success": True,
        "message": "Certificado SSL del panel revocado. El panel vuelve a HTTP."
    }


# ─── SMTP relay global (smarthost) ───────────────────────────────────────────

from pydantic import BaseModel as _BM, Field as _F


class GlobalRelayRequest(_BM):
    enabled:  bool = True
    host:     str = _F("", max_length=255)
    port:     int = _F(587, ge=1, le=65535)
    username: str = _F("", max_length=255)
    password: str = _F("", max_length=255)


@router.get("/settings/relay")
async def get_global_relay(current_user=Depends(require_admin), db: Session = Depends(get_db)):
    """Configuración del relay SMTP global del servidor (sin la contraseña)."""
    s = get_or_create_settings(db)
    return {
        "enabled":  bool(s.relay_enabled),
        "host":     s.relay_host or "",
        "port":     s.relay_port or 587,
        "username": s.relay_username or "",
        "has_password": bool(s.relay_username),  # si hay user, asumimos pass guardada
    }


@router.post("/settings/relay")
async def set_global_relay(data: GlobalRelayRequest,
                           current_user=Depends(require_admin),
                           db: Session = Depends(get_db)):
    """
    Configura/actualiza o desactiva el relay SMTP global. Si enabled=False,
    se quita el relayhost (vuelta a envío directo).
    """
    s = get_or_create_settings(db)
    from scripts.mail_manager import MailManager

    if not data.enabled:
        s.relay_enabled = False
        db.commit()
        try:
            MailManager().remove_global_relay()
        except PermissionError:
            raise HTTPException(403, "Se necesitan privilegios root")
        except Exception as e:
            raise HTTPException(502, f"Error quitando el relay: {e}")
        return {"status": "success", "enabled": False}

    if not data.host:
        raise HTTPException(400, "Indica el host del relay")

    s.relay_enabled  = True
    s.relay_host     = data.host.strip()
    s.relay_port     = data.port
    s.relay_username = data.username.strip() or None
    db.commit()

    try:
        MailManager().set_global_relay(data.host, data.port, data.username, data.password)
    except PermissionError:
        raise HTTPException(403, "Se necesitan privilegios root")
    except Exception as e:
        raise HTTPException(502, f"Error configurando el relay: {e}")

    return {"status": "success", "enabled": True, "host": data.host, "port": data.port}


# ─── Timezone ────────────────────────────────────────────────────────────────

@router.get("/settings/timezones")
async def list_timezones(current_user=Depends(require_admin)):
    """
    Devuelve la lista de zonas horarias disponibles en el sistema.
    Intenta usar zoneinfo (Python ≥3.9); si no, usa pytz como fallback.
    """
    try:
        from zoneinfo import available_timezones
        zones = sorted(available_timezones())
    except ImportError:
        try:
            import pytz
            zones = pytz.all_timezones
        except ImportError:
            # Fallback mínimo con zonas comunes
            zones = [
                "UTC", "Europe/Madrid", "Europe/London", "Europe/Paris",
                "Europe/Berlin", "Europe/Rome", "America/New_York",
                "America/Chicago", "America/Denver", "America/Los_Angeles",
                "America/Sao_Paulo", "America/Argentina/Buenos_Aires",
                "America/Mexico_City", "Asia/Tokyo", "Asia/Shanghai",
                "Asia/Dubai", "Asia/Kolkata", "Australia/Sydney",
                "Pacific/Auckland",
            ]
    return {"timezones": zones}


@router.get("/settings/timezone-current")
async def get_current_timezone(current_user=Depends(require_admin)):
    """
    Lee la zona horaria actual del sistema operativo (timedatectl).
    """
    import subprocess
    tz = "UTC"
    binary = _timedatectl_bin()
    if binary:
        try:
            r = subprocess.run(
                [binary, "show", "--property=Timezone", "--value"],
                capture_output=True, text=True, timeout=5,
            )
            tz = r.stdout.strip() or "UTC"
        except Exception:
            tz = "UTC"
    return {"timezone": tz}


@router.post("/settings/timezone")
async def set_timezone(
    data: dict,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Cambia la zona horaria del servidor via timedatectl y la guarda en BD.
    Body: { "timezone": "Europe/Madrid" }
    """
    import subprocess
    import re

    tz = (data.get("timezone") or "").strip()
    if not tz or not re.match(r'^[A-Za-z_/+\-0-9]+$', tz):
        raise HTTPException(status_code=400, detail="Zona horaria no válida")

    # Aplicar en el SO via timedatectl (ruta absoluta: el servicio tiene PATH reducido)
    binary = _timedatectl_bin()
    if binary:
        try:
            r = subprocess.run(
                [binary, "set-timezone", tz],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode != 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Zona horaria no reconocida por el sistema: {tz}"
                )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    # Si no hay timedatectl (entorno de desarrollo), solo se guarda en BD

    # Guardar en BD
    settings = get_or_create_settings(db)
    settings.timezone = tz
    db.commit()

    return {"success": True, "timezone": tz, "message": f"Zona horaria cambiada a {tz}"}
