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


# ─────────────────────────────────────────────────────────────────────────────
# FastCGI cache (Fase 14)
# ─────────────────────────────────────────────────────────────────────────────
FASTCGI_CACHE_ROOT = "/var/cache/nginx/fastcgi"
FASTCGI_CACHE_GLOBAL_CONF = "/etc/nginx/conf.d/svqpanel-fastcgi-cache-global.conf"
FASTCGI_CACHE_GLOBAL_CONTENT = '''# SVQPanel — directivas FastCGI cache compartidas (nivel http)
# fastcgi_cache_key debe declararse UNA sola vez en todo nginx; aquí lo
# centralizamos. Las zonas (keys_zone) las define cada dominio en su
# propio fichero svqpanel-cache-{domain}.conf.
fastcgi_cache_key "$scheme$request_method$host$request_uri";
'''

# Rate limiting (anti-abuso). Una zona por dominio (igual que la caché), con
# su propio 'rate' (peticiones/seg por IP) y 'burst' (ráfaga tolerada). nginx
# fija el rate en la zona (nivel http) y lo aplica con limit_req en el location.
RATELIMIT_GLOBAL_CONF = "/etc/nginx/conf.d/svqpanel-ratelimit-global.conf"
RATELIMIT_GLOBAL_CONTENT = '''# SVQPanel — rate limiting (nivel http)
# Las zonas (limit_req_zone) las define cada dominio en su propio fichero
# svqpanel-ratelimit-{domain}.conf. Aquí solo el código de respuesta.
limit_req_status 429;
'''


def get_ratelimit_conf_path(domain: str) -> str:
    """Ruta del fichero conf con la zona de rate limit del dominio."""
    return f"/etc/nginx/conf.d/svqpanel-ratelimit-{domain}.conf"


def _ratelimit_zone_name(domain: str) -> str:
    """Nombre de zona único por dominio (alfanumérico)."""
    return "svqrl_" + domain.replace('.', '_').replace('-', '_')


def ensure_ratelimit_global() -> None:
    """Crea el conf global (limit_req_status). Idempotente."""
    import os
    if not os.path.isfile(RATELIMIT_GLOBAL_CONF):
        with open(RATELIMIT_GLOBAL_CONF, "w") as f:
            f.write(RATELIMIT_GLOBAL_CONTENT)


def write_ratelimit_zone(domain: str, rps: int) -> str:
    """
    Escribe /etc/nginx/conf.d/svqpanel-ratelimit-{domain}.conf con la zona
    limit_req_zone del dominio (rate = rps peticiones/seg por IP).
    """
    ensure_ratelimit_global()
    zone = _ratelimit_zone_name(domain)
    path = get_ratelimit_conf_path(domain)
    content = (
        f"# SVQPanel — rate limit de {domain}\n"
        f"limit_req_zone $binary_remote_addr zone={zone}:10m rate={rps}r/s;\n"
    )
    with open(path, "w") as f:
        f.write(content)
    return path


def remove_ratelimit_zone(domain: str) -> None:
    """Borra el fichero de zona de rate limit de un dominio."""
    import os
    path = get_ratelimit_conf_path(domain)
    if os.path.isfile(path):
        os.remove(path)


def _ratelimit_directive(domain: str, burst: int) -> str:
    """Línea limit_req para inyectar en el location del dominio."""
    zone = _ratelimit_zone_name(domain)
    return f"\n        limit_req zone={zone} burst={burst} nodelay;"


def get_fastcgi_cache_conf_path(domain: str) -> str:
    """Ruta del fichero conf en /etc/nginx/conf.d/ con la zona de cache del dominio."""
    return f"/etc/nginx/conf.d/svqpanel-cache-{domain}.conf"


def get_fastcgi_cache_dir(domain: str) -> str:
    """Directorio donde nginx guarda los ficheros cacheados de un dominio."""
    return f"{FASTCGI_CACHE_ROOT}/{domain}"


