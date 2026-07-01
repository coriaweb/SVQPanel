"""Utility functions for system management"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Política TLS del servidor (centralizada) ────────────────────────────────
# Nivel "moderno" (NCSC-NL 2025): TLS 1.2 SOLO con cifrados AEAD (ECDHE + GCM/
# CHACHA20) — sin CBC, Camellia, ARIA ni CCM_8, que el test marca como
# insufficient/phase-out. TLS 1.3 negocia sus propios cifrados (todos buenos).
# Compatible con cualquier navegador/móvil de los últimos ~8 años.
# Fuente única: usar SSL_PROTOCOLS / SSL_CIPHERS en todos los vhosts (web,
# correo, webmail, panel) para que un cambio de política se propague a la vez.
SSL_PROTOCOLS = "TLSv1.2 TLSv1.3"
SSL_CIPHERS = (
    "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:"
    "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
    "ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305"
)
# Algoritmos de firma TLS 1.2 (handshake). Dejamos SOLO SHA-256/384/512 — fuera
# SHA-224 (phase-out NCSC) y SHA-1 (insuficiente). Requiere nginx 1.19.4+ /
# OpenSSL 1.1.1+ (la directiva ssl_conf_command). TLS 1.3 ya lo gestiona solo.
SSL_SIGN_ALGS = (
    "ECDSA+SHA256:ECDSA+SHA384:ECDSA+SHA512:"
    "RSA-PSS+SHA256:RSA-PSS+SHA384:RSA-PSS+SHA512:"
    "RSA+SHA256:RSA+SHA384:RSA+SHA512"
)
# Línea nginx lista para inyectar tras los ssl_ciphers (con su \n al final).
SSL_CONF_COMMAND_LINE = f"    ssl_conf_command SignatureAlgorithms {SSL_SIGN_ALGS};\n"


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
FASTCGI_CACHE_GLOBAL_CONTENT = '''# SVQPanel — directivas de cache de página compartidas (nivel http)
# La cache_key debe declararse UNA sola vez en todo nginx; aquí la centralizamos.
# Las zonas (keys_zone) las define cada dominio en su svqpanel-cache-{domain}.conf.
# fastcgi_cache_key → modo nginx-puro; proxy_cache_key → modo Apache (proxy a :8181).
fastcgi_cache_key "$scheme$request_method$host$request_uri";
proxy_cache_key   "$scheme$request_method$host$request_uri";
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


# ── Rate-limit específico de /wp-login.php (anti fuerza bruta WordPress) ──────
# Zona propia, independiente del rate-limit general del sitio, para poder
# aplicar un límite muy estricto solo al login (p.ej. 3 req/min por IP) sin
# afectar al tráfico normal del dominio.
def get_wplogin_conf_path(domain: str) -> str:
    return f"/etc/nginx/conf.d/svqpanel-wplogin-{domain}.conf"


def _wplogin_zone_name(domain: str) -> str:
    return "svqwp_" + domain.replace('.', '_').replace('-', '_')


def write_wplogin_zone(domain: str, per_min: int) -> str:
    """
    Escribe la zona limit_req_zone para /wp-login.php del dominio.
    per_min = peticiones/min por IP (nginx admin r/m). Idempotente.
    """
    ensure_ratelimit_global()  # reutiliza limit_req_status 429
    zone = _wplogin_zone_name(domain)
    path = get_wplogin_conf_path(domain)
    content = (
        f"# SVQPanel — rate limit de wp-login.php de {domain}\n"
        f"limit_req_zone $binary_remote_addr zone={zone}:10m rate={per_min}r/m;\n"
    )
    with open(path, "w") as f:
        f.write(content)
    return path


def remove_wplogin_zone(domain: str) -> None:
    import os
    path = get_wplogin_conf_path(domain)
    if os.path.isfile(path):
        os.remove(path)


def _wplogin_location_block(domain: str, backend_name: str, ssl: bool,
                            proxy_to_apache: bool = False) -> str:
    """
    Rate-limit de wp-login.php: aplica el límite y sirve la petición por el MISMO
    camino que el resto del vhost: fastcgi a PHP-FPM en modo nginx puro, o proxy a
    Apache (:8181) en modo dual (para no saltarse los .htaccess). burst=2 + nodelay
    deja pasar un par de reintentos humanos pero corta el flood.

    Usa `location ~ ^/+wp-login\\.php` (regex) y NO `location = /wp-login.php`
    (match exacto): igual que con xmlrpc, el exacto no normaliza las barras
    iniciales y `//wp-login.php` se lo saltaría sin rate-limit. El regex captura
    cualquier número de barras. Un regex gana al 'location ~ \\.php$' / 'location /'
    por orden de aparición (va antes en el vhost).
    """
    zone = _wplogin_zone_name(domain)
    if proxy_to_apache:
        return (
            f"    location ~ ^/+wp-login\\.php {{\n"
            f"        limit_req zone={zone} burst=2 nodelay;\n"
            f"        proxy_pass http://127.0.0.1:8181;\n"
            f"        proxy_set_header Host $host;\n"
            f"        proxy_set_header X-Real-IP $remote_addr;\n"
            f"        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
            f"        proxy_set_header X-Forwarded-Proto $scheme;\n"
            f"    }}\n"
        )
    https_param = "        fastcgi_param HTTPS on;\n" if ssl else ""
    return (
        f"    location ~ ^/+wp-login\\.php {{\n"
        f"        limit_req zone={zone} burst=2 nodelay;\n"
        f"        try_files $uri =404;\n"
        f"        fastcgi_pass php_{backend_name};\n"
        f"        fastcgi_index index.php;\n"
        f"        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;\n"
        f"{https_param}"
        f"        include fastcgi_params;\n"
        f"    }}\n"
    )


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


def _domain_proxies_to_apache() -> bool:
    """True si el webserver está en modo Apache (nginx hace de proxy a :8181).
    En ese modo la cache de página debe ser proxy_cache, no fastcgi_cache."""
    try:
        from scripts.webserver_config import get_webserver
        return get_webserver() in ("apache", "apache+nginx")
    except Exception:
        return False


def generate_fastcgi_cache_zone_conf(domain: str) -> str:
    """
    Devuelve el contenido del fichero /etc/nginx/conf.d/svqpanel-cache-{domain}.conf.
    Define la zona de cache (keys_zone) que se referencia desde la vhost.

    En modo Apache usa proxy_cache_path (nginx hace proxy_pass a :8181, y el
    fastcgi_cache NO aplica al proxy). En modo nginx-puro usa fastcgi_cache_path.
    El nombre de zona (keys_zone) es el mismo; solo cambia la directiva _path.
    """
    cache_dir = get_fastcgi_cache_dir(domain)
    zone = fastcgi_cache_zone_name(domain)
    directive = "proxy_cache_path" if _domain_proxies_to_apache() else "fastcgi_cache_path"
    return f"""# SVQPanel — cache de página para {domain}
{directive} {cache_dir}
    levels=1:2
    keys_zone={zone}:10m
    max_size=500m
    inactive=1h
    use_temp_path=off;
