"""PHP version management — install, enable, disable, uninstall PHP-FPM versions"""

import os
import logging
from typing import List, Dict, Optional
from .base import SystemManager

logger = logging.getLogger(__name__)

ALL_VERSIONS = ["7.4", "8.0", "8.1", "8.2", "8.3", "8.4", "8.5"]

# Paquetes base que deben instalarse (sin estos PHP no funciona)
BASE_EXTENSIONS = ["cli", "fpm", "pgsql", "mysql", "curl", "gd", "mbstring", "xml", "zip", "bcmath"]

# Extensiones opcionales — se instalan una a una, los fallos se ignoran
OPTIONAL_EXTENSIONS = ["opcache", "intl", "soap", "readline", "imagick"]


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

        # Enable and start FPM
        self.execute_command(["systemctl", "enable", f"php{version}-fpm"])
        self.execute_command(["systemctl", "start", f"php{version}-fpm"])

        logger.info(f"PHP {version} installed and FPM started")
        return self.get_status(version)

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
