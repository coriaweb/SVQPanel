"""PHP version management — install, enable, disable, uninstall PHP-FPM versions"""

import os
import re
import logging
from typing import List, Dict, Optional
from .base import SystemManager

logger = logging.getLogger(__name__)

ALL_VERSIONS = ["7.3", "7.4", "8.0", "8.1", "8.2", "8.3", "8.4", "8.5"]

# Versiones EOL (sin soporte de seguridad oficial de php.net). Se ofrecen porque
# algunos sitios legacy las necesitan (migraciones), pero se marcan "deprecated"
# en la UI para desaconsejar elegirlas en sitios nuevos.
# Ref: https://www.php.net/supported-versions.php (7.x y 8.0/8.1 ya EOL).
DEPRECATED_VERSIONS = ["7.3", "7.4", "8.0", "8.1"]

# Paquetes base que deben instalarse (sin estos PHP no funciona)
BASE_EXTENSIONS = ["cli", "fpm", "pgsql", "mysql", "curl", "gd", "mbstring", "xml", "zip", "bcmath"]

# Extensiones opcionales — se instalan una a una, los fallos se ignoran.
# DEBE ser la misma lista que el loop de PHP de install.sh: una versión
# instalada desde el panel tiene que nacer igual que una del install.
# gmp/intl/imagick/apcu: Nextcloud. redis: caché de objetos por dominio.
OPTIONAL_EXTENSIONS = ["opcache", "intl", "soap", "readline", "gmp", "imagick", "apcu", "redis"]

# Paquetes que el gestor de extensiones NO deja desinstalar: sin ellos la
# versión deja de funcionar (base), o el panel pierde una feature transversal
# (redis: caché de objetos por dominio; opcache: rendimiento de todos los sitios).
PROTECTED_EXTENSIONS = set(BASE_EXTENSIONS) | {"common", "opcache", "redis"}

# Nombre de extensión válido en paquetes Debian (php8.2-<ext>).
# \Z y no $: $ aceptaría un \n final ("ldap\n" pasaría la validación).
_EXT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9+.-]{0,40}\Z")

# ─────────────────────────────────────────────────────────────────────────────
# ionCube Loader — extensión ESPECIAL (no es un paquete apt)
# ─────────────────────────────────────────────────────────────────────────────
# WHMCS y otro software comercial vienen cifrados con ionCube y NO arrancan sin su
# loader ("Script error: the ionCube Loader for PHP needs to be installed"). Pero
# ionCube no está en apt ni en Sury: es un .so propietario que se descarga de
# ioncube.com y se carga con `zend_extension` (no con `extension`). Por eso el
# buscador de extensiones del panel —que lista php{ver}-* de apt— nunca lo mostraba.
# Lo tratamos como extensión especial: aparece en la lista y se instala/quita con
# esta lógica propia en vez de con apt.
IONCUBE_EXT      = "ioncube"
IONCUBE_URL      = "https://downloads.ioncube.com/loader_downloads/ioncube_loaders_lin_x86-64.tar.gz"
IONCUBE_INI_NAME = "00-ioncube.ini"   # 00- para cargarse ANTES que el resto