"""


def _fastcgi_cache_block(domain: str, ttl_minutes: int, sec_headers: str = "") -> str:
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
        add_header X-Cache-Status $upstream_cache_status always;{sec_headers}
"""


def _proxy_cache_block(domain: str, ttl_minutes: int, sec_headers: str = "") -> str:
    """
    Equivalente a _fastcgi_cache_block pero para modo Apache (proxy_pass a :8181):
    el fastcgi_cache NO funciona con proxy_pass, hay que usar proxy_cache. Mismas
    exclusiones ($skip_cache: admin/POST/logueados/carrito WooCommerce) y misma
    zona por dominio. Se inserta DENTRO del 'location /' que hace proxy a Apache.
    """
    zone = fastcgi_cache_zone_name(domain)
    return f"""
        # ── Proxy cache (SVQPanel, modo Apache) ──────────────────────────
        proxy_cache          {zone};
        proxy_cache_bypass   $skip_cache;
        proxy_no_cache       $skip_cache;
        proxy_cache_valid    200 301 302 {ttl_minutes}m;
        proxy_cache_valid    404 1m;
        proxy_cache_use_stale error timeout invalid_header updating http_500 http_503;
        proxy_cache_lock     on;
        add_header X-Cache-Status $upstream_cache_status always;{sec_headers}
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

    # IPv4: escuchar genérico (listen 80), NO atado a una IP concreta. Atarlo a
    # la IP (listen 185.x.x.x:80) en un servidor de una sola IP hace que ESE
    # vhost capture TODO el tráfico de la IP (un listen con IP es más específico
    # que el genérico) y rompe el enrutado por server_name de los demás dominios.
    # El enrutado lo hace server_name; la IP solo importaría con multi-IP real.
    ipv4_listen_http  = "80"
    ipv4_listen_https = "443"
    # IPv6: escuchar en [::]:80 y enrutar por server_name (incluye la IPv6). NO
    # default_server (ese rol es del vhost de bienvenida; duplicarlo da 404).
    ipv6_listen_http  = "listen [::]:80;"
    ipv6_listen_https = "listen [::]:443 ssl;"

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
    ssl_protocols {SSL_PROTOCOLS};
    ssl_ciphers {SSL_CIPHERS};
    ssl_prefer_server_ciphers on;
{SSL_CONF_COMMAND_LINE}
    return 301 {destination}$request_uri;
}}
"""
    return config


