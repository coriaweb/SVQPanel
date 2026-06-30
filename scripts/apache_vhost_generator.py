"""
Apache vhost generator — Apache como BACKEND de Nginx (arquitectura proxy).

ARQUITECTURA (modo apache+nginx):
    Internet → Nginx (:80, :443)            ← maneja SSL, HTTP/3, headers,
                 │                             bad bots, IPv6/IPv4
                 └─ proxy_pass → Apache (127.0.0.1:8181)
                                   └─ sirve PHP RESPETANDO .htaccess

Por eso este vhost Apache es DELIBERADAMENTE simple:
  - Escucha solo en 127.0.0.1:8181 (no expuesto a internet).
  - NO lleva SSL, headers de seguridad, bad bots ni redirecciones HTTPS:
    todo eso lo hace Nginx, el front. Duplicarlo causaría doble-header y
    conflictos.
  - SÍ lleva `AllowOverride All` → el único motivo de tener Apache: que los
    clientes con apps legacy puedan usar sus ficheros .htaccess (mod_rewrite,
    deny/allow, auth básica, etc.).
  - El PHP se sirve vía PHP-FPM (mismo socket por dominio que en Nginx).

La IP real del visitante llega vía X-Forwarded-For (mod_remoteip, configurado
en install.sh) para que los .htaccess que filtran por IP funcionen.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Puerto del backend Apache (debe coincidir con ports.conf del install)
APACHE_BACKEND_PORT = 8181
APACHE_BACKEND_ADDR = f"127.0.0.1:{APACHE_BACKEND_PORT}"


def generate_apache_vhost(
    domain_name: str,
    username: str,
    php_version: str = "8.2",
    ssl_enabled: bool = False,        # ignorado: el SSL lo termina Nginx
    ipv6: Optional[str] = None,       # ignorado: el binding público lo hace Nginx
    ipv4: Optional[str] = None,       # ignorado
    force_https: bool = False,        # ignorado: la redirección la hace Nginx
    hsts: bool = False,               # ignorado: HSTS lo pone Nginx
    redirect_to: Optional[str] = None,
    custom_docroot: Optional[str] = None,
    docroot_subdir: Optional[str] = None,
    blocked_user_agents: Optional[list] = None,  # ignorado: bots los bloquea Nginx
    readonly_mode_enabled: bool = False,         # ignorado: readonly lo hace Nginx
    allowed_mutation_ips: Optional[str] = None,
    php_socket_override: Optional[str] = None,
    custom_apache_config: Optional[str] = None,
    httpauth: Optional[dict] = None,
    xmlrpc_blocked: bool = False,  # el rate-limit de wp-login lo hace siempre Nginx
) -> str:
    """
    Genera el vhost Apache BACKEND (127.0.0.1:8181) de un dominio.

    Solo sirve PHP + ficheros estáticos respetando .htaccess. Todo lo de cara
    a internet (SSL, headers, bots, redirecciones) lo gestiona el Nginx front,
    por eso varios parámetros se aceptan por compatibilidad pero se ignoran.
    """
    from scripts.utils import get_public_html, get_domain_logs

    # Docroot
    if custom_docroot:
        docroot = custom_docroot
    else:
        public_html = get_public_html(username, domain_name)
        docroot = f"{public_html}/{docroot_subdir.lstrip('/')}" if docroot_subdir else public_html

    logs_dir = get_domain_logs(username, domain_name)
    access_log = f"{logs_dir}/apache.access.log"
    error_log = f"{logs_dir}/apache.error.log"

    # Socket PHP-FPM del dominio (MISMO que crea el pool real y usa Nginx). El
    # nombre lo define php_ini_manager.pool_socket_path (/run/php/svqpanel-
    # {domain}.sock); usar otro patrón aquí dejaba Apache apuntando a un socket
    # inexistente → 503. Por eso derivamos del helper, no de un patrón inventado.
    if php_socket_override:
        php_socket = php_socket_override
    else:
        try:
            from scripts.php_ini_manager import pool_socket_path
            php_socket = pool_socket_path(domain_name)
        except Exception:
            php_socket = f"/run/php/svqpanel-{domain_name}.sock"

    # Modo redirección: si el dominio redirige a otra URL, el Nginx front ya
    # hace el 301; el backend Apache no necesita vhost real. Devolvemos uno
    # mínimo que responde 410 por si acaso recibe tráfico directo.
    if redirect_to:
        return f"""# SVQPanel — {domain_name} (redirección gestionada por Nginx front)
