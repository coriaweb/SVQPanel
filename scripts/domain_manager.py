"""Domain management - create/delete virtual hosts"""

import os
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
    reload_nginx,
    reload_nginx_or_diagnose,
    write_fastcgi_cache_zone,
    remove_fastcgi_cache_zone,
    write_ratelimit_zone,
    remove_ratelimit_zone,
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
        php_version: str = "8.2",
        webserver: str = None
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
            webserver: "nginx", "apache", o None para auto-detectar

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

        # Auto-detectar webserver si no se especifica
        if webserver is None:
            from scripts.webserver_config import supports_nginx, supports_apache
            # Si soporta apache, crear vhost Apache; si no, nginx
            if supports_apache():
                webserver = "apache"
            else:
                webserver = "nginx"

        domain_root = get_domain_root(username, domain_name)
        public_html = get_public_html(username, domain_name)
        logs_dir = get_domain_logs(username, domain_name)
        private_dir = get_domain_private(username, domain_name)

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

            # Crear el pool PHP-FPM dedicado (aislamiento: open_basedir +
            # disable_functions + tmp propio). Todos los dominios lo tienen.
            from scripts import php_ini_manager as phpini
            ok, msg = phpini.write_pool(domain_name, php_version, username, {})
            if not ok:
                raise RuntimeError(f"No se pudo crear el pool PHP-FPM: {msg}")
            php_socket = phpini.pool_socket_path(domain_name)

            # Crear configuración según webserver.
            # IMPORTANTE (modo apache+nginx): nginx es SIEMPRE el front que
            # escucha 80/443, hace SSL y proxy_pass a Apache (127.0.0.1:8181),
            # que sirve el PHP respetando .htaccess. Por tanto, en modo "apache"
            # hay que crear AMBOS vhosts (Apache backend + nginx front), no solo
            # el de Apache. Antes solo se creaba el de Apache y el dominio quedaba
            # sin vhost nginx activo → nginx servía la página por defecto y el
            # cert del panel (ERR_CERT_COMMON_NAME_INVALID).
            if webserver == "apache":
                from scripts.apache_vhost_generator import generate_apache_vhost
                from scripts.webserver_config import get_apache_vhost_path

                # 1) Vhost Apache BACKEND (127.0.0.1:8181)
                apache_path = get_apache_vhost_path(domain_name)
                with open(apache_path, "w") as f:
                    f.write(generate_apache_vhost(
                        domain_name, username, php_version, ssl_enabled=False,
                    ))
                logger.info(f"Created Apache vhost: {apache_path}")
                self.execute_command(["a2ensite", domain_name], check=False)
                # Validar la configuración ANTES de recargar. Si el configtest
                # falla, distinguimos si el problema es ESTE vhost o uno ajeno
                # (un vhost roto de otro dominio bloquearía el reload de todos).
                rc, _out, err = self.execute_command(
                    ["apache2ctl", "configtest"], check=False)
                if rc != 0:
                    err = (err or "").strip()
                    if domain_name in err:
                        raise RuntimeError(f"Apache configtest falló para este dominio: {err}")
                    raise RuntimeError(
                        "Apache no puede recargar porque otro vhost tiene un error "
                        f"(no es de este dominio). Revisa `apache2ctl configtest`: {err}")
                try:
                    self.execute_command(["systemctl", "reload", "apache2"])
                except Exception as e:
                    raise RuntimeError(f"Apache reload failed: {e}")

                # 2) Vhost Nginx FRONT (80/443) que hace proxy a Apache
                config_path = get_nginx_config_path(domain_name)
                with open(config_path, "w") as f:
                    f.write(generate_nginx_config(
                        domain_name, username, php_version,
                        ssl_enabled=False,
                        proxy_to_apache=True,
                    ))
                logger.info(f"Created Nginx front vhost (proxy→Apache): {config_path}")
                enabled_link = f"/etc/nginx/sites-enabled/{domain_name}"
                self.execute_command(["ln", "-sf", config_path, enabled_link])
                # Recarga con diagnóstico: si el configtest falla por un vhost
                # AJENO (huérfano de un borrado anterior), no culpamos a este.
                reload_nginx_or_diagnose(domain_name)

            else:  # nginx solo
                config_path = get_nginx_config_path(domain_name)
                config_content = generate_nginx_config(
                    domain_name,
                    username,
                    php_version,
                    ssl_enabled=False,
                    php_socket_override=php_socket,
                )

                with open(config_path, "w") as f:
                    f.write(config_content)
                logger.info(f"Created Nginx config: {config_path}")

                # Activar site (symlink a sites-enabled)
                enabled_link = f"/etc/nginx/sites-enabled/{domain_name}"
                self.execute_command(["ln", "-sf", config_path, enabled_link])

                # Test y reload Nginx (con diagnóstico de vhost ajeno/huérfano)
                reload_nginx_or_diagnose(domain_name)

            logger.info(f"Domain created: {domain_name}")
            return {
                "success": True,
                "domain": domain_name,
                "user": username,
                "php_version": php_version,
                "public_html": public_html,
                "logs_dir": logs_dir,
                "config_path": config_path
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

            # Eliminar el vhost Apache si existe (modo apache+nginx). El borrado
            # solo quitaba el de nginx; en modo Apache quedaba el .conf colgando
            # en sites-available + el symlink en sites-enabled.
            try:
                from scripts.webserver_config import get_apache_vhost_path
                apache_vhost = get_apache_vhost_path(domain_name)
                if self.file_exists(apache_vhost):
                    # a2dissite quita el symlink en sites-enabled
                    self.execute_command(["a2dissite", f"{domain_name}.conf"], check=False)
                    self.execute_command(["a2dissite", domain_name], check=False)
                    self.execute_command(["rm", "-f", apache_vhost])
                    logger.info(f"Removed Apache vhost: {apache_vhost}")
                    rc, _out, _err = self.execute_command(
                        ["apache2ctl", "configtest"], check=False)
                    if rc == 0:
                        self.execute_command(["systemctl", "reload", "apache2"], check=False)
            except Exception as apache_err:
                logger.warning(f"No se pudo eliminar el vhost Apache de {domain_name}: {apache_err}")

            # Eliminar el pool PHP-FPM dedicado del dominio (todas las versiones)
            try:
                from scripts import php_ini_manager as phpini
                phpini.remove_pool(domain_name)
            except Exception as pool_err:
                logger.warning(f"No se pudo eliminar el pool de {domain_name}: {pool_err}")

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

    def regenerate_vhost(
        self,
        username: str,
        domain_name: str,
        php_version: str,
        ssl_enabled: bool = False,
        ipv6: str = None,
        fastcgi_cache_enabled: bool = False,
        fastcgi_cache_ttl_minutes: int = 60,
        php_socket_override: str = None,
        template_nginx_extra: str = None,
        redirect_to: str = None,
        custom_docroot: str = None,
        ipv4: str = None,
        force_https: bool = False,
        hsts: bool = False,
        rate_limit_enabled: bool = False,
        rate_limit_rps: int = 10,
        rate_limit_burst: int = 20,
        docroot_subdir: str = None,
        readonly_mode_enabled: bool = False,
        allowed_mutation_ips: str = None,
        blocked_user_agents: list = None,
        security_headers_enabled: bool = False,
        http3_enabled: bool = False,
        webserver: str = None,
        custom_nginx_config: str = None,
        custom_apache_config: str = None,
        httpauth: dict = None,
        canonical_domain: str = "www",
        is_subdomain: bool = False,
    ) -> dict:
        """
        Regenera la vhost completa del dominio con TODO el estado actual
        (SSL, IPv6, cache, socket PHP dedicado, rate limit, docroot_subdir).
        Punto único de verdad para no perder ajustes al tocar una feature.

        Args:
            webserver: "nginx" o "apache". Si None, auto-detecta.
        """
        if not validate_domain(domain_name):
            raise ValueError(f"Invalid domain: {domain_name}")

        # Recuperar de la BD lo que el caller no haya indicado, en UNA consulta:
        #  - is_subdomain: los subdominios no llevan www. ni redirección canónica.
        #  - docroot_subdir: la subcarpeta de la plantilla (Laravel/Symfony
        #    'public'). Si se pierde, el dominio sirve desde la raíz y da 404.
        # Esto evita propagar ambos flags por TODOS los callers de regenerate_vhost.
        if not is_subdomain or docroot_subdir is None:
            try:
                from api.models.database import SessionLocal
                from api.models.models_domain import Domain as _D
                _db = SessionLocal()
                try:
                    _d = _db.query(_D).filter(_D.domain_name == domain_name).first()
                    if _d:
                        if not is_subdomain:
                            is_subdomain = bool(_d.is_subdomain)
                        if docroot_subdir is None:
                            docroot_subdir = getattr(_d, "docroot_subdir", None) or None
                finally:
                    _db.close()
            except Exception:
                pass

        # Auto-detectar webserver
        if webserver is None:
            from scripts.webserver_config import supports_apache
            if supports_apache():
                webserver = "apache"
            else:
                webserver = "nginx"

        if webserver == "apache":
            # ── Arquitectura dual: Nginx FRONT + Apache BACKEND ──
            # 1) Vhost Apache (127.0.0.1:8181): sirve PHP respetando .htaccess.
            # 2) Vhost Nginx (front 80/443): SSL/headers/bots + proxy_pass a Apache.
            # Así Apache aporta .htaccess y Nginx aporta todo lo moderno.
            from scripts.apache_vhost_generator import generate_apache_vhost
            from scripts.webserver_config import get_apache_vhost_path

            # 1) Apache backend
            apache_path = get_apache_vhost_path(domain_name)
            apache_content = generate_apache_vhost(
                domain_name,
                username,
                php_version,
                redirect_to=redirect_to,
                custom_docroot=custom_docroot,
                docroot_subdir=docroot_subdir,
                readonly_mode_enabled=readonly_mode_enabled,
                allowed_mutation_ips=allowed_mutation_ips,
                php_socket_override=php_socket_override,
                custom_apache_config=custom_apache_config,
                httpauth=httpauth,
            )
            with open(apache_path, "w") as f:
                f.write(apache_content)

            # Habilitar el sitio en Apache (symlink en sites-enabled) y recargar
            self.execute_command(["a2ensite", f"{domain_name}.conf"], check=False)
            rc, _, err = self.execute_command(["apache2ctl", "configtest"], check=False)
            if rc != 0:
                raise RuntimeError(f"Apache configtest falló: {err.strip()}")
            # Reload en background para no bloquear el panel (igual que nginx)
            import subprocess, threading, os as _os
            _env = _os.environ.copy()
            _env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
            threading.Thread(
                target=lambda: subprocess.run(
                    ["systemctl", "reload", "apache2"], capture_output=True, env=_env),
                daemon=True,
            ).start()

            # 2) Vhost Nginx front (proxy a Apache). Reutiliza TODA la lógica
            #    nginx (SSL, headers, bots, HTTP/3) con proxy_to_apache=True.
            config_path = get_nginx_config_path(domain_name)
            config_content = generate_nginx_config(
                domain_name, username, php_version,
                ssl_enabled=ssl_enabled, ipv6=ipv6,
                php_socket_override=php_socket_override,
                template_nginx_extra=template_nginx_extra,
                redirect_to=redirect_to, custom_docroot=custom_docroot,
                ipv4=ipv4, force_https=force_https, hsts=hsts,
                rate_limit_enabled=rate_limit_enabled, rate_limit_burst=rate_limit_burst,
                docroot_subdir=docroot_subdir,
                readonly_mode_enabled=readonly_mode_enabled,
                allowed_mutation_ips=allowed_mutation_ips,
                blocked_user_agents=blocked_user_agents or [],
                security_headers_enabled=security_headers_enabled,
                http3_enabled=http3_enabled,
                proxy_to_apache=True,
                custom_nginx_config=custom_nginx_config,
                httpauth=httpauth,
                canonical_domain=canonical_domain,
                is_subdomain=is_subdomain,
            )
            with open(config_path, "w") as f:
                f.write(config_content)
            # Asegurar que el vhost nginx FRONT está activo (symlink en
            # sites-enabled). Sin esto, nginx no carga el vhost del dominio y
            # sirve la página/cert por defecto del panel.
            enabled_link = f"/etc/nginx/sites-enabled/{domain_name}"
            self.execute_command(["ln", "-sf", config_path, enabled_link])
            if not reload_nginx():
                raise RuntimeError("Nginx reload failed tras regenerar vhost (modo apache)")

        else:  # nginx
            if fastcgi_cache_enabled:
                write_fastcgi_cache_zone(domain_name)
            else:
                remove_fastcgi_cache_zone(domain_name)

            # Zona de rate limit (nivel http) debe existir antes que el vhost
            if rate_limit_enabled:
                write_ratelimit_zone(domain_name, rate_limit_rps)
            else:
                remove_ratelimit_zone(domain_name)

            config_path = get_nginx_config_path(domain_name)
            config_content = generate_nginx_config(
                domain_name,
                username,
                php_version,
                ssl_enabled=ssl_enabled,
                ipv6=ipv6,
                fastcgi_cache_enabled=fastcgi_cache_enabled,
                fastcgi_cache_ttl_minutes=fastcgi_cache_ttl_minutes,
                php_socket_override=php_socket_override,
                template_nginx_extra=template_nginx_extra,
                redirect_to=redirect_to,
                custom_docroot=custom_docroot,
                ipv4=ipv4,
                force_https=force_https,
                hsts=hsts,
                rate_limit_enabled=rate_limit_enabled,
                rate_limit_burst=rate_limit_burst,
                docroot_subdir=docroot_subdir,
                readonly_mode_enabled=readonly_mode_enabled,
                allowed_mutation_ips=allowed_mutation_ips,
                blocked_user_agents=blocked_user_agents or [],
                security_headers_enabled=security_headers_enabled,
                http3_enabled=http3_enabled,
                custom_nginx_config=custom_nginx_config,
                httpauth=httpauth,
                canonical_domain=canonical_domain,
                is_subdomain=is_subdomain,
            )
            with open(config_path, "w") as f:
                f.write(config_content)

            if not reload_nginx():
                raise RuntimeError("Nginx reload failed tras regenerar vhost")

        return {"success": True, "domain": domain_name}

    # ── Protección con contraseña (.htpasswd) ──────────────────────────────────
    def htpasswd_path(self, username: str, domain_name: str) -> str:
        """Ruta del .htpasswd del dominio (fuera del docroot público)."""
        return f"/home/{username}/web/{domain_name}/.htpasswd"

    def write_htpasswd(self, username: str, domain_name: str,
                       auth_user: str, password: str) -> str:
        """Crea/actualiza el .htpasswd con un usuario. Devuelve el hash apr1.

        Usa `openssl passwd -apr1 -stdin` (la contraseña va por stdin, no por la
        línea de comandos → no visible en `ps`).
        """
        rc, out, err = self.execute_with_input(
            ["openssl", "passwd", "-apr1", "-stdin"], password + "\n", check=False)
        if rc != 0 or not out.strip():
            raise RuntimeError(f"No pude generar el hash de contraseña: {err}")
        pass_hash = out.strip()
        path = self.htpasswd_path(username, domain_name)
        with open(path, "w") as f:
            f.write(f"{auth_user}:{pass_hash}\n")
        # 640 y owner www-data:{user}: el webserver (www-data) lo lee, el usuario
        # del dominio no puede modificarlo a su antojo, y no es servible por HTTP.
        self.execute_command(["chown", f"www-data:{username}", path], check=False)
        self.execute_command(["chmod", "640", path], check=False)
        return pass_hash

    def write_htpasswd_hash(self, username: str, domain_name: str,
                            auth_user: str, pass_hash: str) -> None:
        """Reescribe el .htpasswd con un hash ya existente (sin regenerarlo)."""
        path = self.htpasswd_path(username, domain_name)
        with open(path, "w") as f:
            f.write(f"{auth_user}:{pass_hash}\n")
        self.execute_command(["chown", f"www-data:{username}", path], check=False)
        self.execute_command(["chmod", "640", path], check=False)

    def remove_htpasswd(self, username: str, domain_name: str) -> None:
        path = self.htpasswd_path(username, domain_name)
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    def set_fastcgi_cache(
        self,
        username: str,
        domain_name: str,
        php_version: str,
        enabled: bool,
        ttl_minutes: int = 60,
        ssl_enabled: bool = False,
        ipv6: str = None,
        php_socket_override: str = None,
        ipv4: str = None,
        force_https: bool = False,
        hsts: bool = False,
        rate_limit_enabled: bool = False,
        rate_limit_rps: int = 10,
        rate_limit_burst: int = 20,
        security_headers_enabled: bool = False,
        http3_enabled: bool = False,
        canonical_domain: str = "www",
    ) -> dict:
        """Activa o desactiva FastCGI cache. Delega en regenerate_vhost."""
        try:
            self.regenerate_vhost(
                username, domain_name, php_version,
                ssl_enabled=ssl_enabled, ipv6=ipv6,
                fastcgi_cache_enabled=enabled,
                fastcgi_cache_ttl_minutes=ttl_minutes,
                php_socket_override=php_socket_override,
                ipv4=ipv4,
                force_https=force_https,
                hsts=hsts,
                rate_limit_enabled=rate_limit_enabled,
                rate_limit_rps=rate_limit_rps,
                rate_limit_burst=rate_limit_burst,
                security_headers_enabled=security_headers_enabled,
                http3_enabled=http3_enabled,
                canonical_domain=canonical_domain,
            )
            logger.info(f"FastCGI cache {'enabled' if enabled else 'disabled'} para {domain_name}")
            return {
                "success": True, "domain": domain_name,
                "fastcgi_cache_enabled": enabled, "ttl_minutes": ttl_minutes,
            }
        except Exception as e:
            logger.error(f"Failed to set FastCGI cache for {domain_name}: {e}")
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
