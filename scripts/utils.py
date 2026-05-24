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
    """Get home directory for a user"""
    return f"/home/{username}"


def get_public_html(username: str, domain: str) -> str:
    """Get public_html path for a domain"""
    return f"/home/{username}/public_html/{domain}"


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
    """Generate Nginx vhost configuration"""

    public_html = get_public_html(user, domain)
    php_socket = f"/run/php/php{php_version}-fpm.sock"

    # Server blocks
    server_block = f"""
upstream php_backend_{domain.replace('.', '_')} {{
    server unix:{php_socket};
}}

server {{
    listen 80;
    {"listen [" + ipv6 + "]:80;" if ipv6 else ""}
    server_name {domain} www.{domain};
    root {public_html};

    index index.php index.html;

    location ~ \\.php$ {{
        try_files $uri =404;
        fastcgi_pass php_backend_{domain.replace('.', '_')};
        fastcgi_index index.php;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        include fastcgi_params;
    }}

    location ~ /\\.ht {{
        deny all;
    }}

    error_log /var/log/nginx/{domain}_error.log;
    access_log /var/log/nginx/{domain}_access.log;
}}
"""

    if ssl_enabled:
        server_block += f"""
server {{
    listen 443 ssl http2;
    {"listen [" + ipv6 + "]:443 ssl http2;" if ipv6 else ""}
    server_name {domain} www.{domain};
    root {public_html};

    ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;

    index index.php index.html;

    location ~ \\.php$ {{
        try_files $uri =404;
        fastcgi_pass php_backend_{domain.replace('.', '_')};
        fastcgi_index index.php;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        include fastcgi_params;
    }}

    location ~ /\\.ht {{
        deny all;
    }}

    error_log /var/log/nginx/{domain}_error.log;
    access_log /var/log/nginx/{domain}_access.log;
}}
"""

    return server_block


def reload_nginx() -> bool:
    """Test and reload nginx configuration"""
    import subprocess
    try:
        subprocess.run(["nginx", "-t"], check=True, capture_output=True)
        subprocess.run(["systemctl", "reload", "nginx"], check=True, capture_output=True)
        logger.info("Nginx reloaded successfully")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to reload nginx: {e.stderr}")
        return False