def _canonical_redirect_block(domain: str, canonical_domain: Optional[str]) -> str:
    """Bloque nginx que fuerza el dominio canónico (www / non-www) con un 301.

    Se inyecta dentro del server{} (que escucha tanto dominio como www.dominio).
    Usa $host para detectar la variante pedida y redirige a la canónica
    preservando esquema y URI. Devuelve "" si canonical_domain es 'none'/None.
    """
    if canonical_domain == "www":
        # dominio.com → www.dominio.com (la variante con www es la canónica)
        return (
            f"\n    # ── Dominio canónico: forzar www ──\n"
            f"    if ($host = {domain}) {{\n"
            f"        return 301 $scheme://www.{domain}$request_uri;\n"
            f"    }}\n"
        )
    if canonical_domain == "non-www":
        # www.dominio.com → dominio.com (la variante sin www es la canónica)
        return (
            f"\n    # ── Dominio canónico: forzar sin www ──\n"
            f"    if ($host = www.{domain}) {{\n"
            f"        return 301 $scheme://{domain}$request_uri;\n"
            f"    }}\n"
        )
    return ""


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
    proxy_to_apache: bool = False,
    custom_nginx_config: Optional[str] = None,
    httpauth: Optional[dict] = None,
    canonical_domain: Optional[str] = "www",
    is_subdomain: bool = False,
    xmlrpc_blocked: bool = False,
    wp_login_ratelimit: int = 0,
) -> str:
    """
    Generate Nginx vhost configuration (Hestia-style paths).

    Si proxy_to_apache=True, el bloque que sirve PHP se reemplaza por un
    proxy_pass a Apache (127.0.0.1:8181), que sirve el sitio respetando los
    .htaccess. Nginx sigue siendo el front (SSL, headers, bots, HTTP/3); solo
    delega la ejecución del PHP+.htaccess a Apache. El resto del vhost (TLS,
    seguridad, ficheros bloqueados) es idéntico al modo nginx puro.
    """

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
    cache_block = ""  # built below after _sh is defined
    readonly_block = _readonly_mode_block(allowed_mutation_ips) if readonly_mode_enabled else ""
    # Bloqueo de XML-RPC (WordPress): 444 = cierra la conexión sin responder, así
    # el bot no gasta PHP-FPM ni recibe pista de que el endpoint existe. Coherente
    # con el bloqueo de bad-bots (también 444). Solo si el dominio lo activó.
    # OJO al regex y no `location = /xmlrpc.php`: el match exacto NO normaliza las
    # barras iniciales, así que `//xmlrpc.php` (doble barra) se lo salta y llega a
    # PHP/Apache arrancando WordPress. Los bots lo explotan en masa (visto ~18k
    # hits/min a //xmlrpc.php esquivando el bloqueo). `~ ^/+xmlrpc\.php` captura
    # cualquier número de barras iniciales y con o sin querystring.
    xmlrpc_block = (
        "    location ~ ^/+xmlrpc\\.php { return 444; }\n" if xmlrpc_blocked else ""
    )
    # Rate-limit de wp-login.php (anti fuerza bruta). Necesita su zona en
    # /etc/nginx/conf.d (la escriben los callers con write_wplogin_zone). Aquí
    # solo el location. Hay variante http/https por el fastcgi_param HTTPS.
    wp_login_http = (
        _wplogin_location_block(domain, backend_name, ssl=False, proxy_to_apache=proxy_to_apache)
        if wp_login_ratelimit and wp_login_ratelimit > 0 else ""
    )
    wp_login_ssl = (
        _wplogin_location_block(domain, backend_name, ssl=True, proxy_to_apache=proxy_to_apache)
        if wp_login_ratelimit and wp_login_ratelimit > 0 else ""
    )
    # Bloques combinados de protección WordPress que se insertan en cada server.
    wp_protect_http = xmlrpc_block + wp_login_http
    wp_protect_ssl  = xmlrpc_block + wp_login_ssl

    # Bloque de bloqueo de user-agents.
    #   1) Catálogo GLOBAL (Seguridad → Bloqueo de bots): /etc/nginx/conf.d/
    #      bad-bots.conf define `map $http_user_agent $bad_bot`. Aquí lo
    #      consultamos para que ese catálogo aplique a TODOS los dominios. El
    #      map siempre trae `default 0`, así que es inocuo si no hay bots.
    #   2) Patrones POR DOMINIO (blocked_user_agents): específicos de este sitio.
    bot_lines = ["    if ($bad_bot) { return 444; }"]
    if blocked_user_agents:
        for pattern in blocked_user_agents:
            pattern = pattern.strip()
            if pattern:
                safe = pattern.replace('"', '\\"').replace("'", "\\'")
                bot_lines.append(f'    if ($http_user_agent ~* "{safe}") {{ return 444; }}')
    bots_block = "\n" + "\n".join(bot_lines) + "\n"

    # server_name incluye IPv6 cuando está asignada (para acceso por IP directa).
    # Un SUBDOMINIO (gestion.zococoria.es) NO lleva www. (nadie usa
    # www.gestion.zococoria.es) ni redirección canónica: se sirve tal cual.
    if is_subdomain:
        server_names = domain
    else:
        server_names = f"{domain} www.{domain}"
    if ipv6:
        server_names += f" {ipv6}"   # nginx acepta IPv6 sin corchetes en server_name

    # Redirección al dominio canónico (www / non-www). Vacío si 'none'/None o si
    # es un subdominio (no aplica el concepto www).
    canonical_block = "" if is_subdomain else _canonical_redirect_block(domain, canonical_domain)

    # Inyección dentro del server{}: primero la plantilla, luego las directivas
    # personalizadas del dominio (pueden complementar/sobrescribir a la plantilla).
    tpl_extra = ("\n" + template_nginx_extra.rstrip()) if template_nginx_extra else ""
    if custom_nginx_config and custom_nginx_config.strip():
        tpl_extra += "\n    # ── Directivas personalizadas del dominio ──\n" + custom_nginx_config.rstrip() + "\n"
    # Protección con contraseña (auth básica) a nivel de server → protege todo
    # el sitio. .well-known/acme-challenge se exime para no romper Let's Encrypt.
    if httpauth and httpauth.get("file"):
        _realm = (httpauth.get("realm") or "Zona restringida").replace('"', "'")
        tpl_extra += (
            f'\n    # ── Protección con contraseña ──\n'
            f'    auth_basic "{_realm}";\n'
            f'    auth_basic_user_file {httpauth["file"]};\n'
            f'    location ^~ /.well-known/acme-challenge/ {{ auth_basic off; allow all; }}\n')


    # IPv4: escuchar genérico (listen 80), NO atado a una IP concreta. Atarlo a
    # la IP (listen 185.x.x.x:80) en un servidor de una sola IP hace que ESE
    # vhost capture TODO el tráfico de la IP (un listen con IP es más específico
    # que el genérico) y rompe el enrutado por server_name de los demás dominios.
    # El enrutado lo hace server_name; la IP solo importaría con multi-IP real.
    ipv4_listen_http  = "80"
    ipv4_listen_https = "443"
    # IPv6: escuchar en [::]:80 (todas) y enrutar por server_name (que incluye la
    # IPv6 literal). NO default_server: ese rol es del vhost de bienvenida
    # (svqpanel-welcome); duplicarlo aquí roba el tráfico IPv6 y da 404.
    ipv6_listen_http  = "listen [::]:80;"
    ipv6_listen_https = "listen [::]:443 ssl;"

    hsts_header = (
        '    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;'
        if (hsts and ssl_enabled) else ""
    )

    # HTTP/3 (QUIC) — requiere nginx 1.25+ con http_v3_module
    # Añade listen quic en puerto 443 y el header Alt-Svc para anunciar HTTP/3
    http3_listen = ""
    http3_header = ""
    if http3_enabled and ssl_enabled:
        # listen genérico (sin IP), por la misma razón que el resto: atarlo a la
        # IP rompe el enrutado en servidores de una sola IP.
        # OJO: NADA de `reuseport` aquí. `reuseport` solo puede aparecer UNA vez
        # por puerto en TODA la config de nginx; ponerlo en cada vhost hace que el
        # SEGUNDO dominio con HTTP/3 reviente nginx entero con "duplicate listen
        # options for 0.0.0.0:443" (y bloquea cualquier reload → migraciones y
        # cambios de vhost fallan). reuseport no es necesario para que QUIC
        # funcione: solo balancea conexiones UDP entre workers.
        http3_listen = "\n    listen 443 quic;"
        if ipv6:
            http3_listen += "\n    listen [::]:443 quic;"
        http3_header = '\n    add_header Alt-Svc \'h3=":443"; ma=86400\' always;'

    # Headers de seguridad HTTP (sin CSP para no romper contenido de clientes)
    sec_headers_http = ""
    sec_headers_https = ""
    _sh = ""
    if security_headers_enabled:
        _sh = """\
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()" always;
    add_header X-XSS-Protection "1; mode=block" always;"""
        sec_headers_http = "\n" + _sh
        sec_headers_https = "\n" + _sh
    # cache_block: security headers para HTTP; cache_block_ssl: todos (incluye HSTS+Alt-Svc)
    _sh_https = _sh
    if hsts and ssl_enabled:
        _sh_https += '\n    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;'
    if http3_enabled and ssl_enabled:
        _sh_https += '\n    add_header Alt-Svc \'h3=":443"; ma=86400\' always;'
    cache_block     = _fastcgi_cache_block(domain, fastcgi_cache_ttl_minutes, sec_headers=_sh) if fastcgi_cache_enabled else ""
    cache_block_ssl = _fastcgi_cache_block(domain, fastcgi_cache_ttl_minutes, sec_headers=_sh_https) if fastcgi_cache_enabled else ""

    # ── Bloque que ejecuta la aplicación (location / + PHP) ──
    # Modo nginx puro: try_files + fastcgi_pass a PHP-FPM.
    # Modo apache (proxy_to_apache): proxy_pass a Apache backend (:8181), que
    # sirve el sitio respetando .htaccess. Nginx sigue siendo front (SSL, bots,
    # headers); solo delega la ejecución a Apache.
    if proxy_to_apache:
        # En modo Apache la cache de página es proxy_cache (fastcgi_cache no aplica
        # al proxy_pass). Mismas exclusiones que en nginx-puro (via $skip_cache).
        pcache_http = _proxy_cache_block(domain, fastcgi_cache_ttl_minutes, sec_headers=_sh) \
            if fastcgi_cache_enabled else ""
        pcache_ssl = _proxy_cache_block(domain, fastcgi_cache_ttl_minutes, sec_headers=_sh_https) \
            if fastcgi_cache_enabled else ""

        def _proxy_loc(pcache: str) -> str:
            return (
                "    location / {\n"
                "        proxy_pass http://127.0.0.1:8181;\n"
                "        proxy_set_header Host $host;\n"
                "        proxy_set_header X-Real-IP $remote_addr;\n"
                "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
                "        proxy_set_header X-Forwarded-Proto $scheme;\n"
                "        proxy_set_header X-Forwarded-Host $host;\n"
                "        proxy_read_timeout 300;\n"
                f"{pcache}"
                "    }\n"
            )
        app_block_http = _proxy_loc(pcache_http)
        app_block_ssl  = _proxy_loc(pcache_ssl)
    else:
        # Cache de navegador para estáticos: CSS/JS/imágenes/fuentes con expires
        # largo (acelera la web en visitas repetidas; el navegador no los re-pide).
        static_cache = (
            "    location ~* \\.(?:css|js|jpg|jpeg|png|gif|ico|webp|avif|svg|woff|woff2|ttf|eot|otf|mp4|webm|ogg|mp3|pdf)$ {\n"
            "        expires 30d;\n"
            "        add_header Cache-Control \"public, max-age=2592000\";\n"
            "        access_log off;\n"
            "        try_files $uri =404;\n"
            "    }\n\n"
        )
        # Bloque clásico nginx: estáticos cacheados + location / con try_files + PHP.
        app_block_http = (
            static_cache +
            f"    location / {{{rl_directive}\n"
            f"{readonly_block}        try_files $uri $uri/ /index.php?$query_string;\n"
            f"    }}\n\n"
            f"    location ~ \\.php$ {{\n"
            f"        try_files $uri =404;\n"
            f"        fastcgi_pass php_{backend_name};\n"
            f"        fastcgi_index index.php;\n"
            f"        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;\n"
            f"        include fastcgi_params;{cache_block}\n"
            f"    }}\n"
        )
        app_block_ssl = (
            static_cache +
            f"    location / {{{rl_directive}\n"
            f"{readonly_block}        try_files $uri $uri/ /index.php?$query_string;\n"
            f"    }}\n\n"
            f"    location ~ \\.php$ {{\n"
            f"        try_files $uri =404;\n"
            f"        fastcgi_pass php_{backend_name};\n"
            f"        fastcgi_index index.php;\n"
            f"        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;\n"
            # Decirle a PHP que la petición llega por HTTPS. Sin esto, apps como
            # WordPress detectan $_SERVER['HTTPS'] vacío (nginx terminó el SSL) y
            # redirigen a HTTPS en bucle infinito → ERR_TOO_MANY_REDIRECTS.
            f"        fastcgi_param HTTPS on;\n"
            f"        include fastcgi_params;{cache_block_ssl}\n"
            f"    }}\n"
        )

    # Si force_https: el bloque HTTP solo redirige a HTTPS
    if force_https and ssl_enabled:
        # $server_name al redirigir a https da el primer nombre del bloque (el
        # dominio raíz); para respetar la variante pedida usamos $host. El
        # canonical_block (si aplica) ya redirige a la variante correcta antes.
        http_block = f"""server {{
    listen {ipv4_listen_http};
    {ipv6_listen_http}
    server_name {server_names};
{canonical_block}    return 301 https://$host$request_uri;
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
{canonical_block}{tpl_extra}{bots_block}{wp_protect_http}{app_block_http}
    location ~ /\\.ht {{
        deny all;
    }}
    # Bloquea el acceso a metadatos de VCS y ficheros de config sensibles: los bots
    # sondean /.git/config, /.env, /.svn/… para robar credenciales o el repo entero.
    # 444 (cierra sin responder, no da pistas). El regex cubre el path en cualquier
    # posición (p.ej. /subdir/.git/config).
    location ~ /\\.(git|svn|hg|env|bzr)(/|$) {{
        return 444;
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
    ssl_protocols {SSL_PROTOCOLS};
    ssl_ciphers {SSL_CIPHERS};
    ssl_prefer_server_ciphers on;
{SSL_CONF_COMMAND_LINE}{hsts_header}{http3_header}{sec_headers_https}

    index index.php index.html index.htm;
{skip_block}    set $phpfpm_backend php_{backend_name};
{canonical_block}{tpl_extra}{bots_block}{wp_protect_ssl}{app_block_ssl}
    location ~ /\\.ht {{
        deny all;
    }}
    # Bloquea el acceso a metadatos de VCS y ficheros de config sensibles: los bots
    # sondean /.git/config, /.env, /.svn/… para robar credenciales o el repo entero.
    # 444 (cierra sin responder, no da pistas). El regex cubre el path en cualquier
    # posición (p.ej. /subdir/.git/config).
    location ~ /\\.(git|svn|hg|env|bzr)(/|$) {{
        return 444;
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


def nginx_configtest() -> tuple:
    """
    Ejecuta `nginx -t`. Devuelve (ok: bool, salida: str).
    No recarga nada; solo valida la sintaxis de TODA la config.
    """
    import subprocess
    import os

    env = os.environ.copy()
    env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    try:
        proc = subprocess.run(["nginx", "-t"], capture_output=True, env=env)
        out = (proc.stderr or b"").decode(errors="replace")
        return proc.returncode == 0, out
    except Exception as e:
        return False, str(e)


def reload_nginx_or_diagnose(domain_name: str) -> None:
    """
    Recarga nginx tras crear/editar el vhost de `domain_name`. Si el configtest
    falla, distingue si el problema es ESTE vhost o uno AJENO (huérfano de un
    borrado anterior cuyo root/logs ya no existen). Así un vhost roto de otro
    dominio no hace fracasar el alta del nuevo con un mensaje engañoso.

    Lanza RuntimeError con un mensaje específico si no puede recargar.
    """
    ok, out = nginx_configtest()
    if ok:
        if not reload_nginx():
            raise RuntimeError("Nginx no pudo recargar (configtest OK pero reload falló)")
        return

    out = (out or "").strip()
    if domain_name in out:
        raise RuntimeError(f"Nginx configtest falló por el vhost de este dominio: {out}")
    raise RuntimeError(
        "Nginx no puede recargar porque OTRO vhost tiene un error (no es de este "
        "dominio); suele ser un vhost huérfano de un borrado anterior. Ejecuta "
        f"`python -m api.cli clean_orphan_vhosts --yes` para sanearlos. Detalle: {out}")


def reload_nginx() -> bool:
    """
    Valida la config y recarga nginx con un delay de 1s mediante un proceso
    completamente desacoplado (doble fork). Así el request HTTP termina y
    llega al cliente antes de que nginx recargue y corte la conexión.
    """
    import subprocess
    import os

    env = os.environ.copy()
    env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

    # Validar config de forma síncrona — si hay error de sintaxis, no recargar
    try:
        subprocess.run(["nginx", "-t"], check=True, capture_output=True, env=env)
    except subprocess.CalledProcessError as e:
        logger.error(f"Nginx config test failed: {e.stderr.decode() if e.stderr else e}")
        return False

    # Lanzar reload con 1s de delay como proceso totalmente independiente
    # (doble fork vía shell: el hijo se desacopla del proceso uvicorn)
    try:
        subprocess.Popen(
            "sleep 1 && nginx -s reload",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # desacopla del grupo de procesos de uvicorn
            env=env,
        )
        logger.info("Nginx reload scheduled (1s delay, detached)")
    except Exception as e:
        logger.error(f"Failed to schedule nginx reload: {e}")
        return False

    return True
