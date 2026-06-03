"""
Apache vhost generator — paralelo a generate_nginx_config()
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def generate_apache_vhost(
    domain_name: str,
    username: str,
    php_version: str = "8.2",
    ssl_enabled: bool = False,
    ipv6: Optional[str] = None,
    ipv4: Optional[str] = None,
    force_https: bool = False,
    hsts: bool = False,
    redirect_to: Optional[str] = None,
    custom_docroot: Optional[str] = None,
    docroot_subdir: Optional[str] = None,
    blocked_user_agents: Optional[list] = None,
    readonly_mode_enabled: bool = False,
    allowed_mutation_ips: Optional[str] = None,
) -> str:
    """
    Genera un vhost Apache2 para un dominio.

    Args:
        domain_name: Nombre del dominio (ej: example.com)
        username: Usuario propietario del dominio
        php_version: Versión PHP (7.4, 8.0, 8.1, 8.2, 8.3, 8.4, 8.5)
        ssl_enabled: Si SSL está activo
        ipv6: IPv6 opcional a bindar
        ipv4: IPv4 opcional a bindar
        force_https: Redirigir HTTP a HTTPS
        hsts: Habilitar HSTS
        redirect_to: Redirigir a otra URL
        custom_docroot: Docroot personalizado (default: public_html)
        docroot_subdir: Subdir dentro de public_html (ej: "app/public")
        blocked_user_agents: Lista de user-agents a bloquear
        readonly_mode_enabled: Desactivar PUT/DELETE/POST
        allowed_mutation_ips: IPs que pueden hacer mutaciones en modo readonly

    Returns:
        Contenido del vhost Apache
    """
    from scripts.utils import (
        get_public_html,
        get_domain_logs,
    )

    blocked_user_agents = blocked_user_agents or []

    # Docroot
    if custom_docroot:
        docroot = custom_docroot
    else:
        public_html = get_public_html(username, domain_name)
        if docroot_subdir:
            docroot = f"{public_html}/{docroot_subdir.lstrip('/')}"
        else:
            docroot = public_html

    logs_dir = get_domain_logs(username, domain_name)
    access_log = f"{logs_dir}/apache.access.log"
    error_log = f"{logs_dir}/apache.error.log"

    # Bind addresses
    listen_http = "*:80"
    listen_https = "*:443"
    if ipv4:
        listen_http = f"{ipv4}:80"
        listen_https = f"{ipv4}:443"
    if ipv6:
        listen_http = f"[{ipv6}]:80"
        listen_https = f"[{ipv6}]:443"

    server_names = f"{domain_name} www.{domain_name}"
    if ipv6:
        server_names += f" [{ipv6}]"

    # ─────────────────────────────────────────────────────────────────────────
    # VHost HTTP (redirect a HTTPS si fuerza_https)
    # ─────────────────────────────────────────────────────────────────────────

    if redirect_to:
        # Modo redirección: HTTP y HTTPS redirigen a redirect_to
        vhost_http = f"""<VirtualHost {listen_http}>
    ServerName {domain_name}
    ServerAlias www.{domain_name}

    ErrorLog {error_log}
    CustomLog {access_log} combined

    # Redirigir a {redirect_to}
    RewriteEngine On
    RewriteRule ^(.*)$ {redirect_to}$1 [R=301,L]
</VirtualHost>
"""
        if ssl_enabled:
            vhost_https = f"""<VirtualHost {listen_https}>
    ServerName {domain_name}
    ServerAlias www.{domain_name}

    SSLEngine On
    SSLCertificateFile /etc/letsencrypt/live/{domain_name}/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/{domain_name}/privkey.pem
    SSLProtocol TLSv1.2 TLSv1.3
    SSLCipherSuite HIGH:!aNULL:!MD5

    ErrorLog {error_log}
    CustomLog {access_log} combined

    # Redirigir a {redirect_to}
    RewriteEngine On
    RewriteRule ^(.*)$ {redirect_to}$1 [R=301,L]
</VirtualHost>
"""
        else:
            vhost_https = ""

    else:
        # Modo normal: servir contenido
        vhost_http = f"""<VirtualHost {listen_http}>
    ServerName {domain_name}
    ServerAlias www.{domain_name}
    DocumentRoot {docroot}

    ErrorLog {error_log}
    CustomLog {access_log} combined

