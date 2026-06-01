"""
Autoinstalador de aplicaciones web (1 clic) para dominios de SVQPanel.

Soporta: WordPress, Laravel, Nextcloud, PrestaShop.

Cada instalador:
  1. Crea una BD MariaDB + usuario con credenciales aleatorias.
  2. Descarga la aplicación en el public_html del dominio.
  3. Configura la conexión a BD (wp-config.php, .env, config/...).
  4. Deja los archivos con owner del usuario del dominio.
  5. Devuelve las credenciales/URL para que el panel las muestre.

Herramientas del sistema usadas (instaladas por install.sh / ensure_tools):
  - wp-cli (WordPress)    - composer (Laravel)
  - curl, tar, unzip      - mariadb/mysql

NO usa shell=True con input de usuario: los comandos van como listas y los
nombres/credenciales se validan o se generan aleatoriamente.
"""

import json
import logging
import os
import re
import secrets
import shutil
import string
import subprocess
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_SYS_ENV = {
    **os.environ,
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
}

# Apps soportadas con su versión PHP recomendada (informativa).
SUPPORTED_APPS = {
    "wordpress":  {"name": "WordPress",  "php_min": "7.4", "needs": ["wp"]},
    "laravel":    {"name": "Laravel",    "php_min": "8.2", "needs": ["composer"]},
    "nextcloud":  {"name": "Nextcloud",  "php_min": "8.1", "needs": ["curl"]},
    "prestashop": {"name": "PrestaShop", "php_min": "8.1", "needs": ["curl"]},
}

WPCLI_PATH = "/usr/local/bin/wp"
COMPOSER_PATH = "/usr/local/bin/composer"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _run(cmd, cwd=None, as_user=None, timeout=600, input_text=None):
    """Ejecuta un comando (lista, sin shell). Devuelve (rc, stdout, stderr)."""
    if as_user:
        cmd = ["sudo", "-u", as_user, "-H"] + cmd
    try:
        r = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True,
            timeout=timeout, env=_SYS_ENV, input=input_text,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout tras {timeout}s"
    except Exception as e:
        return -1, "", str(e)


