"""Utility functions for system management"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def validate_username(username: str) -> bool:
    """Validate Linux username format"""
    # Usernames must start with letter/underscore, contain only alphanumeric and underscore
    pattern = r'^[a-zA-Z_][a-zA-Z0-9_-]{2,31}$'
    return bool(re.match(pattern, username))


def validate_domain(domain: str) -> bool:
    """Validate domain name format"""
    pattern = r'^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$'
    return bool(re.match(pattern, domain.lower()))


def validate_ipv6(ipv6: str) -> bool:
    """Validate IPv6 address format"""
    import ipaddress
    try:
        ipaddress.IPv6Address(ipv6)
        return True
    except ValueError:
        return False


def validate_email(email: str) -> bool:
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def get_home_directory(username: str) -> str:
    """Get home directory for a user — /home/username"""
    return f"/home/{username}"


def get_web_root(username: str) -> str:
    """Get web root for a user — /home/username/web"""
    return f"/home/{username}/web"


def get_domain_root(username: str, domain: str) -> str:
    """Get domain root directory — /home/username/web/domain.com"""
    return f"/home/{username}/web/{domain}"


def get_public_html(username: str, domain: str) -> str:
    """Get public_html path — /home/username/web/domain.com/public_html"""
    return f"/home/{username}/web/{domain}/public_html"


def get_domain_logs(username: str, domain: str) -> str:
    """Get domain logs directory — /home/username/web/domain.com/logs"""
    return f"/home/{username}/web/{domain}/logs"


def get_domain_private(username: str, domain: str) -> str:
    """Get domain private directory — /home/username/web/domain.com/private"""
    return f"/home/{username}/web/{domain}/private"


def get_nginx_config_path(domain: str) -> str:
    """Get nginx config file path"""
    return f"/etc/nginx/sites-available/{domain}"


def generate_nginx_config(
    domain: str,
    user: str,
    php_version: str,
    ssl_enabled: bool = False,
    ipv6: Optional[str] = None
) -> str:
    """Generate Nginx vhost configuration (Hestia-style paths)"""

    public_html = get_public_html(user, domain)
    logs_dir = get_domain_logs(user, domain)
    php_socket = f"/run/php/php{php_version}-fpm.sock"
    backend_name = domain.replace('.', '_').replace('-', '_')

    # server_name incluye IPv6 cuando está asignada (para acceso por IP directa)
    server_names = f"{domain} www.{domain}"
    if ipv6:
        server_names += f" {ipv6}"   # nginx acepta IPv6 sin corchetes en server_name

    server_block = f"""upstream php_{backend_name} {{
    server unix:{php_socket};
}}

server {{
    listen 80;
    {"listen [::]:" + "80;" if not ipv6 else "listen [" + ipv6 + "]:80 default_server;"}
    server_name {server_names};
    root {public_html};

    index index.php index.html index.htm;

    location / {{
        try_files $uri $uri/ /index.php?$query_string;
    }}

    location ~ \\.php$ {{
        try_files $uri =404;
        fastcgi_pass php_{backend_name};
        fastcgi_index index.php;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        include fastcgi_params;
    }}

    location ~ /\\.ht {{
        deny all;
    }}

    location ~ /\\.well-known {{
        allow all;
    }}

    error_log {logs_dir}/nginx.error.log;
    access_log {logs_dir}/nginx.access.log;
}}
"""

    if ssl_enabled:
        server_block += f"""
server {{
    listen 443 ssl http2;
    {"listen [::]:" + "443 ssl http2;" if not ipv6 else "listen [" + ipv6 + "]:443 ssl http2 default_server;"}
    server_name {server_names};
    root {public_html};

    ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    index index.php index.html index.htm;

    location / {{
        try_files $uri $uri/ /index.php?$query_string;
    }}

    location ~ \\.php$ {{
        try_files $uri =404;
        fastcgi_pass php_{backend_name};
        fastcgi_index index.php;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        include fastcgi_params;
    }}

    location ~ /\\.ht {{
        deny all;
    }}

    error_log {logs_dir}/nginx.error.log;
    access_log {logs_dir}/nginx.access.log;
}}
"""

    return server_block


def reload_nginx() -> bool:
    """Test and reload nginx configuration"""
    import subprocess
    import os

    env = os.environ.copy()
    env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

    try:
        subprocess.run(["nginx", "-t"], check=True, capture_output=True, env=env)
        subprocess.run(["systemctl", "reload", "nginx"], check=True, capture_output=True, env=env)
        logger.info("Nginx reloaded successfully")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to reload nginx: {e.stderr}")
        return False
