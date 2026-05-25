"""Domain management - create/delete virtual hosts"""

import logging
from .base import SystemManager
from .utils import (
    validate_domain,
    validate_username,
    get_domain_root,
    get_public_html,
    get_domain_logs,
    get_domain_private,
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
        Create a new domain for a user (Hestia-style structure)

        Crea:
          /home/username/web/domain.com/
            public_html/   ← raíz web
            private/       ← archivos privados
            logs/          ← nginx access + error logs

        Args:
            username: System username
            domain_name: Domain name (e.g., example.com)
            php_version: PHP version (7.4, 8.0-8.5)

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

        domain_root = get_domain_root(username, domain_name)
        public_html = get_public_html(username, domain_name)
        logs_dir = get_domain_logs(username, domain_name)
        private_dir = get_domain_private(username, domain_name)
        nginx_config = get_nginx_config_path(domain_name)

        try:
            logger.info(f"Creating domain: {domain_name} for user: {username}")

            # Estructura de directorios Hestia-style
            # domain_root grupo=www-data para que nginx pueda atravesarlo (750 r-x para www-data)
            # public_html grupo=username con 755 (others pueden leer — nginx es "other" aquí)
            # private y logs: solo el usuario y www-data para logs
            for directory, mode, grp in [
                (domain_root, 0o750, "www-data"),   # nginx (www-data) puede atravesar
                (public_html, 0o755, username),      # lectura pública → nginx puede leer
                (private_dir, 0o750, username),      # privado: solo el usuario
                (logs_dir,    0o750, "www-data"),    # nginx escribe los logs
            ]:
                self.create_directory(directory, mode=mode)
                self.change_ownership(directory, username, grp)

            # Página de bienvenida por defecto
            index_file = f"{public_html}/index.html"
            with open(index_file, "w") as f:
                f.write(f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{domain_name}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #f0f2f5;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
    }}
    .card {{
      background: #fff;
      border-radius: 12px;
      box-shadow: 0 4px 24px rgba(0,0,0,.10);
      padding: 48px 56px;
      text-align: center;
      max-width: 480px;
      width: 90%;
    }}
    .icon {{ font-size: 64px; margin-bottom: 16px; }}
    h1 {{ font-size: 1.7rem; color: #1e2a38; margin-bottom: 8px; }}
    .domain {{ color: #2563eb; font-weight: 600; font-size: 1.1rem; }}
    p {{ color: #6b7280; margin-top: 12px; line-height: 1.6; }}
    .badge {{
      display: inline-block;
      margin-top: 24px;
      padding: 6px 14px;
      background: #f0f9ff;
      color: #0369a1;
      border-radius: 999px;
      font-size: .8rem;
      font-weight: 500;
      border: 1px solid #bae6fd;
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">🌐</div>
    <h1>¡Dominio configurado!</h1>
    <div class="domain">{domain_name}</div>
    <p>
      Este dominio está correctamente configurado en el servidor.<br>
      Sube tus archivos a <code>public_html/</code> para publicar tu sitio web.
    </p>
    <div class="badge">Gestionado con SVQPanel</div>
  </div>
</body>
</html>
""")
            self.change_ownership(index_file, username)

            # Crear ficheros de log vacíos con los permisos correctos
            for log_file in [f"{logs_dir}/nginx.access.log", f"{logs_dir}/nginx.error.log"]:
                self.execute_command(["touch", log_file])
                self.execute_command(["chown", f"www-data:{username}", log_file])
                self.execute_command(["chmod", "640", log_file])

            # Crear configuración Nginx
            config_content = generate_nginx_config(
                domain_name,
                username,
                php_version,
                ssl_enabled=False
            )

            with open(nginx_config, "w") as f:
                f.write(config_content)
            logger.info(f"Created Nginx config: {nginx_config}")

            # Activar site (symlink a sites-enabled)
            enabled_link = f"/etc/nginx/sites-enabled/{domain_name}"
            self.execute_command(["ln", "-sf", nginx_config, enabled_link])

            # Test y reload Nginx
            if not reload_nginx():
                raise RuntimeError("Nginx configuration test failed")

            logger.info(f"Domain created: {domain_name}")
            return {
                "success": True,
                "domain": domain_name,
                "user": username,
                "php_version": php_version,
                "public_html": public_html,
                "logs_dir": logs_dir,
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

    def delete_domain(self, domain_name: str, username: str = None, cleanup_dirs: bool = True) -> dict:
        """
        Delete a domain and its directory structure

        Args:
            domain_name: Domain name
            username: System username (needed to delete /home/user/web/domain/)
            cleanup_dirs: Delete domain directory (default True)

        Returns:
            {'success': True, 'deleted_domain': 'example.com'}
        """
        if not validate_domain(domain_name):
            raise ValueError(f"Invalid domain: {domain_name}")

        nginx_config = get_nginx_config_path(domain_name)
        enabled_link = f"/etc/nginx/sites-enabled/{domain_name}"

        try:
            logger.info(f"Deleting domain: {domain_name}")

            # Desactivar y eliminar config Nginx
            if self.file_exists(enabled_link):
                self.execute_command(["rm", "-f", enabled_link])
                logger.info(f"Removed Nginx symlink: {enabled_link}")

            if self.file_exists(nginx_config):
                self.execute_command(["rm", "-f", nginx_config])
                logger.info(f"Removed Nginx config: {nginx_config}")

            # Eliminar directorio del dominio si se conoce el usuario
            if cleanup_dirs and username:
                domain_root = get_domain_root(username, domain_name)
                if self.file_exists(domain_root):
                    self.execute_command(["rm", "-rf", domain_root])
                    logger.info(f"Removed domain directory: {domain_root}")

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

    def update_nginx_ipv6(
        self,
        username: str,
        domain_name: str,
        php_version: str,
        ipv6_address: str = None,
        ssl_enabled: bool = False
    ) -> dict:
        """
        Regenera el vhost nginx de un dominio con (o sin) IPv6.

        Args:
            username: Propietario del dominio
            domain_name: Nombre del dominio
            php_version: Versión PHP actual
            ipv6_address: IPv6 a añadir al listen, o None para quitarla
            ssl_enabled: Si SSL está activo

        Returns:
            {'success': True, 'domain': ..., 'ipv6': ...}
        """
        if not validate_domain(domain_name):
            raise ValueError(f"Invalid domain: {domain_name}")

        nginx_config = get_nginx_config_path(domain_name)

        try:
            logger.info(f"Regenerating nginx config for {domain_name} with IPv6={ipv6_address}")

            config_content = generate_nginx_config(
                domain_name,
                username,
                php_version,
                ssl_enabled=ssl_enabled,
                ipv6=ipv6_address
            )

            with open(nginx_config, "w") as f:
                f.write(config_content)

            if not reload_nginx():
                raise RuntimeError("Nginx reload failed after IPv6 update")

            logger.info(f"Nginx updated for {domain_name} with IPv6={ipv6_address}")
            return {
                "success": True,
                "domain": domain_name,
                "ipv6": ipv6_address
            }

        except Exception as e:
            logger.error(f"Failed to update nginx IPv6: {str(e)}")
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