def _gen_password(n: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def _gen_suffix(n: int = 6) -> str:
    return "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(n))


def _safe_ident(s: str, maxlen: int = 16) -> str:
    """Identificador seguro para nombre de BD/usuario (alfanumérico + _)."""
    s = re.sub(r"[^a-z0-9_]", "", s.lower())
    return s[:maxlen] or "app"


def ensure_wp_cli() -> bool:
    """Instala wp-cli en /usr/local/bin/wp si no está. Idempotente."""
    if shutil.which("wp") or os.path.exists(WPCLI_PATH):
        return True
    rc, _, err = _run([
        "curl", "-fsSL", "-o", WPCLI_PATH,
        "https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar",
    ])
    if rc != 0:
        logger.error(f"No se pudo descargar wp-cli: {err}")
        return False
    os.chmod(WPCLI_PATH, 0o755)
    return True


def ensure_composer() -> bool:
    """Instala composer en /usr/local/bin/composer si no está. Idempotente."""
    if shutil.which("composer") or os.path.exists(COMPOSER_PATH):
        return True
    rc, _, err = _run(["curl", "-fsSL", "-o", "/tmp/composer-setup.php",
                       "https://getcomposer.org/installer"])
    if rc != 0:
        logger.error(f"No se pudo descargar composer installer: {err}")
        return False
    rc, _, err = _run(["php", "/tmp/composer-setup.php",
                       "--install-dir=/usr/local/bin", "--filename=composer"])
    try: os.remove("/tmp/composer-setup.php")
    except OSError: pass
    return rc == 0


def _empty_or_safe(docroot: str) -> bool:
    """El docroot debe existir y estar vacío (o solo con index por defecto)."""
    if not os.path.isdir(docroot):
        return False
    entries = [e for e in os.listdir(docroot) if e not in (".", "..")]
    # Permitimos un index.html/php por defecto de la creación del dominio
    trivial = {"index.html", "index.php", "index.nginx-debian.html", ".well-known"}
    return all(e in trivial for e in entries)


def _chown_tree(path: str, user: str):
    _run(["chown", "-R", f"{user}:{user}", path])


# ─────────────────────────────────────────────────────────────────────────────
# Orquestador
# ─────────────────────────────────────────────────────────────────────────────
class AppInstaller:
    """
    Instala una app en el docroot de un dominio. Recibe un callback run_sql
    para crear la BD (lo provee la capa API reutilizando _run_mariadb).
    """

    def __init__(self, run_sql):
        # run_sql(sql:str) -> ejecuta SQL en MariaDB con el admin del panel
        self.run_sql = run_sql

    # ── BD ────────────────────────────────────────────────────────────────
    def _create_db(self, owner: str, app: str) -> Dict[str, str]:
        suffix = _gen_suffix()
        db_name = f"{_safe_ident(owner, 10)}_{_safe_ident(app, 4)}{suffix}"
        db_user = f"{_safe_ident(owner, 10)}_{suffix}"
        db_pass = _gen_password()
        safe_name = db_name.replace("`", "``")
        safe_user = db_user.replace("'", "''")
        safe_pass = db_pass.replace("'", "''")
        self.run_sql(f"CREATE DATABASE `{safe_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
        self.run_sql(f"CREATE USER '{safe_user}'@'localhost' IDENTIFIED BY '{safe_pass}';")
        # Privilegios específicos (no ALL: el admin del panel no tiene GRANT ALL
        # sobre BDs nuevas). Mismo set que usa databases.py al crear BDs.
        self.run_sql(
            f"GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, INDEX, ALTER, "
            f"CREATE TEMPORARY TABLES, LOCK TABLES, EXECUTE, "
            f"CREATE VIEW, SHOW VIEW, CREATE ROUTINE, ALTER ROUTINE, "
            f"EVENT, TRIGGER ON `{safe_name}`.* TO '{safe_user}'@'localhost';"
        )
        self.run_sql("FLUSH PRIVILEGES;")
        return {"db_name": db_name, "db_user": db_user, "db_pass": db_pass}

    # ── WordPress ───────────────────────────────────────────────────────────
    def install_wordpress(self, domain: str, owner: str, docroot: str,
                          admin_user: str, admin_pass: str, admin_email: str) -> Dict:
        if not ensure_wp_cli():
            raise RuntimeError("No se pudo instalar wp-cli en el servidor")
        if not _empty_or_safe(docroot):
            raise RuntimeError("El directorio del dominio no está vacío; instala en un dominio limpio")

        db = self._create_db(owner, "wp")

        # Descargar el core
        rc, _, err = _run([WPCLI_PATH, "core", "download", "--path=" + docroot],
                          as_user=owner)
        if rc != 0:
            raise RuntimeError(f"wp core download falló: {err}")

        # wp-config.php
        rc, _, err = _run([
            WPCLI_PATH, "config", "create",
            "--path=" + docroot,
            "--dbname=" + db["db_name"],
            "--dbuser=" + db["db_user"],
            "--dbpass=" + db["db_pass"],
            "--dbhost=localhost",
            "--skip-check",
        ], as_user=owner)
        if rc != 0:
            raise RuntimeError(f"wp config create falló: {err}")

        # Instalar el sitio
        url = f"https://{domain}"
        rc, _, err = _run([
            WPCLI_PATH, "core", "install",
            "--path=" + docroot,
            "--url=" + url,
            "--title=" + domain,
            "--admin_user=" + admin_user,
            "--admin_password=" + admin_pass,
            "--admin_email=" + admin_email,
            "--skip-email",
        ], as_user=owner)
        if rc != 0:
            raise RuntimeError(f"wp core install falló: {err}")

        _chown_tree(docroot, owner)
        return {
            "app": "wordpress",
            "url": url,
            "admin_url": f"{url}/wp-admin",
            "admin_user": admin_user,
            "admin_password": admin_pass,
            "db": db,
        }
