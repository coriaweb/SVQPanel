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
        "cpu_percent":   sys.get("cpu_percent", 0.0),
        "mem_total_mb":  sys.get("mem_total_mb", 0),
        "mem_used_mb":   sys.get("mem_used_mb", 0),
        "mem_percent":   sys.get("mem_percent", 0.0),
        "disk_total_gb": sys.get("disk_total_gb", 0),
        "disk_used_gb":  sys.get("disk_used_gb", 0),
        "disk_percent":  sys.get("disk_percent", 0.0),
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



@router.get("/system/services/{service_name}/configs")
async def get_service_config_list(
    service_name: str,
    current_user=Depends(require_admin),
):
    """Lista los ficheros de configuración disponibles para un servicio"""
    try:
        from scripts.config_manager import get_service_configs
        configs = get_service_configs(service_name)
        return [{"label": c["label"], "path": c["path"], "comment": c["comment"]} for c in configs]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/system/services/{service_name}/config/{file_label:path}")
async def read_service_config(
    service_name: str,
    file_label: str,
    current_user=Depends(require_admin),
):
    """Lee el contenido de un fichero de configuración de un servicio"""
    try:
        from scripts.config_manager import read_config
        return read_config(service_name, file_label)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/system/services/{service_name}/config/{file_label:path}")
async def write_service_config(
    service_name: str,
    file_label: str,
    body: dict,
    current_user=Depends(require_admin),
):
    """
    Guarda un fichero de configuración.
    Body: {"content": "..."}
    Hace backup automático, test de sintaxis y recarga el servicio.
    """
    content = body.get("content")
    if content is None:
        raise HTTPException(status_code=400, detail="Falta el campo 'content'")
    try:
        from scripts.config_manager import write_config
        return write_config(service_name, file_label, content)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
        "fail2ban", "crowdsec", "nftables", "ufw", "ssh", "vsftpd", "proftpd",
        "clamav", "dovecot", "exim4", "postfix",
        "redis", "memcached", "cron", "spamassassin", "spamd", "rspamd",
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


# ─── Actualizaciones del sistema ─────────────────────────────────────────────

