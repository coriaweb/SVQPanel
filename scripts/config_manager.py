"""
Config Manager — lectura y escritura de ficheros de configuración de servicios.
Solo permite editar ficheros de una whitelist predefinida por seguridad.
"""

import os
import subprocess
import shutil
import glob
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ──────────────────────── Definición de configs por servicio ─────────────────
#
# Cada entrada: {
#   "label":      Nombre legible del fichero
#   "path":       Ruta absoluta (puede ser glob para versiones dinámicas)
#   "test_cmd":   Comando para validar sintaxis (lista) o None
#   "reload_svc": Servicio a recargar tras guardar (o None)
#   "comment":    Descripción breve
# }

BASE_CONFIGS = {
    "nginx": [
        {
            "label":      "nginx.conf",
            "path":       "/etc/nginx/nginx.conf",
            "test_cmd":   ["nginx", "-t"],
            "reload_svc": "nginx",
            "comment":    "Configuración global de Nginx",
        },
    ],
    "apache2": [
        {
            "label":      "apache2.conf",
            "path":       "/etc/apache2/apache2.conf",
            "test_cmd":   ["apache2ctl", "configtest"],
            "reload_svc": "apache2",
            "comment":    "Configuración global de Apache2",
        },
        {
            "label":      "ports.conf",
            "path":       "/etc/apache2/ports.conf",
            "test_cmd":   ["apache2ctl", "configtest"],
            "reload_svc": "apache2",
            "comment":    "Puertos de escucha de Apache2",
        },
    ],
    "named": [
        {
            "label":      "named.conf.options",
            "path":       "/etc/bind/named.conf.options",
            "test_cmd":   ["named-checkconf"],
            "reload_svc": "named",
            "comment":    "Opciones globales de BIND9 (forwarders, recursion, etc.)",
        },
        {
            "label":      "named.conf.local",
            "path":       "/etc/bind/named.conf.local",
            "test_cmd":   ["named-checkconf"],
            "reload_svc": "named",
            "comment":    "Zonas locales de BIND9",
        },
    ],
    "ssh": [
        {
            "label":      "sshd_config",
            "path":       "/etc/ssh/sshd_config",
            "test_cmd":   ["sshd", "-t"],
            "reload_svc": "ssh",
            "comment":    "Configuración del servidor SSH",
        },
    ],
    "fail2ban": [
        {
            "label":      "jail.local",
            "path":       "/etc/fail2ban/jail.local",
            "test_cmd":   None,
            "reload_svc": "fail2ban",
            "comment":    "Configuración de jails de Fail2ban",
        },
    ],
    "postgresql": [
        {
            "label":      "postgresql.conf",
            "path":       None,   # Se resuelve dinámicamente
            "test_cmd":   None,
            "reload_svc": "postgresql",
            "comment":    "Configuración de PostgreSQL",
            "glob":       "/etc/postgresql/*/main/postgresql.conf",
        },
        {
            "label":      "pg_hba.conf",
            "path":       None,
            "test_cmd":   None,
            "reload_svc": "postgresql",
            "comment":    "Autenticación de clientes PostgreSQL",
            "glob":       "/etc/postgresql/*/main/pg_hba.conf",
        },
    ],
    "mariadb": [
        {
            "label":      "my.cnf",
            "path":       "/etc/mysql/my.cnf",
            "test_cmd":   None,
            "reload_svc": "mariadb",
            "comment":    "Configuración de MariaDB",
        },
    ],
    "postfix": [
        {
            "label":      "main.cf",
            "path":       "/etc/postfix/main.cf",
            "test_cmd":   ["postfix", "check"],
            "reload_svc": "postfix",
            "comment":    "Configuración principal de Postfix (SMTP)",
        },
        {
            "label":      "master.cf",
            "path":       "/etc/postfix/master.cf",
            "test_cmd":   ["postfix", "check"],
            "reload_svc": "postfix",
            "comment":    "Servicios/transports de Postfix (puertos, submission…)",
        },
    ],
    "dovecot": [
        {
            "label":      "dovecot.conf",
            "path":       "/etc/dovecot/dovecot.conf",
            "test_cmd":   ["doveconf", "-n"],
            "reload_svc": "dovecot",
            "comment":    "Configuración principal de Dovecot (IMAP/POP3)",
        },
    ],
    "rspamd": [
        {
            "label":      "ratelimit.conf",
            "path":       "/etc/rspamd/local.d/ratelimit.conf",
            "test_cmd":   None,
            "reload_svc": "rspamd",
            "comment":    "Límites de tasa de Rspamd (local.d)",
        },
        {
            "label":      "milter_headers.conf",
            "path":       "/etc/rspamd/local.d/milter_headers.conf",
            "test_cmd":   None,
            "reload_svc": "rspamd",
            "comment":    "Cabeceras que Rspamd añade al correo",
        },
        {
            "label":      "greylisting.conf",
            "path":       "/etc/rspamd/local.d/greylisting.conf",
            "test_cmd":   None,
            "reload_svc": "rspamd",
            "comment":    "Greylisting de Rspamd",
        },
        {
            "label":      "dkim_signing.conf",
            "path":       "/etc/rspamd/local.d/dkim_signing.conf",
            "test_cmd":   None,
            "reload_svc": "rspamd",
            "comment":    "Firma DKIM de Rspamd",
        },
    ],
    "redis": [
        {
            "label":      "redis.conf",
            "path":       "/etc/redis/redis.conf",
            "test_cmd":   None,
            "reload_svc": "redis-server",
            "comment":    "Configuración de Redis (cache)",
        },
    ],
    "nftables": [
        {
            "label":      "nftables.conf",
            "path":       "/etc/nftables.conf",
            "test_cmd":   ["nft", "-c", "-f", "/etc/nftables.conf"],
            "reload_svc": "nftables",
            "comment":    "Reglas del firewall nftables (gestionado por el panel)",
        },
    ],
    "crowdsec": [
        {
            "label":      "config.yaml",
            "path":       "/etc/crowdsec/config.yaml",
            "test_cmd":   None,
            "reload_svc": "crowdsec",
            "comment":    "Configuración principal de CrowdSec",
        },
        {
            "label":      "acquis.yaml",
            "path":       "/etc/crowdsec/acquis.yaml",
            "test_cmd":   None,
            "reload_svc": "crowdsec",
            "comment":    "Fuentes de logs que analiza CrowdSec",
        },
    ],
    "crowdsec-firewall-bouncer": [
        {
            "label":      "crowdsec-firewall-bouncer.yaml",
            "path":       "/etc/crowdsec/bouncers/crowdsec-firewall-bouncer.yaml",
            "test_cmd":   None,
            "reload_svc": "crowdsec-firewall-bouncer",
            "comment":    "Configuración del bouncer de firewall de CrowdSec",
        },
    ],
}