def fastcgi_cache_zone_name(domain: str) -> str:
    """Nombre de la keys_zone nginx (alfanumérico). Limita a 32 chars."""
    safe = domain.replace('.', '_').replace('-', '_')[:24]
    return f"SVQ_{safe}"


def generate_fastcgi_cache_zone_conf(domain: str) -> str:
    """
    Devuelve el contenido del fichero /etc/nginx/conf.d/svqpanel-cache-{domain}.conf.
    Define la zona de cache (keys_zone) que se referencia desde la vhost.
    """
    cache_dir = get_fastcgi_cache_dir(domain)
    zone = fastcgi_cache_zone_name(domain)
    return f"""# SVQPanel — FastCGI cache zone para {domain}
fastcgi_cache_path {cache_dir}
    levels=1:2
    keys_zone={zone}:10m
    max_size=500m
    inactive=1h
    use_temp_path=off;
"""


def _fastcgi_cache_block(domain: str, ttl_minutes: int) -> str:
    """
    Devuelve el snippet que se inserta DENTRO del 'location ~ \\.php$' cuando
    la cache está habilitada para este dominio.
    Bypass automático para WordPress/WooCommerce admin/logueados/POST.
    """
    zone = fastcgi_cache_zone_name(domain)
    return f"""
        # ── FastCGI cache (SVQPanel) ─────────────────────────────────────
        fastcgi_cache_bypass $skip_cache;
        fastcgi_no_cache     $skip_cache;
        fastcgi_cache        {zone};
        fastcgi_cache_valid  200 301 302 {ttl_minutes}m;
        fastcgi_cache_valid  404 1m;
        fastcgi_cache_use_stale error timeout invalid_header updating http_500 http_503;
        fastcgi_cache_lock   on;
        add_header X-Cache-Status $upstream_cache_status always;
"""


def _skip_cache_block() -> str:
    """Variable $skip_cache compartida por http/https — se evalúa a nivel server."""
    return """
    # ── $skip_cache: bypass de FastCGI cache para admin/POST/logueados ─
    set $skip_cache 0;
    if ($request_method = POST)              { set $skip_cache 1; }
    if ($query_string != "")                 { set $skip_cache 1; }
    if ($request_uri ~* "/wp-admin/|/xmlrpc.php|wp-.*\\.php|/feed/|/sitemap(_index)?\\.xml") { set $skip_cache 1; }
    if ($http_cookie ~* "comment_author|wordpress_[a-f0-9]+|wp-postpass|wordpress_no_cache|wordpress_logged_in|woocommerce_items_in_cart|woocommerce_cart_hash|wp_woocommerce_session") {
        set $skip_cache 1;
    }
"""


def _generate_redirect_config(
    domain: str,
    redirect_to: str,
    ssl_enabled: bool = False,
    ipv6: Optional[str] = None,
    ipv4: Optional[str] = None,
) -> str:
    """Genera un vhost nginx que redirige permanentemente (301) a redirect_to."""
    server_names = f"{domain} www.{domain}"
    if ipv6:
        server_names += f" {ipv6}"

    ipv4_listen_http  = f"{ipv4}:80" if ipv4 else "80"
    ipv4_listen_https = f"{ipv4}:443" if ipv4 else "443"
    ipv6_listen_http  = f"listen [{ipv6}]:80 default_server;" if ipv6 else "listen [::]:80;"
    ipv6_listen_https = f"listen [{ipv6}]:443 ssl default_server;" if ipv6 else "listen [::]:443 ssl;"

    # Asegurarse de que redirect_to no termina en /
    destination = redirect_to.rstrip("/")

    config = f"""server {{
    listen {ipv4_listen_http};
    {ipv6_listen_http}
    server_name {server_names};

    return 301 {destination}$request_uri;
}}
"""
    if ssl_enabled:
        config += f"""
server {{
    listen {ipv4_listen_https} ssl http2;
    {ipv6_listen_https}
    server_name {server_names};

    ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    return 301 {destination}$request_uri;
}}
"""
    return config


