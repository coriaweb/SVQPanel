"""
Services Manager — detección y control de servicios del sistema vía systemd.
Detecta automáticamente los servicios instalados y obtiene estado, uptime, CPU y memoria.
"""

import subprocess
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Servicios conocidos: (nombre_systemd, descripción_legible)
KNOWN_SERVICES = [
    ("nginx",          "Proxy inverso / Servidor web"),
    ("apache2",        "Servidor web Apache"),
    ("named",          "Servidor DNS (BIND9)"),
    ("postgresql",     "Base de datos PostgreSQL"),
    ("mariadb",        "Base de datos MariaDB"),
    ("mysql",          "Base de datos MySQL"),
    ("redis",          "Cache Redis"),
    ("memcached",      "Cache Memcached"),
    ("fail2ban",       "Protección fuerza bruta"),
    ("ufw",            "Firewall UFW"),
    ("iptables",       "Firewall iptables"),
    ("ssh",            "Servidor SSH"),
    ("vsftpd",         "Servidor FTP (vsftpd)"),
    ("proftpd",        "Servidor FTP (proftpd)"),
    ("clamav-daemon",  "Antivirus ClamAV"),
    ("spamassassin",   "Filtro spam SpamAssassin"),
    ("spamd",          "Filtro spam spamd"),
    ("dovecot",        "Servidor IMAP/POP3"),
    ("exim4",          "Servidor de correo Exim"),
    ("postfix",        "Servidor de correo Postfix"),
    ("cron",           "Programador de tareas"),
]

PHP_VERSIONS = ["5.6", "7.0", "7.1", "7.2", "7.3", "7.4",
                "8.0", "8.1", "8.2", "8.3", "8.4", "8.5"]


def _run(cmd: list) -> tuple[int, str, str]:
    """Ejecuta un comando y devuelve (returncode, stdout, stderr)"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def _parse_systemctl_props(output: str) -> dict:
    props = {}
    for line in output.strip().split("\n"):
        if "=" in line:
            k, v = line.split("=", 1)
            props[k.strip()] = v.strip()
    return props


def _format_uptime(ts_str: str) -> str:
    """Convierte el timestamp de systemd en tiempo legible"""
    if not ts_str or ts_str in ("n/a", ""):
        return "—"
    try:
        # "Mon 2026-05-25 12:00:00 UTC"
        dt = datetime.strptime(ts_str, "%a %Y-%m-%d %H:%M:%S %Z")
        dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        days = delta.days
        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        if days > 0:
            return f"{days} días"
        elif hours > 0:
            return f"{hours} horas"
        else:
            return f"{minutes} min"
    except Exception:
        return "—"


def get_service_info(service_name: str, description_override: str = None) -> Optional[dict]:
    """
    Obtiene info de un servicio systemd.
    Devuelve None si el servicio no está instalado.
    """
    code, out, _ = _run([
        "systemctl", "show", service_name,
        "--property=LoadState,ActiveState,MainPID,ActiveEnterTimestamp,Description,MemoryCurrent"
    ])

    if code != 0:
        return None

    props = _parse_systemctl_props(out)

    load_state = props.get("LoadState", "not-found")
    if load_state == "not-found":
        return None

    active_state = props.get("ActiveState", "inactive")
    is_running = active_state == "active"

    # Descripción
    description = description_override or props.get("Description", service_name)

    # Uptime
    uptime_str = _format_uptime(props.get("ActiveEnterTimestamp", "")) if is_running else "—"

    # Memoria (cgroup)
    memory_mb = 0
    mem_raw = props.get("MemoryCurrent", "")
    if mem_raw and mem_raw not in ("[not set]", "infinity", "") and mem_raw.isdigit():
        memory_mb = round(int(mem_raw) / (1024 * 1024))

    # CPU % vía ps del PID principal
    cpu_pct = 0.0
    main_pid = props.get("MainPID", "0")
    if main_pid and main_pid != "0":
        c, ps_out, _ = _run(["ps", "-p", main_pid, "-o", "%cpu", "--no-headers"])
        if c == 0 and ps_out:
            try:
                cpu_pct = float(ps_out.strip())
            except ValueError:
                pass

    return {
        "name":        service_name,
        "description": description,
        "is_running":  is_running,
        "state":       active_state,
        "uptime":      uptime_str,
        "cpu":         cpu_pct,
        "memory_mb":   memory_mb,
    }


def get_all_services() -> list:
    """
    Devuelve todos los servicios detectados en el sistema.
    Solo incluye los que están instalados (LoadState != not-found).
    """
    services = []
    seen = set()

    # Servicios conocidos
    for svc_name, description in KNOWN_SERVICES:
        if svc_name in seen:
            continue
        info = get_service_info(svc_name, description)
        if info:
            services.append(info)
            seen.add(svc_name)

    # PHP-FPM dinámico
    for ver in PHP_VERSIONS:
        svc_name = f"php{ver}-fpm"
        if svc_name in seen:
            continue
        info = get_service_info(svc_name, f"Intérprete PHP {ver}")
        if info:
            services.append(info)
            seen.add(svc_name)

    # Ordenar: primero los activos, luego por nombre
    services.sort(key=lambda s: (0 if s["is_running"] else 1, s["name"]))
    return services


def control_service(service_name: str, action: str) -> dict:
    """
    Controla un servicio: start | stop | restart | reload
    Devuelve {"success": True/False, "output": "..."}
    """
    if action not in ("start", "stop", "restart", "reload"):
        raise ValueError(f"Acción inválida: {action}")

    code, out, err = _run(["systemctl", action, service_name])
    success = code == 0
    return {
        "success": success,
        "service": service_name,
        "action":  action,
        "output":  out or err or ("OK" if success else "Error desconocido"),
    }


def get_system_stats() -> dict:
    """Estadísticas generales del sistema"""
    stats = {
        "load_1":  0.0,
        "load_5":  0.0,
        "load_15": 0.0,
        "uptime_days": 0,
        "uptime_str":  "—",
        "cpu_count": 1,
        "os_name": "",
    }

    # Load average
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
            stats["load_1"]  = float(parts[0])
            stats["load_5"]  = float(parts[1])
            stats["load_15"] = float(parts[2])
    except Exception:
        pass

    # Uptime
    try:
        with open("/proc/uptime") as f:
            seconds = float(f.read().split()[0])
            days = int(seconds // 86400)
            hours = int((seconds % 86400) // 3600)
            stats["uptime_days"] = days
            stats["uptime_str"]  = f"{days} días, {hours} horas" if days > 0 else f"{hours} horas"
    except Exception:
        pass

    # CPU cores
    try:
        with open("/proc/cpuinfo") as f:
            stats["cpu_count"] = f.read().count("processor\t:")
    except Exception:
        pass

    # OS
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    stats["os_name"] = line.split("=", 1)[1].strip().strip('"')
                    break
    except Exception:
        pass

    return stats