PHP_VERSIONS = ["5.6", "7.0", "7.1", "7.2", "7.3", "7.4",
                "8.0", "8.1", "8.2", "8.3", "8.4", "8.5"]


def _resolve_path(cfg: dict) -> Optional[str]:
    """Resuelve la ruta del fichero (soporta glob para versiones dinámicas)"""
    if cfg.get("path"):
        return cfg["path"]
    pattern = cfg.get("glob")
    if pattern:
        matches = sorted(glob.glob(pattern))
        return matches[-1] if matches else None
    return None


def get_service_configs(service_name: str) -> list:
    """
    Devuelve la lista de ficheros de configuración disponibles para un servicio.
    Para PHP-FPM, genera dinámicamente según la versión.
    """
    configs = []

    # PHP-FPM dinámico
    if service_name.startswith("php") and service_name.endswith("-fpm"):
        ver = service_name[3:-4]  # "php8.5-fpm" → "8.5"
        candidates = [
            {
                "label":      f"php.ini (FPM)",
                "path":       f"/etc/php/{ver}/fpm/php.ini",
                "test_cmd":   [f"php{ver}", "-t"],
                "reload_svc": service_name,
                "comment":    f"Configuración PHP {ver} para FPM",
            },
            {
                "label":      f"php-fpm.conf",
                "path":       f"/etc/php/{ver}/fpm/php-fpm.conf",
                "test_cmd":   [f"php-fpm{ver}", "--test"],
                "reload_svc": service_name,
                "comment":    f"Configuración del proceso PHP {ver} FPM",
            },
            {
                "label":      f"www.conf",
                "path":       f"/etc/php/{ver}/fpm/pool.d/www.conf",
                "test_cmd":   None,
                "reload_svc": service_name,
                "comment":    f"Pool FPM por defecto de PHP {ver}",
            },
        ]
        for c in candidates:
            if c["path"] and os.path.exists(c["path"]):
                configs.append({**c, "exists": True})
        return configs

    # Servicio conocido
    base = BASE_CONFIGS.get(service_name, [])
    for cfg in base:
        path = _resolve_path(cfg)
        if path and os.path.exists(path):
            configs.append({
                "label":      cfg["label"],
                "path":       path,
                "test_cmd":   cfg.get("test_cmd"),
                "reload_svc": cfg.get("reload_svc"),
                "comment":    cfg.get("comment", ""),
                "exists":     True,
            })

    return configs