def _readonly_mode_block(allowed_ips_json: Optional[str]) -> str:
    """
    Genera el bloque nginx limit_except que bloquea POST/PUT/DELETE/PATCH
    excepto desde las IPs indicadas (JSON array de IPs o CIDRs).
    Si allowed_ips_json es None o vacío, bloquea a TODOS.
    """
    import json
    lines = ["    limit_except GET HEAD OPTIONS {"]
    ips = []
    if allowed_ips_json:
        try:
            ips = json.loads(allowed_ips_json)
        except Exception:
            ips = []
    for ip in ips:
        lines.append(f"        allow {ip};")
    lines.append("        deny all;")
    lines.append("    }")
    return "\n".join(lines) + "\n"


def generate_nginx_config(
    domain: str,
    user: str,
    php_version: str,
    ssl_enabled: bool = False,
    ipv6: Optional[str] = None,
    fastcgi_cache_enabled: bool = False,
    fastcgi_cache_ttl_minutes: int = 60,
    php_socket_override: Optional[str] = None,
    template_nginx_extra: Optional[str] = None,
    redirect_to: Optional[str] = None,
    custom_docroot: Optional[str] = None,
    ipv4: Optional[str] = None,
    force_https: bool = False,
    hsts: bool = False,
    rate_limit_enabled: bool = False,
    rate_limit_burst: int = 20,
    docroot_subdir: Optional[str] = None,
    readonly_mode_enabled: bool = False,
    allowed_mutation_ips: Optional[str] = None,
    blocked_user_agents: Optional[list] = None,
    security_headers_enabled: bool = False,
    http3_enabled: bool = False,
) -> str:
    """Generate Nginx vhost configuration (Hestia-style paths)"""

    # Si hay redirección activa, generar vhost mínimo de 301
    if redirect_to:
        return _generate_redirect_config(domain, redirect_to, ssl_enabled, ipv6, ipv4)

    # Directiva de rate limit a inyectar en location / (vacío si desactivado)
    rl_directive = _ratelimit_directive(domain, rate_limit_burst) if rate_limit_enabled else ""

    # Docroot: personalizado o el estándar
    public_html = custom_docroot or get_public_html(user, domain)
    # docroot_subdir (p.ej. 'public' en Laravel): la app sirve desde una
    # subcarpeta del docroot. Lo aporta la plantilla; no toca el custom_docroot.
    if docroot_subdir:
        safe_sub = docroot_subdir.strip("/").replace("..", "")
        if safe_sub:
            public_html = f"{public_html.rstrip('/')}/{safe_sub}"
    logs_dir = get_domain_logs(user, domain)
    # Si el dominio tiene php.ini propio, usa su pool dedicado
    php_socket = php_socket_override or f"/run/php/php{php_version}-fpm.sock"
    backend_name = domain.replace('.', '_').replace('-', '_')

    skip_block  = _skip_cache_block() if fastcgi_cache_enabled else ""
    cache_block = _fastcgi_cache_block(domain, fastcgi_cache_ttl_minutes) if fastcgi_cache_enabled else ""
    readonly_block = _readonly_mode_block(allowed_mutation_ips) if readonly_mode_enabled else ""

    # Bloque de bloqueo de user-agents por dominio
    bots_block = ""
    if blocked_user_agents:
        lines = []
        for pattern in blocked_user_agents:
            pattern = pattern.strip()
            if pattern:
                safe = pattern.replace('"', '\\"').replace("'", "\\'")
                lines.append(f'    if ($http_user_agent ~* "{safe}") {{ return 444; }}')
        if lines:
            bots_block = "\n" + "\n".join(lines) + "\n"

    # server_name incluye IPv6 cuando está asignada (para acceso por IP directa)
    server_names = f"{domain} www.{domain}"
    if ipv6:
        server_names += f" {ipv6}"   # nginx acepta IPv6 sin corchetes en server_name

    tpl_extra = ("\n" + template_nginx_extra.rstrip()) if template_nginx_extra else ""


    ipv4_listen_http  = f"{ipv4}:80" if ipv4 else "80"
    ipv4_listen_https = f"{ipv4}:443" if ipv4 else "443"
    ipv6_listen_http  = f"listen [{ipv6}]:80 default_server;" if ipv6 else "listen [::]:80;"
    ipv6_listen_https = f"listen [{ipv6}]:443 ssl default_server;" if ipv6 else "listen [::]:443 ssl;"

    hsts_header = (
        '    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;'
        if (hsts and ssl_enabled) else ""
    )

    # HTTP/3 (QUIC) — requiere nginx 1.25+ con http_v3_module
    # Añade listen quic en puerto 443 y el header Alt-Svc para anunciar HTTP/3
    http3_listen = ""
    http3_header = ""
    if http3_enabled and ssl_enabled:
        http3_listen = f"\n    listen {ipv4 + ':' if ipv4 else ''}443 quic reuseport;"
        if ipv6:
            http3_listen += f"\n    listen [{ipv6}]:443 quic reuseport;"
        http3_header = '\n    add_header Alt-Svc \'h3=":443"; ma=86400\' always;'

    # Headers de seguridad HTTP (sin CSP para no romper contenido de clientes)
    sec_headers_http = ""
    sec_headers_https = ""
    if security_headers_enabled:
        _sh = """\
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()" always;
    add_header X-XSS-Protection "1; mode=block" always;"""
        sec_headers_http = "\n" + _sh
        sec_headers_https = "\n" + _sh

    # Si force_https: el bloque HTTP solo redirige a HTTPS
    if force_https and ssl_enabled:
        http_block = f"""server {{
    listen {ipv4_listen_http};
    {ipv6_listen_http}
    server_name {server_names};
    return 301 https://$server_name$request_uri;
}}
"""
    else:
        http_block = None  # se construye abajo

    server_block = f"""upstream php_{backend_name} {{
    server unix:{php_socket};
}}
"""

    if http_block:
        server_block += http_block
    else:
        server_block += f"""server {{
    listen {ipv4_listen_http};
    {ipv6_listen_http}
    server_name {server_names};
    root {public_html};
{sec_headers_http}
    index index.php index.html index.htm;
{skip_block}
    # Pasamos el upstream al template via variable para que los location blocks
    # de la plantilla puedan usar $phpfpm_backend en lugar del nombre hardcodeado
    set $phpfpm_backend php_{backend_name};
{tpl_extra}{bots_block}
    location / {{{rl_directive}
{readonly_block}        try_files $uri $uri/ /index.php?$query_string;
    }}

    location ~ \\.php$ {{
        try_files $uri =404;
        fastcgi_pass php_{backend_name};
        fastcgi_index index.php;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        include fastcgi_params;{cache_block}
    }}

    location ~ /\\.ht {{
        deny all;
    }}

    # .well-known SIEMPRE permitido (certbot/ACME, autodiscover) — va antes de
    # los deny de ficheros ocultos para no bloquear la validación de SSL.
    location ~ /\\.well-known {{
        allow all;
    }}

    # Bloquear ficheros sensibles (credenciales, VCS, dumps y backups).
    location ~ /\\.(?:env|git|svn|hg|bzr)(?:/|$) {{
        deny all;
    }}
    location ~* \\.(?:sql|bak|old|orig|save|swp|swo|log|sh)$ {{
        deny all;
    }}
    location ~ ~$ {{
        deny all;
    }}
    location = /composer.json {{ deny all; }}
    location = /composer.lock {{ deny all; }}
    location = /package.json {{ deny all; }}
    location = /.user.ini {{ deny all; }}
    location = /wp-config.php.bak {{ deny all; }}

    error_log {logs_dir}/nginx.error.log;
    access_log {logs_dir}/nginx.access.log;
}}
"""

    if ssl_enabled:
        server_block += f"""
server {{
    listen {ipv4_listen_https} ssl;
    http2 on;
    {ipv6_listen_https}{http3_listen}
    server_name {server_names};
    root {public_html};

    ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
{hsts_header}{http3_header}{sec_headers_https}

    index index.php index.html index.htm;
{skip_block}    set $phpfpm_backend php_{backend_name};
{tpl_extra}{bots_block}    location / {{{rl_directive}
{readonly_block}        try_files $uri $uri/ /index.php?$query_string;
    }}

    location ~ \\.php$ {{
        try_files $uri =404;
        fastcgi_pass php_{backend_name};
        fastcgi_index index.php;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        include fastcgi_params;{cache_block}
    }}

    location ~ /\\.ht {{
        deny all;
    }}

    # Bloquear acceso a ficheros sensibles que algunos frameworks dejan en la
    # raíz web (credenciales, control de versiones, dumps y backups).
    location ~ /\\.(?:env|git|svn|hg|bzr)(?:/|$) {{
        deny all;
    }}
    location ~* \\.(?:sql|bak|old|orig|save|swp|swo|log|sh)$ {{
        deny all;
    }}
    location ~ ~$ {{
        deny all;
    }}
    location = /composer.json {{ deny all; }}
    location = /composer.lock {{ deny all; }}
    location = /package.json {{ deny all; }}
    location = /.user.ini {{ deny all; }}
    location = /wp-config.php.bak {{ deny all; }}

    error_log {logs_dir}/nginx.error.log;
    access_log {logs_dir}/nginx.access.log;
}}
"""

    return server_block


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de cache (lectura/escritura/purga)
# ─────────────────────────────────────────────────────────────────────────────
def ensure_fastcgi_cache_root() -> None:
    """
    Crea /var/cache/nginx/fastcgi/ con permisos correctos para que nginx
    pueda escribir. Crea también el conf global con fastcgi_cache_key.
    Idempotente.
    """
    import os
    import subprocess
    os.makedirs(FASTCGI_CACHE_ROOT, exist_ok=True)
    try:
        subprocess.run(["chown", "-R", "www-data:www-data", FASTCGI_CACHE_ROOT], check=False)
    except FileNotFoundError:
        pass
    # Conf global con fastcgi_cache_key (nivel http) — se incluye una sola vez
    if not os.path.isfile(FASTCGI_CACHE_GLOBAL_CONF):
        with open(FASTCGI_CACHE_GLOBAL_CONF, "w") as f:
            f.write(FASTCGI_CACHE_GLOBAL_CONTENT)


