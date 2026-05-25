"""
Rutas API para monitorización del sistema y control de servicios
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from api.models.database import get_db
from api.models.models_user import User
from api.models.models_domain import Domain
from api.models.models_dns import DnsZone
from api.dependencies import require_admin

router = APIRouter()


@router.get("/system/stats")
async def get_system_stats(
    current_user=Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Estadísticas del sistema + contadores del panel"""
    try:
        from scripts.services_manager import get_system_stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error importando services_manager: {str(e)}")

    sys = get_system_stats()

    # Contadores del panel
    total_users    = db.query(User).count()
    active_users   = db.query(User).filter(User.is_active == True).count()
    suspended_users = total_users - active_users
    total_domains  = db.query(Domain).count()
    active_domains = db.query(Domain).filter(Domain.is_active == True).count()
    total_dns_zones = db.query(DnsZone).count()

    try:
        from api.models.models_dns import DnsRecord
        total_dns_records = db.query(DnsRecord).count()
    except Exception:
        total_dns_records = 0

    return {
        # Sistema
        "os_name":     sys["os_name"],
        "uptime_str":  sys["uptime_str"],
        "uptime_days": sys["uptime_days"],
        "load_1":      sys["load_1"],
        "load_5":      sys["load_5"],
        "load_15":     sys["load_15"],
        "cpu_count":   sys["cpu_count"],
        # Panel
        "total_users":     total_users,
        "active_users":    active_users,
        "suspended_users": suspended_users,
        "total_domains":   total_domains,
        "active_domains":  active_domains,
        "total_dns_zones": total_dns_zones,
        "total_dns_records": total_dns_records,
    }


@router.get("/system/services")
async def list_services(
    current_user=Depends(require_admin),
):
    """Lista todos los servicios detectados en el sistema"""
    try:
        from scripts.services_manager import get_all_services
        return get_all_services()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al detectar servicios: {str(e)}"
        )



@router.post("/system/services/{service_name}/{action}")
async def control_service(
    service_name: str,
    action: str,
    current_user=Depends(require_admin),
):
    """
    Controla un servicio del sistema.
    Acciones: start | stop | restart | reload
    """
    # Validaciones de seguridad
    allowed_actions = {"start", "stop", "restart", "reload"}
    if action not in allowed_actions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Acción inválida. Permitidas: {', '.join(allowed_actions)}"
        )

    # Whitelist de servicios controlables (evitar ejecución arbitraria)
    allowed_prefixes = (
        "nginx", "apache2", "named", "bind9",
        "php", "postgresql", "mariadb", "mysql",
        "fail2ban", "ufw", "ssh", "vsftpd", "proftpd",
        "clamav", "dovecot", "exim4", "postfix",
        "redis", "memcached", "cron", "spamassassin", "spamd",
        "svqpanel",
    )
    if not any(service_name.startswith(p) for p in allowed_prefixes):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Servicio no permitido"
        )

    from scripts.services_manager import control_service
    try:
        result = control_service(service_name, action)
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result["output"]
            )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