def read_config(service_name: str, file_label: str) -> dict:
    """Lee el contenido de un fichero de configuración"""
    configs = get_service_configs(service_name)
    cfg = next((c for c in configs if c["label"] == file_label), None)
    if not cfg:
        raise ValueError(f"Fichero '{file_label}' no disponible para '{service_name}'")

    path = cfg["path"]
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {
            "service":  service_name,
            "label":    file_label,
            "path":     path,
            "content":  content,
            "comment":  cfg["comment"],
            "size":     os.path.getsize(path),
        }
    except PermissionError:
        raise PermissionError(f"Sin permiso para leer {path}")


def write_config(service_name: str, file_label: str, content: str) -> dict:
    """
    Escribe un fichero de configuración:
    1. Backup automático
    2. Escribe el nuevo contenido
    3. Test de sintaxis (si aplica)
    4. Si el test falla → restaura el backup
    5. Si todo ok → recarga el servicio
    """
    configs = get_service_configs(service_name)
    cfg = next((c for c in configs if c["label"] == file_label), None)
    if not cfg:
        raise ValueError(f"Fichero '{file_label}' no disponible para '{service_name}'")

    path = cfg["path"]
    backup_path = path + f".bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # 1. Backup
    try:
        shutil.copy2(path, backup_path)
        logger.info(f"Backup creado: {backup_path}")
    except Exception as e:
        logger.warning(f"No se pudo crear backup: {e}")
        backup_path = None

    # 2. Escribir
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except PermissionError:
        raise PermissionError(f"Sin permiso para escribir en {path}")

    # 3. Test de sintaxis
    test_output = ""
    test_ok = True
    test_cmd = cfg.get("test_cmd")
    if test_cmd:
        try:
            r = subprocess.run(test_cmd, capture_output=True, text=True, timeout=15)
            test_output = (r.stdout + r.stderr).strip()
            test_ok = r.returncode == 0
        except Exception as e:
            test_output = str(e)
            test_ok = False

    # 4. Restaurar si test falla
    if not test_ok and backup_path:
        try:
            shutil.copy2(backup_path, path)
            logger.warning(f"Config restaurada desde backup por error de sintaxis")
        except Exception as e:
            logger.error(f"Error restaurando backup: {e}")
        raise ValueError(
            f"Error de sintaxis — fichero restaurado al estado anterior.\n\n{test_output}"
        )

    # 5. Recargar servicio
    reload_svc = cfg.get("reload_svc")
    reload_output = ""
    if reload_svc and test_ok:
        try:
            r = subprocess.run(
                ["/usr/bin/systemctl", "reload-or-restart", reload_svc],
                capture_output=True, text=True, timeout=15
            )
            reload_output = (r.stdout + r.stderr).strip()
        except Exception as e:
            reload_output = str(e)

    return {
        "success":       True,
        "service":       service_name,
        "label":         file_label,
        "path":          path,
        "backup":        backup_path,
        "test_output":   test_output,
        "reload_output": reload_output,
    }