"""

        # Headers de seguridad HTTP (aplica a HTTP si no fuerza HTTPS)
        security_headers = _generate_apache_security_headers(hsts=False)
        vhost_http += security_headers

        # Bad bots blocker (Apache)
        if blocked_user_agents:
            bots_block = _generate_apache_bots_block(blocked_user_agents)
            vhost_http += bots_block

        # PHP-FPM (socket)
        php_socket = f"/run/php/php{php_version}-fpm-svqpanel-{domain_name}.sock"
        vhost_http += f"""
    <FilesMatch "\\.php$">
        SetHandler "proxy:unix:{php_socket}|fcgi://localhost"
    </FilesMatch>

    <Directory {docroot}>
        Options -Indexes +FollowSymLinks
        AllowOverride All
        Require all granted
    </Directory>
"""

        # Readonly mode
        if readonly_mode_enabled:
            vhost_http += _generate_apache_readonly_block(allowed_mutation_ips)

        # Force HTTPS
        if force_https:
            vhost_http += f"""
    RewriteEngine On
    RewriteCond %{{HTTPS}} !=on
    RewriteRule ^(.*)$ https://{{{{HTTP_HOST}}}}$1 [R=301,L]
"""

        vhost_http += """
</VirtualHost>
"""

        # ─────────────────────────────────────────────────────────────────────────
        # VHost HTTPS
        # ─────────────────────────────────────────────────────────────────────────

        if ssl_enabled:
            vhost_https = f"""<VirtualHost {listen_https}>
    ServerName {domain_name}
    ServerAlias www.{domain_name}
    DocumentRoot {docroot}

    SSLEngine On
    SSLCertificateFile /etc/letsencrypt/live/{domain_name}/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/{domain_name}/privkey.pem
    SSLProtocol TLSv1.2 TLSv1.3
    SSLCipherSuite HIGH:!aNULL:!MD5

    ErrorLog {error_log}
    CustomLog {access_log} combined

"""
            # Headers de seguridad (HTTPS con HSTS)
            security_headers = _generate_apache_security_headers(hsts=hsts)
            vhost_https += security_headers

            # Bad bots blocker
            if blocked_user_agents:
                bots_block = _generate_apache_bots_block(blocked_user_agents)
                vhost_https += bots_block

            # PHP-FPM (socket)
            vhost_https += f"""
    <FilesMatch "\\.php$">
        SetHandler "proxy:unix:{php_socket}|fcgi://localhost"
    </FilesMatch>

    <Directory {docroot}>
        Options -Indexes +FollowSymLinks
        AllowOverride All
        Require all granted
    </Directory>
"""

            # Readonly mode
            if readonly_mode_enabled:
                vhost_https += _generate_apache_readonly_block(allowed_mutation_ips)

            vhost_https += """
</VirtualHost>
"""
        else:
            vhost_https = ""

    # Combinar
    result = vhost_http
    if vhost_https:
        result += "\n" + vhost_https

    return result


def _generate_apache_security_headers(hsts: bool = False) -> str:
    """Genera directivas Apache para headers HTTP de seguridad."""
    headers = """    # Security Headers (SVQPanel)
    Header always set X-Frame-Options "SAMEORIGIN"
    Header always set X-Content-Type-Options "nosniff"
    Header always set X-XSS-Protection "1; mode=block"
    Header always set Referrer-Policy "strict-origin-when-cross-origin"
    Header always set Permissions-Policy "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()"
"""
    if hsts:
        headers += '    Header always set Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"\n'

    return headers


def _generate_apache_bots_block(blocked_user_agents: list) -> str:
    """Genera bloque Apache para bloquear user-agents."""
    if not blocked_user_agents:
        return ""

    block = """
    # Bad Bots Blocker (SVQPanel)
    RewriteEngine On
"""
    for pattern in blocked_user_agents:
        # Escapar caracteres especiales para RewriteCond
        safe_pattern = pattern.replace('"', '\\"')
        block += f"""    RewriteCond %{{HTTP_USER_AGENT}} {safe_pattern} [NC]
"""

    block += """    RewriteRule ^(.*)$ - [F,L]

"""
    return block


def _generate_apache_readonly_block(allowed_mutation_ips: Optional[str] = None) -> str:
    """Genera bloque Apache para modo readonly (bloquea PUT/DELETE/POST)."""
    block = """
    # Readonly Mode (SVQPanel) — bloquea PUT, DELETE, POST
    RewriteEngine On
    RewriteCond %{REQUEST_METHOD} ^(PUT|DELETE|POST)$ [NC]
"""

    if allowed_mutation_ips:
        # allowed_mutation_ips es una cadena "ip1, ip2, ..."
        for ip in allowed_mutation_ips.split(","):
            ip = ip.strip()
            block += f"    RewriteCond %{{REMOTE_ADDR}} !^{ip}$ [NC]\n"

    block += """    RewriteRule ^(.*)$ - [F,L]

"""
    return block
