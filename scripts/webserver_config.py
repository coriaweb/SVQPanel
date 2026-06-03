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

    # Fallback: detectar por presencia de ejecutables/configs
    if Path("/etc/nginx/nginx.conf").exists():
        if Path("/etc/apache2/apache2.conf").exists():
            return "apache+nginx"
        return "nginx"
    elif Path("/etc/apache2/apache2.conf").exists():
        return "apache"

    # Default a nginx si no se puede detectar
    logger.warning("No se pudo detectar webserver, asumiendo nginx")
    return "nginx"


def set_webserver(mode: Literal["nginx", "apache", "apache+nginx"]) -> bool:
    """
    Guarda la configuración de webserver seleccionada.
    Llamado desde install.sh después de elegir la opción.
    """
    try:
        WEBSERVER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(WEBSERVER_CONFIG_FILE, "w") as f:
            f.write(mode.lower())
        logger.info(f"Webserver configurado: {mode}")
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