class PHPManager(SystemManager):
    """Manage PHP versions and FPM services on Debian/Ubuntu systems"""

    def __init__(self):
        super().__init__(require_root=True)

    # ─────────────────────────── helpers ────────────────────────────────────

    def get_socket_path(self, version: str) -> str:
        """Return the PHP-FPM unix socket path for a version"""
        return f"/run/php/php{version}-fpm.sock"

    def is_installed(self, version: str) -> bool:
        """Check if php{version}-fpm package is installed via dpkg"""
        rc, _, _ = self.execute_command(
            ["dpkg", "-l", f"php{version}-fpm"],
            check=False
        )
        return rc == 0

    def is_running(self, version: str) -> bool:
        """Check if PHP-FPM is active by verifying the socket file"""
        return os.path.exists(self.get_socket_path(version))

    def is_enabled(self, version: str) -> bool:
        """Check if PHP-FPM systemd unit is set to start on boot"""
        rc, stdout, _ = self.execute_command(
            ["systemctl", "is-enabled", f"php{version}-fpm"],
            check=False
        )
        return stdout.strip() == "enabled"

    # ────────────────────────── public API ──────────────────────────────────

    def get_all_status(self) -> List[Dict]:
        """
        Return status for every supported PHP version.

        Returns list of dicts:
            [{"version": "8.2", "installed": True, "running": True,
              "enabled": True, "socket": "/run/php/php8.2-fpm.sock"}, ...]
        """
        result = []
        for version in ALL_VERSIONS:
            installed = self.is_installed(version)
            running = self.is_running(version) if installed else False
            enabled = self.is_enabled(version) if installed else False
            result.append({
                "version": version,
                "installed": installed,
                "running": running,
                "enabled": enabled,
                "socket": self.get_socket_path(version) if running else None,
                "deprecated": version in DEPRECATED_VERSIONS,
            })
        return result

    def get_status(self, version: str) -> Dict:
        """Return status for a single PHP version"""
        installed = self.is_installed(version)
        running = self.is_running(version) if installed else False
        enabled = self.is_enabled(version) if installed else False
        return {
            "version": version,
            "installed": installed,
            "running": running,
            "enabled": enabled,
            "socket": self.get_socket_path(version) if running else None,
        }

    def install(self, version: str) -> Dict:
        """
        Install PHP version with FPM and common extensions, then start it.

        If already installed, just enables and starts FPM.
        """
        if version not in ALL_VERSIONS:
            raise ValueError(f"Unknown PHP version: {version}")

        if self.is_installed(version):
            logger.info(f"PHP {version} already installed — enabling service")
            return self.enable(version)

        logger.info(f"Installing PHP {version}...")

        # Make sure Sury repo is present (needed for 8.4, 8.5 on Debian)
        self._ensure_sury_repo()

        # Refresh apt cache
        self.execute_command(["apt-get", "update", "-qq"], check=False)

        # Install base packages as a batch (fail loudly if core install fails)
        base_pkgs = [f"php{version}"] + [f"php{version}-{ext}" for ext in BASE_EXTENSIONS]
        self.execute_command(
            ["apt-get", "install", "-y", "-q",
             "-o", "Dpkg::Options::=--force-confnew"] + base_pkgs
        )
        logger.info(f"PHP {version} base packages installed")

        # Optional extensions one-by-one (failures are non-fatal)
        for ext in OPTIONAL_EXTENSIONS:
            rc, _, err = self.execute_command(
                ["apt-get", "install", "-y", "-q", f"php{version}-{ext}"],
                check=False
            )
            if rc != 0:
                logger.debug(f"Optional extension php{version}-{ext} not available: {err.strip()}")

        # Ajustes del php.ini global — los MISMOS que aplica install.sh, para
        # que una versión instalada desde el panel nazca igual que una del
        # install: disable_functions vacío (el hardening va por pool, y un pool
        # puede añadir pero no quitar), cabecera X-PHP-Originating-Script para
        # rastrear spam, y memory_limit global = techo de los overrides (256M).
        self._apply_global_ini_policy(version)

        # Enable and start FPM
        self.execute_command(["systemctl", "enable", f"php{version}-fpm"])
        self.execute_command(["systemctl", "restart", f"php{version}-fpm"])

        logger.info(f"PHP {version} installed and FPM started")
        return self.get_status(version)

    def _apply_global_ini_policy(self, version: str) -> None:
        """Aplica al php.ini de FPM la política global del panel (best-effort)."""
        ini = f"/etc/php/{version}/fpm/php.ini"
        if not os.path.exists(ini):
            return
        try:
            with open(ini) as f:
                lines = f.read().splitlines()
            wanted = {
                "disable_functions": "disable_functions =",
                "mail.add_x_header": "mail.add_x_header = On",
                "memory_limit": "memory_limit = 256M",
            }
            seen = set()
            out = []
            for line in lines:
                stripped = line.lstrip(" \t;").strip()
                replaced = False
                for key, repl in wanted.items():
                    if stripped.startswith(key) and "=" in stripped and key not in seen:
                        out.append(repl)
                        seen.add(key)
                        replaced = True
                        break
                if not replaced:
                    out.append(line)
            for key, repl in wanted.items():
                if key not in seen:
                    out.append(repl)
            tmp = ini + ".tmp"
            with open(tmp, "w") as f:
                f.write("\n".join(out) + "\n")
            os.replace(tmp, ini)
        except OSError as e:
            logger.warning(f"No se pudo ajustar el php.ini global de {version}: {e}")

    def enable(self, version: str) -> Dict:
        """Enable and start PHP-FPM (must be installed first)"""
        if not self.is_installed(version):
            raise RuntimeError(f"PHP {version} is not installed. Install it first.")

        self.execute_command(["systemctl", "enable", f"php{version}-fpm"])
        self.execute_command(["systemctl", "start", f"php{version}-fpm"])

        logger.info(f"PHP {version}-fpm enabled and started")
        return self.get_status(version)

    def disable(self, version: str) -> Dict:
        """Stop and disable PHP-FPM without removing packages"""
        if not self.is_installed(version):
            raise RuntimeError(f"PHP {version} is not installed.")

        self.execute_command(["systemctl", "stop", f"php{version}-fpm"], check=False)
        self.execute_command(["systemctl", "disable", f"php{version}-fpm"], check=False)

        logger.info(f"PHP {version}-fpm stopped and disabled")
        return self.get_status(version)

    def uninstall(self, version: str) -> Dict:
        """Stop, disable and purge all PHP version packages"""
        if not self.is_installed(version):
            logger.info(f"PHP {version} not installed — nothing to do")
            return {"version": version, "installed": False, "running": False, "enabled": False, "socket": None}

        # 1. Stop and disable first
        self.execute_command(["systemctl", "stop", f"php{version}-fpm"], check=False)
        self.execute_command(["systemctl", "disable", f"php{version}-fpm"], check=False)

        # 2. Purge packages
        pkgs_to_remove = (
            [f"php{version}"]
            + [f"php{version}-fpm"]
            + [f"php{version}-{ext}" for ext in BASE_EXTENSIONS]
            + [f"php{version}-{ext}" for ext in OPTIONAL_EXTENSIONS]
        )
        # Remove only installed ones to avoid apt errors
        installed_pkgs = [p for p in pkgs_to_remove if self._dpkg_installed(p)]
        if installed_pkgs:
            self.execute_command(
                ["apt-get", "remove", "-y", "-q", "--purge"] + installed_pkgs,
                check=False
            )
            self.execute_command(["apt-get", "autoremove", "-y", "-q"], check=False)

        logger.info(f"PHP {version} uninstalled")
        return {"version": version, "installed": False, "running": False, "enabled": False, "socket": None}

    # ─────────────────── extensiones (paquetes php{ver}-*) ──────────────────

    def list_extensions(self, version: str) -> List[Dict]:
        """
        Todas las extensiones disponibles en apt para una versión (php{ver}-*),
        con su descripción y si están instaladas. Incluye también las instaladas
        que ya no estén en el repo (para poder quitarlas igualmente).
        """
        if version not in ALL_VERSIONS:
            raise ValueError(f"Unknown PHP version: {version}")
        prefix = f"php{version}-"

        available: Dict[str, str] = {}
        rc, out, _ = self.execute_command(
            ["apt-cache", "search", "--names-only", f"^{re.escape(prefix)}"],
            check=False)
        if rc == 0:
            for line in out.splitlines():
                name, sep, desc = line.partition(" - ")
                name = name.strip()
                if sep and name.startswith(prefix):
                    available[name[len(prefix):]] = desc.strip()

        installed = set()
        rc, out, _ = self.execute_command(
            ["dpkg-query", "-W", "-f=${Package}\t${Status}\n", f"{prefix}*"],
            check=False)
        if rc == 0:
            for line in out.splitlines():
                pkg, _, st = line.partition("\t")
                if pkg.startswith(prefix) and "install ok installed" in st:
                    installed.add(pkg[len(prefix):])

        exts = []
        for name in sorted(set(available) | installed):
            exts.append({
                "name":        name,
                "package":     f"{prefix}{name}",
                "description": available.get(name, ""),
                "installed":   name in installed,
                "protected":   name in PROTECTED_EXTENSIONS,
            })

        # ionCube: no está en apt (es un .so de ioncube.com), pero lo ofrecemos en
        # la lista como una extensión más — WHMCS y otro software comercial cifrado
        # no arrancan sin él y el usuario no tenía forma de activarlo desde el panel.
        exts.append({
            "name":        IONCUBE_EXT,
            "package":     "ionCube Loader (ioncube.com)",
            "description": "Loader para código PHP cifrado con ionCube (WHMCS y otro "
                           "software comercial). No es un paquete apt: el panel descarga "
                           "el loader oficial y lo activa como zend_extension.",
            "installed":   self.ioncube_installed(version),
            "protected":   False,
        })
        exts.sort(key=lambda e: e["name"])
        return exts

    # ── ionCube (extensión especial: .so de ioncube.com, no paquete apt) ──────
    def _ioncube_ini_path(self, version: str) -> str:
        return f"/etc/php/{version}/mods-available/ioncube.ini"

    def ioncube_installed(self, version: str) -> bool:
        """True si el loader de ionCube está activo para esta versión de PHP."""
        return os.path.exists(f"/etc/php/{version}/fpm/conf.d/{IONCUBE_INI_NAME}")

    def install_ioncube(self, version: str) -> None:
        """
        Instala el ionCube Loader para una versión de PHP: descarga el tarball
        oficial, copia el .so al extension_dir de esa versión y lo carga como
        zend_extension en FPM y CLI. Idempotente.
        """
        import tempfile, glob
        # extension_dir real de esa versión (varía por API de PHP: 20210902…)
        rc, out, _ = self.execute_command(
            [f"php{version}", "-r", "echo ini_get('extension_dir');"], check=False)
        ext_dir = (out or "").strip()
        if rc != 0 or not ext_dir or not os.path.isdir(ext_dir):
            raise RuntimeError(f"No se pudo determinar el extension_dir de PHP {version}")

        with tempfile.TemporaryDirectory() as tmp:
            tgz = os.path.join(tmp, "ioncube.tar.gz")
            rc, _, err = self.execute_command(
                ["curl", "-sSL", "--max-time", "180", "-o", tgz, IONCUBE_URL], check=False)
            if rc != 0 or not os.path.exists(tgz):
                raise RuntimeError(f"No se pudo descargar ionCube: {err.strip()[-200:]}")
            rc, _, err = self.execute_command(["tar", "xzf", tgz, "-C", tmp], check=False)
            if rc != 0:
                raise RuntimeError(f"No se pudo extraer ionCube: {err.strip()[-200:]}")

            so_src = os.path.join(tmp, "ioncube", f"ioncube_loader_lin_{version}.so")
            if not os.path.exists(so_src):
                # ionCube tarda en publicar loader para las versiones más nuevas.
                have = sorted(os.path.basename(p).replace("ioncube_loader_lin_", "").replace(".so", "")
                              for p in glob.glob(os.path.join(tmp, "ioncube", "ioncube_loader_lin_*.so"))
                              if "_ts" not in p)
                raise ValueError(
                    f"ionCube aún no publica loader para PHP {version}. "
                    f"Versiones con loader disponible: {', '.join(have) or '—'}")

            so_dst = os.path.join(ext_dir, f"ioncube_loader_lin_{version}.so")
            self.execute_command(["cp", "-f", so_src, so_dst], check=False)
            self.execute_command(["chmod", "644", so_dst], check=False)

        # ionCube se carga con zend_extension (NO 'extension') y debe ir el primero.
        ini = self._ioncube_ini_path(version)
        with open(ini, "w") as f:
            f.write(
                "; ionCube Loader — necesario para codigo cifrado con ionCube (WHMCS…).\n"
                "; No es un paquete apt: el .so viene de ioncube.com y se carga como\n"
                "; zend_extension. Lo gestiona el panel (PHP → Extensiones).\n"
                f"zend_extension = {so_dst}\n"
            )
        for sapi in ("fpm", "cli"):
            d = f"/etc/php/{version}/{sapi}/conf.d"
            if os.path.isdir(d):
                link = os.path.join(d, IONCUBE_INI_NAME)
                if os.path.islink(link) or os.path.exists(link):
                    os.remove(link)
                os.symlink(ini, link)

        self._reload_fpm(version)
        logger.info(f"ionCube Loader instalado para PHP {version}")

    def remove_ioncube(self, version: str) -> None:
        """Desactiva el ionCube Loader de una versión (quita los symlinks + ini)."""
        for sapi in ("fpm", "cli"):
            link = f"/etc/php/{version}/{sapi}/conf.d/{IONCUBE_INI_NAME}"
            if os.path.islink(link) or os.path.exists(link):
                os.remove(link)
        ini = self._ioncube_ini_path(version)
        if os.path.exists(ini):
            os.remove(ini)
        self._reload_fpm(version)
        logger.info(f"ionCube Loader desactivado en PHP {version}")

    def install_extension(self, version: str, ext: str) -> None:
        """Instala un paquete php{ver}-{ext} del repo y recarga FPM.

        ionCube es un caso especial (no es apt): se delega en install_ioncube().
        """
        self._validate_ext(version, ext)
        if ext == IONCUBE_EXT:
            return self.install_ioncube(version)
        pkg = f"php{version}-{ext}"
        rc, _, _ = self.execute_command(["apt-cache", "show", pkg], check=False)
        if rc != 0:
            raise ValueError(f"El paquete {pkg} no existe en los repositorios")
        rc, _, err = self.execute_command(
            ["apt-get", "install", "-y", "-q", pkg], check=False)
        if rc != 0:
            raise RuntimeError(f"apt-get install {pkg} falló: {err.strip()[-300:]}")
        self._reload_fpm(version)
        logger.info(f"Extensión {pkg} instalada")

    def remove_extension(self, version: str, ext: str) -> None:
        """Desinstala un paquete php{ver}-{ext} (nunca los protegidos) y recarga FPM.

        ionCube es un caso especial (no es apt): se delega en remove_ioncube().
        """
        self._validate_ext(version, ext)
        if ext == IONCUBE_EXT:
            return self.remove_ioncube(version)
        if ext in PROTECTED_EXTENSIONS:
            raise ValueError(
                f"'{ext}' es un paquete protegido: sin él la versión o una "
                f"feature del panel dejarían de funcionar")
        pkg = f"php{version}-{ext}"
        if not self._dpkg_installed(pkg):
            return
        rc, _, err = self.execute_command(
            ["apt-get", "remove", "-y", "-q", pkg], check=False)
        if rc != 0:
            raise RuntimeError(f"apt-get remove {pkg} falló: {err.strip()[-300:]}")
        self.execute_command(["apt-get", "autoremove", "-y", "-q"], check=False)
        self._reload_fpm(version)
        logger.info(f"Extensión {pkg} desinstalada")

    def _validate_ext(self, version: str, ext: str) -> None:
        if version not in ALL_VERSIONS:
            raise ValueError(f"Unknown PHP version: {version}")
        if not self.is_installed(version):
            raise RuntimeError(f"PHP {version} no está instalado")
        if not _EXT_NAME_RE.match(ext or ""):
            raise ValueError(f"Nombre de extensión inválido: {ext!r}")

    def _reload_fpm(self, version: str) -> None:
        # USR2 (reload) relanza los workers con la config/extensiones nuevas
        # sin cortar conexiones; si no está corriendo no pasa nada.
        self.execute_command(
            ["systemctl", "reload-or-restart", f"php{version}-fpm"], check=False)

    # ────────────────────────── private ─────────────────────────────────────

    def _dpkg_installed(self, package: str) -> bool:
        """Return True if a specific package name is installed"""
        rc, _, _ = self.execute_command(["dpkg", "-l", package], check=False)
        return rc == 0

    def _ensure_sury_repo(self):
        """Add Ondřej Surý PHP repo if not already present"""
        sury_list = "/etc/apt/sources.list.d/sury-php.list"

        if os.path.exists(sury_list):
            logger.info("Sury PHP repo already configured")
            return

        logger.info("Adding Sury PHP repository…")

        # Detect Debian/Ubuntu codename
        _, codename, _ = self.execute_command(["lsb_release", "-sc"], check=False)
        codename = codename.strip()
        if not codename:
            codename = "bookworm"  # Debian 12 fallback

        # Import GPG key
        self.execute_command(
            "curl -sSL https://packages.sury.org/php/apt.gpg | "
            "gpg --dearmor -o /usr/share/keyrings/deb.sury.org-php.gpg",
        )

        # Write sources.list entry
        with open(sury_list, "w") as f:
            f.write(
                f"deb [signed-by=/usr/share/keyrings/deb.sury.org-php.gpg] "
                f"https://packages.sury.org/php/ {codename} main\n"
            )

        # Refresh
        self.execute_command(["apt-get", "update", "-qq"], check=False)
        logger.info("Sury repo added")

    # ────────────────────── legacy compatibility ─────────────────────────────

    @staticmethod
    def get_installed_versions() -> list:
        """Legacy: list dirs under /etc/php/"""
        try:
            import subprocess
            result = subprocess.run(
                ["ls", "-1", "/etc/php"],
                capture_output=True, text=True, check=False
            )
            versions = [v for v in result.stdout.strip().split("\n") if v]
            return sorted(versions)
        except Exception:
            return []

    @staticmethod
    def php_version_installed(version: str) -> bool:
        """Legacy: check /etc/php/{version} exists"""
        return os.path.isdir(f"/etc/php/{version}")
