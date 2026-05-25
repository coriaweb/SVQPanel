"""Domain management - create/delete virtual hosts"""

import logging
from .base import SystemManager
from .utils import (
    validate_domain,
    validate_username,
    get_public_html,
    get_nginx_config_path,
    generate_nginx_config,
    reload_nginx
)

logger = logging.getLogger(__name__)


class DomainManager(SystemManager):
    """Manage domains and virtual hosts"""

    def __init__(self):
        super().__init__(require_root=True)

    def create_domain(
        self,
        username: str,
        domain_name: str,
        php_version: str = "8.2"
    ) -> dict:
        """
        Create a new domain for a user

        Args:
            username: System username
            domain_name: Domain name (e.g., example.com)
            php_version: PHP version (7.4, 8.0, 8.1, 8.2, 8.3)

        Returns:
            {'success': True, 'domain': 'example.com', ...}
        """
        if not validate_username(username):
            raise ValueError(f"Invalid username: {username}")

        if not validate_domain(domain_name):
            raise ValueError(f"Invalid domain: {domain_name}")

        valid_php = ["7.4", "8.0", "8.1", "8.2", "8.3", "8.4", "8.5"]
        if php_version not in valid_php:
            raise ValueError(f"Invalid PHP version: {php_version}")

        public_html = get_public_html(username, domain_name)
        nginx_config = get_nginx_config_path(domain_name)

        try:
            logger.info(f"Creating domain: {domain_name} for user: {username}")

            # Create public_html directory
            self.create_directory(public_html, mode=0o755)
            self.change_ownership(public_html, username)

            # Create index.php
            index_file = f"{public_html}/index.php"
            with open(index_file, "w") as f:
                f.write("<?php phpinfo(); ?>\n")
            self.change_ownership(index_file, username)

            # Create Nginx config
            config_content = generate_nginx_config(
                domain_name,
                username,
                php_version,
                ssl_enabled=False
            )

            with open(nginx_config, "w") as f:
                f.write(config_content)
            logger.info(f"Created Nginx config: {nginx_config}")

            # Enable site (symlink to sites-enabled)
            enabled_link = f"/etc/nginx/sites-enabled/{domain_name}"
            self.execute_command([
                "ln", "-sf",
                nginx_config,
                enabled_link
            ])

            # Test and reload Nginx
            if not reload_nginx():
                raise RuntimeError("Nginx configuration test failed")

            logger.info(f"Domain created: {domain_name}")
            return {
                "success": True,
                "domain": domain_name,
                "user": username,
                "php_version": php_version,
                "public_html": public_html,
                "nginx_config": nginx_config
            }

        except Exception as e:
            logger.error(f"Failed to create domain: {str(e)}")
            # Cleanup on failure
            try:
                self.delete_domain(domain_name, cleanup_dirs=True)
            except:
                pass
            raise

    def delete_domain(self, domain_name: str, cleanup_dirs: bool = True) -> dict:
        """
        Delete a domain

        Args:
            domain_name: Domain name
            cleanup_dirs: Delete public_html directory

        Returns:
            {'success': True, 'deleted_domain': 'example.com'}
        """
        if not validate_domain(domain_name):
            raise ValueError(f"Invalid domain: {domain_name}")

        nginx_config = get_nginx_config_path(domain_name)
        enabled_link = f"/etc/nginx/sites-enabled/{domain_name}"

        try:
            logger.info(f"Deleting domain: {domain_name}")

            # Delete Nginx symlink
            if self.file_exists(enabled_link):
                self.execute_command(["rm", enabled_link])
                logger.info(f"Removed Nginx symlink: {enabled_link}")

            # Delete Nginx config
            if self.file_exists(nginx_config):
                self.execute_command(["rm", nginx_config])
                logger.info(f"Removed Nginx config: {nginx_config}")

            # Delete public_html directory if requested
            # Note: This is user-specific, would need to query DB
            # Leaving this to be handled at API level

            # Reload Nginx
            if not reload_nginx():
                logger.warning("Nginx reload had issues but continuing...")

            logger.info(f"Domain deleted: {domain_name}")
            return {
                "success": True,
                "deleted_domain": domain_name
            }

        except Exception as e:
            logger.error(f"Failed to delete domain: {str(e)}")
            raise

    def change_php_version(
        self,
        domain_name: str,
        php_version: str
    ) -> dict:
        """
        Change PHP version for a domain

        Args:
            domain_name: Domain name
            php_version: New PHP version

        Returns:
            {'success': True, 'domain': 'example.com', 'php_version': '8.2'}
        """
        if not validate_domain(domain_name):
            raise ValueError(f"Invalid domain: {domain_name}")

        valid_php = ["7.4", "8.0", "8.1", "8.2", "8.3", "8.4", "8.5"]
        if php_version not in valid_php:
            raise ValueError(f"Invalid PHP version: {php_version}")

        nginx_config = get_nginx_config_path(domain_name)

        try:
            logger.info(f"Changing PHP version for {domain_name} to {php_version}")

            # Read current config
            with open(nginx_config, "r") as f:
                config = f.read()

            # Replace PHP socket version
            old_socket = f"php[0-9.]+\\.sock"
            new_socket = f"php{php_version}.sock"

            import re
            config = re.sub(
                f"php[0-9.]+\\.sock",
                new_socket,
                config
            )

            # Write updated config
            with open(nginx_config, "w") as f:
                f.write(config)

            # Reload Nginx
            if not reload_nginx():
                raise RuntimeError("Nginx reload failed")

            logger.info(f"PHP version changed: {domain_name} → {php_version}")
            return {
                "success": True,
                "domain": domain_name,
                "php_version": php_version
            }

        except Exception as e:
            logger.error(f"Failed to change PHP version: {str(e)}")
            raise