def write_fastcgi_cache_zone(domain: str) -> str:
    """Escribe /etc/nginx/conf.d/svqpanel-cache-{domain}.conf con la zona. Devuelve la ruta."""
    import os
    ensure_fastcgi_cache_root()
    os.makedirs(get_fastcgi_cache_dir(domain), exist_ok=True)
    try:
        import subprocess
        subprocess.run(["chown", "-R", "www-data:www-data", get_fastcgi_cache_dir(domain)], check=False)
    except FileNotFoundError:
        pass
    path = get_fastcgi_cache_conf_path(domain)
    with open(path, "w") as f:
        f.write(generate_fastcgi_cache_zone_conf(domain))
    return path


def remove_fastcgi_cache_zone(domain: str) -> None:
    """Borra el fichero de zona y el directorio de cache de un dominio."""
    import os
    import shutil
    path = get_fastcgi_cache_conf_path(domain)
    if os.path.isfile(path):
        os.remove(path)
    cache_dir = get_fastcgi_cache_dir(domain)
    if os.path.isdir(cache_dir):
        shutil.rmtree(cache_dir, ignore_errors=True)


def purge_fastcgi_cache(domain: str) -> int:
    """
    Vacía el directorio de cache del dominio (sin borrar el dir). Devuelve
    el número de bytes liberados aproximado.
    """
    import os
    cache_dir = get_fastcgi_cache_dir(domain)
    if not os.path.isdir(cache_dir):
        return 0
    freed = 0
    for root, dirs, files in os.walk(cache_dir):
        for name in files:
            fp = os.path.join(root, name)
            try:
                freed += os.path.getsize(fp)
                os.remove(fp)
            except OSError:
                pass
    return freed


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
