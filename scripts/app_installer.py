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


class RequirementsError(RuntimeError):
    """Requisitos previos no cumplidos (PHP, extensiones, dir no vacío…).

    Es un error de usuario: el endpoint lo traduce a HTTP 422 con el mensaje
    tal cual, sin envolverlo como fallo interno.
    """

_SYS_ENV = {
    **os.environ,
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
}

# Apps soportadas con su versión PHP recomendada (informativa).
SUPPORTED_APPS = {
    "wordpress":  {"name": "WordPress",  "php_min": "7.4", "needs": ["wp"]},
    "laravel":    {"name": "Laravel",    "php_min": "8.2", "needs": ["composer"]},
    "nextcloud":  {"name": "Nextcloud",  "php_min": "8.1", "needs": ["curl", "unzip"]},
    "prestashop": {"name": "PrestaShop", "php_min": "8.1", "needs": ["curl"]},
}

WPCLI_PATH = "/usr/local/bin/wp"
COMPOSER_PATH = "/usr/local/bin/composer"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _run(cmd, cwd=None, as_user=None, timeout=600, input_text=None, env=None):
    """Ejecuta un comando (lista, sin shell). Devuelve (rc, stdout, stderr).

    env: por defecto _SYS_ENV. Se pasa a `sudo` con env_keep vía prefijo
    VAR=valor para que las variables sobrevivan al cambio de usuario (sudo
    limpia el entorno; -H solo ajusta HOME)."""
    run_env = env or _SYS_ENV
    if as_user:
        # sudo sanea el entorno al cambiar de usuario; para forzar variables
        # extra (COMPOSER_HOME, COMPOSER_NO_INTERACTION…) las inyectamos con
        # `env VAR=val` DENTRO del contexto del usuario. Solo las que difieren
        # de os.environ (las heredadas ya viajan por env= del subprocess).
        extra = {k: v for k, v in run_env.items()
                 if os.environ.get(k) != v}
        prefix = ["env"] + [f"{k}={v}" for k, v in extra.items()] if extra else []
        cmd = ["sudo", "-u", as_user, "-H"] + prefix + cmd
    try:
        r = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True,
            timeout=timeout, env=run_env, input=input_text,
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


# Ficheros "index" placeholder que crea el panel al crear el dominio. Se
# permiten en un docroot "limpio" pero DEBEN eliminarse antes de instalar una
# app, o Apache/nginx sirven el index.html placeholder en vez de la app (p. ej.
# WordPress, cuyo front es index.php → Apache prioriza index.html y muestra la
# página "Gestionado con SVQPanel" en lugar del sitio).
_PLACEHOLDER_INDEX = ("index.html", "index.nginx-debian.html")


def _empty_or_safe(docroot: str) -> bool:
    """El docroot debe existir y estar vacío (o solo con index por defecto)."""
    if not os.path.isdir(docroot):
        return False
    entries = [e for e in os.listdir(docroot) if e not in (".", "..")]
    # Permitimos un index.html/php por defecto de la creación del dominio
    trivial = {"index.html", "index.php", "index.nginx-debian.html", ".well-known"}
    return all(e in trivial for e in entries)


def _clean_placeholders(docroot: str):
    """Elimina los index.html placeholder del panel antes de instalar una app.

    El index.php sí se conserva: WordPress/PrestaShop traen el suyo y wp-cli
    sobrescribe el del panel; eliminarlo aquí no aporta y podría borrar uno ya
    legítimo en flujos no-WP.
    """
    if not os.path.isdir(docroot):
        return
    for name in _PLACEHOLDER_INDEX:
        p = os.path.join(docroot, name)
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass


def _chown_tree(path: str, user: str):
    _run(["chown", "-R", f"{user}:{user}", path])


# Idiomas de WordPress ofrecidos en el instalador (código locale → etiqueta).
# Español (es_ES) es el primero/por defecto. Lista corta y curada; el usuario
# puede ampliarla, pero estos cubren la mayoría de casos en es/EU.
WP_LOCALES = {
    "es_ES": "Español (España)",
    "es_MX": "Español (México)",
    "en_US": "English (US)",
    "ca":    "Català",
    "gl_ES": "Galego",
    "eu":    "Euskara",
    "pt_PT": "Português (Portugal)",
    "pt_BR": "Português (Brasil)",
    "fr_FR": "Français",
    "de_DE": "Deutsch",
    "it_IT": "Italiano",
}
WP_DEFAULT_LOCALE = "es_ES"


