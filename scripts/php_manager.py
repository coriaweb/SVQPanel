"""PHP version management"""

import logging
import subprocess

logger = logging.getLogger(__name__)


class PHPManager:
    """Manage PHP versions and FPM services"""

    @staticmethod
    def get_installed_versions() -> list:
        """Get list of installed PHP versions"""
        try:
            # Check which PHP-FPM services are available
            result = subprocess.run(
                ["ls", "-1", "/etc/php"],
                capture_output=True,
                text=True,
                check=False
            )
            versions = result.stdout.strip().split("\n")
            versions = [v for v in versions if v.startswith("php")]
            logger.info(f"Installed PHP versions: {versions}")
            return sorted(versions)
        except Exception as e:
            logger.error(f"Failed to get PHP versions: {str(e)}")
            return []

    @staticmethod
    def php_version_installed(version: str) -> bool:
        """Check if a PHP version is installed"""
        import os
        php_dir = f"/etc/php/{version}"
        return os.path.exists(php_dir)

    @staticmethod
    def restart_php_fpm(version: str) -> bool:
        """Restart PHP-FPM service for a version"""
        try:
            service_name = f"php{version}-fpm"
            subprocess.run(
                ["systemctl", "restart", service_name],
                check=True,
                capture_output=True
            )
            logger.info(f"Restarted: {service_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to restart PHP-FPM: {str(e)}")
            return False
