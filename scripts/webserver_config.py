"""
Webserver configuration manager — soporta Nginx y Apache
"""

import logging
import os
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# Fichero que marca qué webserver se instaló
WEBSERVER_CONFIG_FILE = Path("/etc/svqpanel/webserver.conf")


def get_webserver() -> Literal["nginx", "apache", "apache+nginx"]:
    """
    Lee qué webserver está configurado en el servidor.
    Returns: "nginx", "apache", o "apache+nginx"
    """
    if WEBSERVER_CONFIG_FILE.exists():
        try:
            with open(WEBSERVER_CONFIG_FILE, "r") as f:
                content = f.read().strip().lower()
                if content in ("nginx", "apache", "apache+nginx"):
                    return content
        except Exception as e:
            logger.warning(f"Error leyendo {WEBSERVER_CONFIG_FILE}: {e}")

    # Fallback: detectar por presencia de ejecutables/configs.
    # Importante: que exista /etc/apache2 NO significa que se use Apache (puede
    # quedar instalado por dependencias). Solo asumimos apache+nginx si Apache
    # está realmente HABILITADO en systemd; si no, es una instalación nginx.
    nginx_present  = Path("/etc/nginx/nginx.conf").exists()
    apache_present = Path("/etc/apache2/apache2.conf").exists()

    def _apache_enabled() -> bool:
        try:
            import subprocess
            r = subprocess.run(["systemctl", "is-enabled", "apache2"],
                               capture_output=True, text=True, timeout=5)
            # 'enabled' / 'static' = en uso; 'disabled'/'masked'/no-instalado = no
            return r.stdout.strip() in ("enabled", "static")
        except Exception:
            return False

    if nginx_present:
        if apache_present and _apache_enabled():
            return "apache+nginx"
        return "nginx"
    elif apache_present:
        return "apache"

    # Default a nginx si no se puede detectar
    logger.warning("No se pudo detectar webserver, asumiendo nginx")
    return "nginx"


def ensure_crowdsec_apache_collection() -> bool:
    """
    Asegura la colección crowdsecurity/apache2 en CrowdSec. Las reglas de nginx
    no entienden el log de Apache, así que al pasar a un modo con Apache hay que
    instalarla o los dominios servidos por Apache quedan sin protección.
    Idempotente y no bloqueante: si cscli no está, no hace nada.
    """
    import shutil
    import subprocess
    cscli = shutil.which("cscli") or "/usr/bin/cscli"
    if not (shutil.which("cscli") or os.path.exists("/usr/bin/cscli")):
        return False
    try:
        # ¿Ya instalada?
        chk = subprocess.run([cscli, "collections", "list", "-o", "json"],
                             capture_output=True, text=True, timeout=15)
        if chk.returncode == 0 and "crowdsecurity/apache2" in (chk.stdout or ""):
            return True
        inst = subprocess.run([cscli, "collections", "install", "crowdsecurity/apache2"],
                              capture_output=True, text=True, timeout=60)
        if inst.returncode == 0:
            # Recargar CrowdSec para que cargue la nueva colección
            subprocess.run(["systemctl", "reload", "crowdsec"],
                           capture_output=True, text=True, timeout=30)
            logger.info("Colección CrowdSec crowdsecurity/apache2 instalada")
            return True
        logger.warning(f"No se pudo instalar crowdsecurity/apache2: {inst.stderr.strip()}")
        return False
    except Exception as e:
        logger.warning(f"ensure_crowdsec_apache_collection: {e}")
        return False


def set_webserver(mode: Literal["nginx", "apache", "apache+nginx"]) -> bool:
    """
    Guarda la configuración de webserver seleccionada.
    Llamado desde install.sh después de elegir la opción.
    Si el modo usa Apache, asegura la colección CrowdSec correspondiente.
    """
    try:
        WEBSERVER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(WEBSERVER_CONFIG_FILE, "w") as f:
            f.write(mode.lower())
        logger.info(f"Webserver configurado: {mode}")
        # Al activar Apache, asegurar su colección de CrowdSec (no bloqueante)
        if mode.lower() in ("apache", "apache+nginx"):
            try:
                ensure_crowdsec_apache_collection()
            except Exception:
                pass
        return True
    except Exception as e:
        logger.error(f"Error escribiendo {WEBSERVER_CONFIG_FILE}: {e}")
        return False


def supports_nginx() -> bool:
    """True si la instalación soporta nginx (nginx o apache+nginx)."""
    ws = get_webserver()
    return ws in ("nginx", "apache+nginx")


def supports_apache() -> bool:
    """True si la instalación soporta Apache (apache o apache+nginx)."""
    ws = get_webserver()
    return ws in ("apache", "apache+nginx")


def get_apache_vhost_path(domain: str) -> str:
    """Ruta del vhost Apache para un dominio."""
    return f"/etc/apache2/sites-available/{domain}.conf"


def get_apache_vhosts_dir() -> str:
    """Directorio de vhosts disponibles en Apache."""
    return "/etc/apache2/sites-available"


def get_apache_vhosts_enabled_dir() -> str:
    """Directorio de vhosts habilitados en Apache."""
    return "/etc/apache2/sites-enabled"
