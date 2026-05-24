"""SSL certificate management with Let's Encrypt"""

import logging
import subprocess
from .base import SystemManager
from .utils import validate_domain

logger = logging.getLogger(__name__)


class SSLManager(SystemManager):
    """Manage SSL certificates with Let's Encrypt"""

    def __init__(self):
        super().__init__(require_root=True)

    def create_ssl(self, domain_name: str) -> dict:
        """
        Create SSL certificate with Let's Encrypt

        Args:
            domain_name: Domain name

        Returns:
            {'success': True, 'domain': 'example.com', 'expires': '2024-...'}
        """
        if not validate_domain(domain_name):
            raise ValueError(f"Invalid domain: {domain_name}")

        try:
            logger.info(f"Creating SSL cert for: {domain_name}")

            # Run certbot
            self.execute_command([
                "certbot",
                "certonly",
                "--nginx",
                "-d", domain_name,
                "-d", f"www.{domain_name}",
                "--non-interactive",
                "--agree-tos",
                "-m", "admin@example.com"  # TODO: from config
            ])

            # Set up auto-renewal
            self.execute_command([
                "systemctl",
                "enable",
                "certbot.timer"
            ])

            logger.info(f"SSL cert created: {domain_name}")
            return {
                "success": True,
                "domain": domain_name,
                "status": "Certificate created and renewal enabled"
            }

        except Exception as e:
            logger.error(f"Failed to create SSL: {str(e)}")
            raise

    def revoke_ssl(self, domain_name: str) -> dict:
        """
        Revoke SSL certificate

        Args:
            domain_name: Domain name

        Returns:
            {'success': True, 'revoked_domain': 'example.com'}
        """
        if not validate_domain(domain_name):
            raise ValueError(f"Invalid domain: {domain_name}")

        try:
            logger.info(f"Revoking SSL: {domain_name}")

            self.execute_command([
                "certbot",
                "revoke",
                "--cert-name", domain_name,
                "--non-interactive"
            ], check=False)

            # Delete cert
            self.execute_command([
                "rm", "-rf",
                f"/etc/letsencrypt/live/{domain_name}"
            ])

            logger.info(f"SSL revoked: {domain_name}")
            return {
                "success": True,
                "revoked_domain": domain_name
            }

        except Exception as e:
            logger.error(f"Failed to revoke SSL: {str(e)}")
            raise