def _normalize_wp_locale(locale: Optional[str]) -> str:
    """Valida el locale recibido; cae a es_ES si es vacío o no soportado."""
    if not locale:
        return WP_DEFAULT_LOCALE
    locale = str(locale).strip()
    return locale if locale in WP_LOCALES else WP_DEFAULT_LOCALE


# Nextcloud: rango de PHP soportado y extensiones requeridas (series 30/31).
NEXTCLOUD_PHP_MIN = (8, 1)
NEXTCLOUD_PHP_MAX = (8, 4)
NEXTCLOUD_PHP_EXTS = ["gd", "mbstring", "intl", "bcmath", "gmp", "curl",
                      "zip", "xml", "pdo_mysql"]

# PrestaShop 8.x: PHP 7.2–8.1 (8.1.x soporta hasta PHP 8.1).
PRESTASHOP_PHP_MIN = (7, 2)
PRESTASHOP_PHP_MAX = (8, 1)
PRESTASHOP_PHP_EXTS = ["gd", "mbstring", "intl", "curl", "zip", "xml",
                       "pdo_mysql"]


def _php_version_tuple(php_bin: str):
    """Devuelve (major, minor) del binario PHP, o None si no se puede determinar."""
    rc, out, _ = _run([php_bin, "-r", "echo PHP_MAJOR_VERSION.'.'.PHP_MINOR_VERSION;"])
    if rc != 0 or "." not in out:
        return None
    try:
        a, b = out.strip().split(".")[:2]
        return (int(a), int(b))
    except ValueError:
        return None


def _check_php_requirements(php_bin: str, app_name: str, vmin, vmax, exts):
    """
    Valida versión y extensiones PHP para una app concreta.
    Devuelve (ok: bool, motivo: str legible para el usuario).
    """
    ver = _php_version_tuple(php_bin)
    if ver is None:
        return False, f"No se pudo determinar la versión de PHP ({php_bin})."
    if ver < vmin or ver > vmax:
        smin = ".".join(map(str, vmin))
        smax = ".".join(map(str, vmax))
        cur = ".".join(map(str, ver))
        return False, (
            f"{app_name} requiere PHP {smin}–{smax} y el dominio usa PHP {cur}. "
            f"Cambia la versión PHP del dominio a una soportada (p. ej. {smax}) "
            f"e inténtalo de nuevo."
        )
    rc, out, _ = _run([php_bin, "-m"])
    loaded = {m.strip().lower() for m in out.splitlines()} if rc == 0 else set()
    missing = [e for e in exts if e.lower() not in loaded]
    if missing:
        cur = ".".join(map(str, ver))
        pkgs = ", ".join(f"php{cur}-{e.replace('pdo_mysql', 'mysql')}" for e in missing)
        return False, (
            f"A PHP {cur} le faltan extensiones requeridas por {app_name}: "
            f"{', '.join(missing)}. Instálalas (p. ej. apt-get install {pkgs}) "
            f"y reinténtalo."
        )
    return True, ""


def _check_nextcloud_php(php_bin: str, php_version=None):
    return _check_php_requirements(php_bin, "Nextcloud",
                                   NEXTCLOUD_PHP_MIN, NEXTCLOUD_PHP_MAX,
                                   NEXTCLOUD_PHP_EXTS)