<VirtualHost {APACHE_BACKEND_ADDR}>
    ServerName {domain_name}
    ServerAlias www.{domain_name}
    Redirect 410 /
    ErrorLog {error_log}
    CustomLog {access_log} svq_combined
</VirtualHost>
"""

    readonly_block = ""
    if readonly_mode_enabled:
        # Nginx ya bloquea las mutaciones en el front, pero lo replicamos como
        # defensa en profundidad por si alguien apunta directo al backend.
        readonly_block = _readonly_block(allowed_mutation_ips)

    # Directivas Apache personalizadas del dominio (dentro del VirtualHost).
    custom_block = ""
    if custom_apache_config and custom_apache_config.strip():
        custom_block = ("\n    # ── Directivas personalizadas del dominio ──\n"
                        + custom_apache_config.rstrip() + "\n")

    # Bloqueo de XML-RPC: defensa en profundidad. El Nginx front ya lo corta antes
    # de llegar aquí (return 444), pero lo negamos también en el backend Apache por
    # si alguien accede directo a :8181. El rate-limit de wp-login se queda en Nginx
    # (Apache requeriría mod_qos/mod_ratelimit, no garantizados).
    xmlrpc_block = ""
    if xmlrpc_blocked:
        xmlrpc_block = (
            "\n    # Bloqueo XML-RPC (lo corta el Nginx front; aquí por si acaso)\n"
            "    <Files \"xmlrpc.php\">\n"
            "        Require all denied\n"
            "    </Files>\n"
        )

    return f"""# SVQPanel — backend Apache de {domain_name} (front: Nginx)
# Apache solo sirve PHP + .htaccess; SSL/headers/bots los hace Nginx.
<VirtualHost {APACHE_BACKEND_ADDR}>
    ServerName {domain_name}
    ServerAlias www.{domain_name}
    DocumentRoot {docroot}

    # Nginx termina el SSL y reenvía por HTTP a Apache con X-Forwarded-Proto.
    # Sin esto, PHP ve HTTPS vacío y apps como WordPress redirigen a HTTPS en
    # bucle infinito (ERR_TOO_MANY_REDIRECTS). Marcamos HTTPS=on cuando el front
    # indica que la petición original era https.
    SetEnvIf X-Forwarded-Proto "https" HTTPS=on

    # Prioridad de índice: index.php ANTES que index.html (el DirectoryIndex
    # global de Debian pone .html primero, así un sitio con ambos serviría el
    # .html en vez de la app PHP). Lo fijamos por vhost.
    DirectoryIndex index.php index.html index.htm

    ErrorLog {error_log}
    CustomLog {access_log} svq_combined

    # PHP vía PHP-FPM (socket dedicado del dominio)
    <FilesMatch "\\.php$">
        SetHandler "proxy:unix:{php_socket}|fcgi://localhost"
    </FilesMatch>

    <Directory {docroot}>
        Options -Indexes +FollowSymLinks
        # AllowOverride All = soporte .htaccess (el motivo de usar Apache)
        AllowOverride All
        Require all granted
    </Directory>

    # Cache de navegador para estáticos (acelera visitas repetidas). mod_expires
    # se ignora si el módulo no está; el .htaccess del cliente puede sobreescribir.
    <IfModule mod_expires.c>
        ExpiresActive On
        <FilesMatch "\\.(?:css|js|jpg|jpeg|png|gif|ico|webp|avif|svg|woff|woff2|ttf|eot|otf|mp4|webm|ogg|mp3|pdf)$">
            ExpiresDefault "access plus 30 days"
            Header set Cache-Control "public, max-age=2592000"
        </FilesMatch>
    </IfModule>
{readonly_block}{custom_block}{xmlrpc_block}
    # Proteger ficheros sensibles aunque el .htaccess del cliente no lo haga
    <FilesMatch "(^\\.|\\.(env|git|sql|bak|old|log|sh)$)">
        Require all denied
    </FilesMatch>
</VirtualHost>
"""


def _readonly_block(allowed_mutation_ips: Optional[str] = None) -> str:
    """Bloquea PUT/DELETE/POST salvo IPs permitidas (defensa en profundidad)."""
    block = """
    # Readonly mode (defensa en profundidad; el front Nginx ya lo aplica)
    RewriteEngine On
    RewriteCond %{REQUEST_METHOD} ^(PUT|DELETE|POST)$ [NC]
"""
    if allowed_mutation_ips:
        for ip in allowed_mutation_ips.split(","):
            ip = ip.strip()
            if ip:
                block += f"    RewriteCond %{{REMOTE_ADDR}} !^{ip}$ [NC]\n"
    block += "    RewriteRule ^(.*)$ - [F,L]\n"
    return block