@router.get("/system/updates")
async def get_system_updates(
    current_user=Depends(require_admin),
):
    """
    Refresca la lista de paquetes APT y devuelve los que tienen actualización disponible.
    Devuelve: { refreshed_at, packages: [{name, current, available, origin}] }
    """
    import subprocess
    from datetime import datetime as dt
    import os
    import shutil
    try:
        # Buscar apt-get y apt en el sistema
        apt_get_path = shutil.which("apt-get") or "/usr/bin/apt-get"
        apt_path = shutil.which("apt") or "/usr/bin/apt"

        # Refrescar índice APT
        current_uid = os.getuid()
        is_root = current_uid == 0

        if is_root:
            update_cmd = [apt_get_path, "update"]
            list_cmd = [apt_path, "list", "--upgradable"]
        else:
            update_cmd = ["sudo", apt_get_path, "update"]
            list_cmd = ["sudo", apt_path, "list", "--upgradable"]

        # Ejecutar apt update (no silencioso para asegurar que funciona)
        update_result = subprocess.run(update_cmd, capture_output=True, text=True, timeout=120)

        # No importa el resultado de update, continuamos con list
        # Listar actualizables
        result = subprocess.run(
            list_cmd,
            capture_output=True, text=True, timeout=60,
        )

        if result.returncode != 0 and "WARNING" not in result.stdout:
            raise Exception(f"apt list falló (code {result.returncode}): {result.stderr or result.stdout}")

        packages = []
        for line in result.stdout.splitlines():
            # Saltar advertencias y líneas vacías
            if not line.strip() or "WARNING:" in line or "Listing" in line:
                continue
            # Formato: pkg/origin version arch [upgradable from: old_version]
            if "[upgradable from:" not in line:
                continue
            try:
                # Extraer nombre/origen y versión disponible (antes de [)
                before_bracket = line[:line.index("[")].strip()
                parts = before_bracket.split()
                pkg_origin = parts[0]
                new_ver    = parts[1]  # Es el segundo campo (versión, no arch)

                # Extraer versión antigua (dentro de [upgradable from: ...])
                bracket_start = line.index("[upgradable from:")
                bracket_end = line.index("]", bracket_start)
                bracket_content = line[bracket_start:bracket_end + 1]
                old_ver = bracket_content.replace("[upgradable from:", "").replace("]", "").strip()

                pkg_name, _, origin = pkg_origin.partition("/")
                packages.append({
                    "name":      pkg_name,
                    "current":   old_ver,
                    "available": new_ver,
                    "origin":    origin,
                })
            except Exception:
                continue
        return {
            "refreshed_at": dt.utcnow().isoformat() + "Z",
            "count":    len(packages),
            "packages": packages,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error comprobando actualizaciones: {str(e)}")


@router.post("/system/updates/upgrade")
async def run_system_upgrade(
    body: dict = {},
    current_user=Depends(require_admin),
):
    """
    Ejecuta apt-get upgrade para un paquete concreto (body.package)
    o para todos los paquetes si no se especifica.
    """
    import subprocess
    import re
    import os
    import shutil

    package = (body or {}).get("package", "").strip()
    try:
        # Buscar apt-get en el sistema
        apt_get_path = shutil.which("apt-get") or "/usr/bin/apt-get"

        if package:
            # Validar: solo caracteres seguros para nombre de paquete
            if not re.match(r'^[a-zA-Z0-9._+\-]+$', package):
                raise HTTPException(status_code=400, detail="Nombre de paquete inválido")

        # Detección de root
        is_root = os.getuid() == 0

        if package:
            if is_root:
                cmd = [apt_get_path, "install", "--only-upgrade", "-y", package]
            else:
                cmd = ["sudo", apt_get_path, "install", "--only-upgrade", "-y", package]
        else:
            if is_root:
                cmd = [apt_get_path, "upgrade", "-y", "-o", "Dpkg::Options::=--force-confold"]
            else:
                cmd = ["sudo", apt_get_path, "upgrade", "-y", "-o", "Dpkg::Options::=--force-confold"]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return {
            "success":   result.returncode == 0,
            "package":   package or "all",
            "stdout":    result.stdout[-4000:] if result.stdout else "",
            "stderr":    result.stderr[-2000:] if result.stderr else "",
            "returncode": result.returncode,
        }
    except HTTPException:
        raise
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Tiempo de espera agotado (apt-get)")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error actualizando: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────────
# Versiones de componentes instalados
# ─────────────────────────────────────────────────────────────────────────────

def _get_version(command: list[str], pattern: str = None) -> str:
    """
    Ejecuta un comando y extrae la versión del output.
    Si pattern es None, devuelve la segunda línea (ej: "node -v" → "v24.16.0").
    Si pattern es string, extrae lo que coincida con el patrón regex.
    """
    try:
        import subprocess, re
        result = subprocess.run(command, capture_output=True, text=True, timeout=5)
        output = result.stdout.strip() + result.stderr.strip()
        if not output:
            return "desconocida"

        if pattern:
            match = re.search(pattern, output)
            return match.group(1) if match else "desconocida"
        else:
            # Devolver la primera línea que tenga contenido
            lines = [l.strip() for l in output.splitlines() if l.strip()]
            return lines[0] if lines else "desconocida"
    except Exception:
        return "no disponible"


@router.get("/system/versions")
async def get_system_versions(current_user=Depends(require_admin)):
    """
    Devuelve las versiones de todos los componentes instalados.
    """
    versions = {
        "components": {
            "Panel": {
                "name": "SVQPanel",
                "version": "1.0.0",  # TODO: leer de config/version.py
                "docs": "https://github.com/coriaweb/SVQPanel",
            },
            "Node.js": {
                "name": "Node.js",
                "version": _get_version(["node", "--version"]),
                "docs": "https://nodejs.org/en/download/package-manager",
            },
            "Nginx": {
                "name": "Nginx",
                "version": _get_version(["nginx", "-v"], r"nginx/(\S+)"),
                "docs": "https://nginx.org/download/",
            },
            "Python": {
                "name": "Python",
                "version": _get_version(["python3", "--version"], r"Python (\S+)"),
                "docs": "https://www.python.org/downloads/",
            },
            "PostgreSQL": {
                "name": "PostgreSQL",
                "version": _get_version(["psql", "--version"], r"psql \(PostgreSQL\) (\S+)"),
                "docs": "https://www.postgresql.org/download/",
            },
            "Redis": {
                "name": "Redis",
                "version": _get_version(["redis-server", "--version"], r"v=(\S+)"),
                "docs": "https://redis.io/download/",
            },
            "Postfix": {
                "name": "Postfix",
                "version": _get_version(["postfix", "-v"], r"postfix/(\S+)"),
                "docs": "http://www.postfix.org/download.html",
            },
            "Dovecot": {
                "name": "Dovecot",
                "version": _get_version(["dovecot", "--version"], r"(\S+)"),
                "docs": "https://www.dovecot.org/download/",
            },
            "Rspamd": {
                "name": "Rspamd",
                "version": _get_version(["rspamd", "--version"], r"rspamd (\S+)"),
                "docs": "https://rspamd.com/",
            },
        }
    }

    # Intentar obtener MariaDB si está instalada
    try:
        mariadb_ver = _get_version(["mariadb", "--version"], r"MariaDB ([\d.]+)")
        if mariadb_ver != "no disponible":
            versions["components"]["MariaDB"] = {
                "name": "MariaDB",
                "version": mariadb_ver,
                "docs": "https://mariadb.org/download/",
            }
    except Exception:
        pass

    # Intentar obtener Apache si está instalada
    try:
        apache_ver = _get_version(["apache2", "-v"], r"Apache/(\S+)")
        if apache_ver != "no disponible":
            versions["components"]["Apache"] = {
                "name": "Apache",
                "version": apache_ver,
                "docs": "https://httpd.apache.org/download.cgi",
            }
    except Exception:
        pass

    return versions