def _check_prestashop_php(php_bin: str, php_version=None):
    return _check_php_requirements(php_bin, "PrestaShop",
                                   PRESTASHOP_PHP_MIN, PRESTASHOP_PHP_MAX,
                                   PRESTASHOP_PHP_EXTS)


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
                          admin_user: str, admin_pass: str, admin_email: str,
                          locale: str = "es_ES") -> Dict:
        if not ensure_wp_cli():
            raise RuntimeError("No se pudo instalar wp-cli en el servidor")
        if not _empty_or_safe(docroot):
            raise RequirementsError("El directorio del dominio no está vacío; instala en un dominio limpio")
        _clean_placeholders(docroot)

        locale = _normalize_wp_locale(locale)

        db = self._create_db(owner, "wp")

        # Descargar el core en el idioma elegido (--locale baja los paquetes de
        # traducción del core ya en la descarga; por defecto es_ES).
        rc, _, err = _run([WPCLI_PATH, "core", "download",
                           "--path=" + docroot, "--locale=" + locale],
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

        # Activar el idioma del sitio (admin + frontend). Para en_US no hace
        # falta (es el idioma base de WP y no hay paquete que instalar).
        if locale != "en_US":
            # Instala el paquete de traducción del core y lo deja como idioma
            # activo del sitio (option WPLANG). Best-effort: si falla, WP queda
            # usable en inglés y no abortamos la instalación.
            _run([WPCLI_PATH, "language", "core", "install",
                  "--path=" + docroot, "--activate", locale], as_user=owner)
            _run([WPCLI_PATH, "site", "switch-language",
                  "--path=" + docroot, locale], as_user=owner)

        _chown_tree(docroot, owner)
        return {
            "app": "wordpress",
            "url": url,
            "admin_url": f"{url}/wp-admin",
            "admin_user": admin_user,
            "admin_password": admin_pass,
            "locale": locale,
            "db": db,
        }

    # ── Laravel ──────────────────────────────────────────────────────────────
    def install_laravel(self, domain: str, owner: str, docroot: str) -> Dict:
        """
        Instala Laravel con composer. Devuelve docroot_public: la web del
        dominio debe apuntar a {docroot}/public (lo ajusta el endpoint).
        """
        if not ensure_composer():
            raise RuntimeError("No se pudo instalar composer en el servidor")
        if not _empty_or_safe(docroot):
            raise RequirementsError("El directorio del dominio no está vacío; instala en un dominio limpio")
        _clean_placeholders(docroot)

        db = self._create_db(owner, "lar")

        # composer create-project en una carpeta temporal del usuario y mover.
        # (create-project exige carpeta vacía/inexistente; el docroot puede
        # tener un index trivial, así que usamos tmp y luego rsync.)
        tmp = f"{os.path.dirname(docroot)}/.laravel_tmp"
        _run(["rm", "-rf", tmp])
        env = dict(_SYS_ENV, COMPOSER_NO_INTERACTION="1", COMPOSER_ALLOW_SUPERUSER="0")
        rc, _, err = _run([
            COMPOSER_PATH, "create-project", "laravel/laravel", tmp,
            "--no-interaction", "--prefer-dist",
        ], as_user=owner, timeout=900)
        if rc != 0:
            _run(["rm", "-rf", tmp])
            raise RuntimeError(f"composer create-project falló: {err[:400]}")

        # Limpiar docroot (index trivial) y mover el proyecto dentro
        _run(["find", docroot, "-mindepth", "1", "-delete"])
        # mover contenido (incluye ocultos) de tmp → docroot
        _run(["bash", "-c", f"shopt -s dotglob && mv {tmp}/* {docroot}/ && rmdir {tmp}"], as_user=owner)

        # Configurar .env: BD + APP_URL
        url = f"https://{domain}"
        envp = os.path.join(docroot, ".env")
        try:
            with open(envp) as f:
                content = f.read()
            repl = {
                r"^APP_URL=.*":       f"APP_URL={url}",
                r"^DB_CONNECTION=.*": "DB_CONNECTION=mysql",
                r"^DB_HOST=.*":       "DB_HOST=127.0.0.1",
                r"^DB_PORT=.*":       "DB_PORT=3306",
                r"^DB_DATABASE=.*":   f"DB_DATABASE={db['db_name']}",
                r"^DB_USERNAME=.*":   f"DB_USERNAME={db['db_user']}",
                r"^DB_PASSWORD=.*":   f"DB_PASSWORD={db['db_pass']}",
            }
            for pat, val in repl.items():
                if re.search(pat, content, flags=re.M):
                    content = re.sub(pat, val, content, flags=re.M)
                else:
                    content += f"\n{val}"
            with open(envp, "w") as f:
                f.write(content)
        except OSError as e:
            raise RuntimeError(f"No se pudo configurar .env de Laravel: {e}")

        # App key + migraciones (como el usuario)
        _run([COMPOSER_PATH, "install", "--no-interaction", "--prefer-dist"],
             cwd=docroot, as_user=owner, timeout=900)
        _run(["php", "artisan", "key:generate", "--force"], cwd=docroot, as_user=owner)
        _run(["php", "artisan", "migrate", "--force"], cwd=docroot, as_user=owner)

        _chown_tree(docroot, owner)

        # PHP-FPM corre como www-data: storage/ y bootstrap/cache deben ser
        # escribibles por www-data. Damos el grupo www-data + permisos de grupo
        # (g+w) + setgid para que los archivos nuevos hereden el grupo.
        for sub in ("storage", "bootstrap/cache"):
            p = os.path.join(docroot, sub)
            if os.path.isdir(p):
                _run(["chgrp", "-R", "www-data", p])
                _run(["chmod", "-R", "g+rwX", p])
                _run(["find", p, "-type", "d", "-exec", "chmod", "g+s", "{}", "+"])
        return {
            "app": "laravel",
            "url": url,
            # La web debe servirse desde /public (el endpoint ajusta el docroot)
            "docroot_public": os.path.join(docroot, "public"),
            "db": db,
        }

    # ── Nextcloud ──────────────────────────────────────────────────────────────
    def install_nextcloud(self, domain: str, owner: str, docroot: str,
                          admin_user: str, admin_pass: str,
                          php_version: Optional[str] = None) -> Dict:
        """
        Descarga la última versión estable de Nextcloud y la instala de forma
        desatendida con `occ maintenance:install` (sin pasar por el wizard web).

        php_version: versión PHP del dominio (p. ej. "8.3"). occ se ejecuta con
        ese binario (php8.3) porque Nextcloud es sensible a la versión PHP y no
        soporta las más nuevas (p. ej. 8.5) hasta tener release compatible.
        """
        if not _empty_or_safe(docroot):
            raise RequirementsError("El directorio del dominio no está vacío; instala en un dominio limpio")
        _clean_placeholders(docroot)

        # Binario PHP a usar para occ: php{ver} si existe, si no el genérico.
        php_bin = "php"
        if php_version:
            cand = f"php{php_version}"
            if shutil.which(cand) or os.path.exists(f"/usr/bin/{cand}"):
                php_bin = cand

        # ── Precheck de requisitos PHP ────────────────────────────────────────
        # Nextcloud es estricto con la versión y extensiones. Validamos ANTES de
        # tocar nada para fallar con un mensaje claro (no dejar un sitio roto).
        ok, why = _check_nextcloud_php(php_bin, php_version)
        if not ok:
            raise RequirementsError(why)

        db = self._create_db(owner, "nc")

        parent = os.path.dirname(docroot)
        zip_path = os.path.join(parent, ".nextcloud_latest.zip")
        tmp = os.path.join(parent, ".nextcloud_tmp")
        _run(["rm", "-rf", tmp, zip_path])

        # Descargar el zip oficial (latest = última estable)
        rc, _, err = _run([
            "curl", "-fsSL", "-o", zip_path,
            "https://download.nextcloud.com/server/releases/latest.zip",
        ], timeout=900)
        if rc != 0:
            _run(["rm", "-rf", tmp, zip_path])
            raise RuntimeError(f"Descarga de Nextcloud falló: {err}")

        # Extraer (crea una carpeta 'nextcloud/' dentro de tmp)
        _run(["mkdir", "-p", tmp])
        rc, _, err = _run(["unzip", "-q", zip_path, "-d", tmp])
        if rc != 0:
            _run(["rm", "-rf", tmp, zip_path])
            raise RuntimeError(f"Descompresión de Nextcloud falló: {err}")

        src = os.path.join(tmp, "nextcloud")
        if not os.path.isdir(src):
            _run(["rm", "-rf", tmp, zip_path])
            raise RuntimeError("El zip de Nextcloud no contiene la carpeta esperada")

        # Limpiar docroot (index trivial) y mover el contenido de nextcloud/ → docroot
        _run(["find", docroot, "-mindepth", "1", "-delete"])
        rc, _, err = _run(["bash", "-c",
                           f"shopt -s dotglob && mv {src}/* {docroot}/"], as_user=owner)
        if rc != 0:
            # fallback como root si el mv como usuario falló por permisos del tmp
            _run(["bash", "-c", f"shopt -s dotglob && mv {src}/* {docroot}/"])
        _run(["rm", "-rf", tmp, zip_path])
        _chown_tree(docroot, owner)

        # data/ debe quedar fuera del docroot servido por nginx; Nextcloud lo crea
        # dentro por defecto pero lo protegemos por .htaccess/nginx. Lo dejamos en
        # el lugar por defecto ({docroot}/data) y la plantilla nginx lo bloquea.

        # Instalación desatendida con occ (como el usuario del dominio).
        url = f"https://{domain}"
        occ = os.path.join(docroot, "occ")
        rc, out, err = _run([
            php_bin, occ, "maintenance:install",
            "--database", "mysql",
            "--database-name", db["db_name"],
            "--database-user", db["db_user"],
            "--database-pass", db["db_pass"],
            "--database-host", "localhost",
            "--admin-user", admin_user,
            "--admin-pass", admin_pass,
        ], cwd=docroot, as_user=owner, timeout=900)
        if rc != 0:
            raise RuntimeError(f"occ maintenance:install falló: {(err or out)[:400]}")

        # Registrar el dominio como trusted_domain (occ usa índice 0 = localhost)
        _run([php_bin, occ, "config:system:set", "trusted_domains", "1",
              "--value", domain], cwd=docroot, as_user=owner)
        # overwrite.cli.url y protocolo https detrás del proxy/nginx
        _run([php_bin, occ, "config:system:set", "overwrite.cli.url",
              "--value", url], cwd=docroot, as_user=owner)
        _run([php_bin, occ, "config:system:set", "overwriteprotocol",
              "--value", "https"], cwd=docroot, as_user=owner)

        # ── Post-configuración: quitar los avisos que Nextcloud da de serie ────
        # Sin esto, "Avisos de seguridad y configuración" sale lleno en cuanto el
        # cliente entra: sin caché en memoria, bloqueo transaccional en la BD,
        # cabecera de proxy inverso mal, sin región de teléfono, sin ventana de
        # mantenimiento… Todo son ajustes que el panel PUEDE dejar bien de salida.

        # 1) Proxy inverso: nginx (y Apache en modo dual) va delante. Sin
        #    trusted_proxies, Nextcloud avisa de que un atacante podría falsear la
        #    IP del visitante (y registra la del proxy en vez de la real).
        _run([php_bin, occ, "config:system:set", "trusted_proxies", "0",
              "--value", "127.0.0.1"], cwd=docroot, as_user=owner)
        _run([php_bin, occ, "config:system:set", "trusted_proxies", "1",
              "--value", "::1"], cwd=docroot, as_user=owner)

        # 2) Caché en memoria + bloqueo de ficheros con Redis. El panel ya da un
        #    Redis por dominio (socket unix aislado en private/redis.sock); si está
        #    activo, lo enchufamos. APCu para la caché local (la recomienda NC) y
        #    Redis para la distribuida y el file locking (evita el aviso "la base de
        #    datos está siendo utilizada para bloqueo de ficheros transaccional").
        try:
            from scripts import redis_manager
            sock = redis_manager.socket_path(owner, domain)
            if not os.path.exists(sock):
                redis_manager.enable_instance(owner, domain)
            if os.path.exists(sock):
                _run([php_bin, occ, "config:system:set", "redis", "host",
                      "--value", sock], cwd=docroot, as_user=owner)
                _run([php_bin, occ, "config:system:set", "redis", "port",
                      "--value", "0", "--type", "integer"], cwd=docroot, as_user=owner)
                _run([php_bin, occ, "config:system:set", "memcache.local",
                      "--value", "\\OC\\Memcache\\APCu"], cwd=docroot, as_user=owner)
                _run([php_bin, occ, "config:system:set", "memcache.distributed",
                      "--value", "\\OC\\Memcache\\Redis"], cwd=docroot, as_user=owner)
                _run([php_bin, occ, "config:system:set", "memcache.locking",
                      "--value", "\\OC\\Memcache\\Redis"], cwd=docroot, as_user=owner)
        except Exception as e:
            logger.warning(f"Nextcloud: no se pudo enchufar Redis en {domain}: {e}")

        # 3) Región de teléfono (validación de números sin prefijo) y ventana de
        #    mantenimiento a las 01:00 UTC (los trabajos pesados fuera de horas punta).
        _run([php_bin, occ, "config:system:set", "default_phone_region",
              "--value", "ES"], cwd=docroot, as_user=owner)
        _run([php_bin, occ, "config:system:set", "maintenance_window_start",
              "--value", "1", "--type", "integer"], cwd=docroot, as_user=owner)

        # 4) Previews (miniaturas). Si enabledPreviewProviders NO está definido,
        #    Nextcloud cae a un default corto y el visor avisa en consola con
        #    "Some mimes were ignored because they are not enabled in the server
        #    previews config": sin miniaturas de vídeo ni de HEIC (los móviles
        #    fotografían en HEIC). Lo dejamos explícito.
        #
        #    OJO con el vídeo: OC\Preview\Movie invoca ffmpeg por exec(), y el pool
        #    del panel bloquea exec/system (disable_functions). En un dominio con el
        #    hardening COMPLETO no habrá miniatura de vídeo aunque ffmpeg esté
        #    instalado — hay que relajar el hardening de ese dominio (Domain.
        #    php_hardening_relaxed). Los proveedores de imagen (Image/HEIC/TIFF) sí
        #    funcionan siempre: los resuelve imagick/GD dentro de PHP, sin exec.
        for _i, _prov in enumerate([
            "OC\\Preview\\Image",     # jpeg, png, gif, bmp
            "OC\\Preview\\HEIC",      # fotos de iPhone/Android modernos
            "OC\\Preview\\TIFF",
            "OC\\Preview\\Movie",     # vídeo genérico (ffmpeg)
            "OC\\Preview\\MP4",
            "OC\\Preview\\MKV",
            "OC\\Preview\\AVI",
            "OC\\Preview\\MOV",
            "OC\\Preview\\PDF",
            "OC\\Preview\\MarkDown",
            "OC\\Preview\\TXT",
        ]):
            _run([php_bin, occ, "config:system:set", "enabledPreviewProviders",
                  str(_i), "--value", _prov], cwd=docroot, as_user=owner)

        # 5) La app Fotos SOLO busca dentro de la carpeta `photosLocation` (default:
        #    "Photos", que Nextcloud crea VACÍA). Si el usuario guarda sus fotos en
        #    cualquier otra carpeta —lo normal: "Fotos", "Cámara", "Móvil"…— la
        #    galería sale VACÍA ("No hay fotos ni videos aquí") aunque Archivos las
        #    vea todas. Es de las cosas que más desconciertan al cliente.
        #    Apuntándola a la raíz, la galería muestra todo lo que haya en la cuenta.
        #    Es preferencia de USUARIO (getUserConfig), no config global: un
        #    `config:system:set photosLocation` NO tiene ningún efecto.
        _run([php_bin, occ, "user:setting", admin_user, "photos",
              "photosLocation", "/"], cwd=docroot, as_user=owner)
        _run([php_bin, occ, "user:setting", admin_user, "photos",
              "photosSourceFolders", '["/"]'], cwd=docroot, as_user=owner)

        _chown_tree(docroot, owner)
        return {
            "app": "nextcloud",
            "url": url,
            "admin_url": url,
            "admin_user": admin_user,
            "admin_password": admin_pass,
            "db": db,
        }

    # ── PrestaShop ─────────────────────────────────────────────────────────────
    def install_prestashop(self, domain: str, owner: str, docroot: str,
                           admin_user: str, admin_pass: str, admin_email: str,
                           php_version: Optional[str] = None) -> Dict:
        """
        Descarga la última release de PrestaShop e instala de forma desatendida
        con su CLI (install/index_cli.php). Tras instalar borra install/ y
        renombra el directorio admin/ por seguridad.
        """
        if not _empty_or_safe(docroot):
            raise RequirementsError("El directorio del dominio no está vacío; instala en un dominio limpio")
        _clean_placeholders(docroot)

        php_bin = "php"
        if php_version:
            cand = f"php{php_version}"
            if shutil.which(cand) or os.path.exists(f"/usr/bin/{cand}"):
                php_bin = cand

        ok, why = _check_prestashop_php(php_bin, php_version)
        if not ok:
            raise RequirementsError(why)

        db = self._create_db(owner, "ps")

        parent = os.path.dirname(docroot)
        rel_zip = os.path.join(parent, ".prestashop_release.zip")
        tmp = os.path.join(parent, ".prestashop_tmp")
        _run(["rm", "-rf", tmp, rel_zip])
        _run(["mkdir", "-p", tmp])

        # URL de la última release estable (zip que contiene prestashop.zip + index)
        rc, out, err = _run([
            "curl", "-fsSL",
            "https://api.github.com/repos/PrestaShop/PrestaShop/releases/latest",
        ])
        download_url = ""
        if rc == 0 and out:
            try:
                data = json.loads(out)
                for asset in data.get("assets", []):
                    n = asset.get("name", "")
                    if n.startswith("prestashop_") and n.endswith(".zip"):
                        download_url = asset.get("browser_download_url", "")
                        break
            except (ValueError, KeyError):
                pass
        if not download_url:
            _run(["rm", "-rf", tmp, rel_zip])
            raise RuntimeError("No se pudo determinar la última release de PrestaShop")

        rc, _, err = _run(["curl", "-fsSL", "-o", rel_zip, download_url], timeout=1200)
        if rc != 0:
            _run(["rm", "-rf", tmp, rel_zip])
            raise RuntimeError(f"Descarga de PrestaShop falló: {err}")

        # El zip de release contiene prestashop.zip (el código real) + index.php
        rc, _, err = _run(["unzip", "-q", rel_zip, "-d", tmp])
        if rc != 0:
            _run(["rm", "-rf", tmp, rel_zip])
            raise RuntimeError(f"Descompresión de PrestaShop falló: {err}")

        inner = os.path.join(tmp, "prestashop.zip")
        if not os.path.isfile(inner):
            _run(["rm", "-rf", tmp, rel_zip])
            raise RuntimeError("La release de PrestaShop no contiene prestashop.zip")

        # Limpiar docroot y extraer el código real directamente dentro
        _run(["find", docroot, "-mindepth", "1", "-delete"])
        rc, _, err = _run(["unzip", "-q", inner, "-d", docroot])
        _run(["rm", "-rf", tmp, rel_zip])
        if rc != 0:
            raise RuntimeError(f"Extracción del core de PrestaShop falló: {err}")
        _chown_tree(docroot, owner)

        # Instalación desatendida por CLI
        url = f"https://{domain}"
        cli = os.path.join(docroot, "install", "index_cli.php")
        if not os.path.isfile(cli):
            raise RuntimeError("No se encontró el instalador CLI de PrestaShop (install/index_cli.php)")

        rc, out, err = _run([
            php_bin, cli,
            "--domain=" + domain,
            "--db_server=127.0.0.1",
            "--db_name=" + db["db_name"],
            "--db_user=" + db["db_user"],
            "--db_password=" + db["db_pass"],
            "--prefix=ps_",
            "--name=" + domain,
            "--email=" + admin_email,
            "--password=" + admin_pass,
            "--firstname=Admin",
            "--lastname=" + domain,
            "--language=es",
            "--country=es",
            "--newsletter=0",
            "--send_email=0",
            "--ssl=1",
        ], cwd=os.path.join(docroot, "install"), as_user=owner, timeout=1200)
        if rc != 0:
            raise RuntimeError(f"Instalador CLI de PrestaShop falló: {(err or out)[:500]}")

        # Post-instalación obligatoria: borrar install/ y renombrar admin/ a un
        # nombre no adivinable (PrestaShop lo exige por seguridad).
        admin_token = "admin" + _gen_suffix(8)
        _run(["rm", "-rf", os.path.join(docroot, "install")])
        old_admin = os.path.join(docroot, "admin")
        new_admin = os.path.join(docroot, admin_token)
        if os.path.isdir(old_admin):
            _run(["mv", old_admin, new_admin])

        _chown_tree(docroot, owner)
        return {
            "app": "prestashop",
            "url": url,
            "admin_url": f"{url}/{admin_token}",
            "admin_user": admin_email,   # PrestaShop entra con el email
            "admin_password": admin_pass,
            "db": db,
        }
