"""
Webmail por dominio (estilo Hestia): sirve el Roundcube COMPARTIDO bajo
webmail.{dominio} mediante un vhost nginx dedicado por dominio.

No se instala un Roundcube por dominio: hay uno solo en /var/www/webmail
(lo instala install.sh) y cada webmail.{dominio} lo reutiliza. Roundcube detecta
el dominio del login (email completo) y conecta al IMAP/SMTP correspondiente.

Cada vhost vive en /etc/nginx/sites-available/svqpanel-webmail-{dominio} y se
enlaza en sites-enabled. SSL: si el certificado del dominio incluye
webmail.{dominio}, se sirve también por HTTPS.
"""

import logging
import os
from typing import Tuple

from .base import SystemManager

logger = logging.getLogger(__name__)

# Roundcube compartido (symlink creado por install.sh)
WEBMAIL_ROOT = "/var/www/webmail"
SITES_AVAILABLE = "/etc/nginx/sites-available"
SITES_ENABLED = "/etc/nginx/sites-enabled"


def vhost_name(domain: str) -> str:
    return f"svqpanel-webmail-{domain}"


def webmail_host(domain: str) -> str:
    return f"webmail.{domain}"


def _find_php_sock() -> str:
    """Socket PHP-FPM para Roundcube (el más nuevo disponible)."""
    import glob
    socks = sorted(
        glob.glob("/run/php/php*-fpm.sock") + glob.glob("/var/run/php/php*-fpm.sock"),
        reverse=True,
    )
    return socks[0] if socks else "/run/php/php8.3-fpm.sock"


def cert_includes_webmail(domain: str) -> bool:
    """¿El certificado del dominio cubre webmail.{dominio}? (mira el live cert)."""
    cert = f"/etc/letsencrypt/live/{domain}/cert.pem"
    if not os.path.exists(cert):
        return False
    try:
        import subprocess
        r = subprocess.run(
            ["/usr/bin/openssl", "x509", "-noout", "-text", "-in", cert],
            capture_output=True, text=True, timeout=10,
        )
        return f"DNS:{webmail_host(domain)}" in r.stdout
    except Exception:
        return False


class WebmailManager(SystemManager):
    """Genera y gestiona los vhosts nginx de webmail.{dominio}."""

    def __init__(self):
        super().__init__(require_root=True)

    # ── Generación del vhost ──────────────────────────────────────────────────
    def _vhost_content(self, domain: str, ssl: bool) -> str:
        host = webmail_host(domain)
        sock = _find_php_sock()

        # Bloques location de Roundcube (root = /var/www/webmail, servido en /).
        # Roundcube 1.7+: assets vía static.php con PATH_INFO.
        rc_locations = f"""    root {WEBMAIL_ROOT};
    index index.php;

    location / {{
        try_files $uri $uri/ /index.php?$query_string;
    }}

    location ~ ^/static\\.php {{
        fastcgi_split_path_info ^(/static\\.php)(/.+)$;
        fastcgi_pass unix:{sock};
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME {WEBMAIL_ROOT}/static.php;
        fastcgi_param PATH_INFO $fastcgi_path_info;
        fastcgi_param SCRIPT_NAME /static.php;
    }}

    location ~ \\.php$ {{
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:{sock};
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        include fastcgi_params;
    }}

    # Rutas internas de Roundcube que no deben servirse
    location ~ ^/(config|temp|logs|SQL|bin|vendor)/ {{ deny all; }}
    location ~ /\\.  {{ deny all; }}
    location ~ ^/(README|INSTALL|LICENSE|CHANGELOG|UPGRADING)$ {{ deny all; }}
"""

        # El cert puede ser propio del webmail o del dominio padre (expand legacy)
        webmail_cert = f"/etc/letsencrypt/live/{host}/fullchain.pem"
        webmail_key  = f"/etc/letsencrypt/live/{host}/privkey.pem"
        domain_cert  = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
        domain_key   = f"/etc/letsencrypt/live/{domain}/privkey.pem"
        import os as _os
        if _os.path.exists(webmail_cert):
            ssl_cert, ssl_key = webmail_cert, webmail_key
        else:
            ssl_cert, ssl_key = domain_cert, domain_key

        out = f"""# SVQPanel — Webmail de {domain} (Roundcube compartido)
server {{
    listen 80;
    listen [::]:80;
    server_name {host};

    # .well-known con ^~ tiene prioridad sobre regex — necesario para certbot ACME
    location ^~ /.well-known {{
        allow all;
    }}
"""
        if ssl:
            # En HTTP solo redirigimos a HTTPS (salvo ACME, ya cubierto arriba)
            out += f"""    location / {{ return 301 https://{host}$request_uri; }}
}}

server {{
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name {host};

    ssl_certificate {ssl_cert};
    ssl_certificate_key {ssl_key};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location ^~ /.well-known {{
        allow all;
    }}

{rc_locations}
    error_log /var/log/nginx/webmail-{domain}.error.log;
    access_log /var/log/nginx/webmail-{domain}.access.log;
}}
"""
        else:
            out += f"""
{rc_locations}
    error_log /var/log/nginx/webmail-{domain}.error.log;
    access_log /var/log/nginx/webmail-{domain}.access.log;
}}
"""
        return out

    # ── Operaciones ───────────────────────────────────────────────────────────
    def is_enabled(self, domain: str) -> bool:
        return os.path.islink(os.path.join(SITES_ENABLED, vhost_name(domain))) or \
               os.path.exists(os.path.join(SITES_AVAILABLE, vhost_name(domain)))

    def enable(self, domain: str, ssl: bool = None) -> Tuple[bool, str]:
        """
        Crea (o regenera) el vhost webmail.{dominio} y recarga nginx.
        ssl=None → autodetecta si el cert del dominio incluye webmail.{dominio}.
        """
        if not os.path.exists(WEBMAIL_ROOT):
            return False, ("Roundcube no está instalado (/var/www/webmail no existe). "
                           "Instálalo para poder activar el webmail por dominio.")
        if ssl is None:
            ssl = cert_includes_webmail(domain)

        avail = os.path.join(SITES_AVAILABLE, vhost_name(domain))
        enabled = os.path.join(SITES_ENABLED, vhost_name(domain))
        try:
            with open(avail, "w") as f:
                f.write(self._vhost_content(domain, ssl))
            if not os.path.islink(enabled):
                os.symlink(avail, enabled)
        except OSError as e:
            return False, f"No se pudo escribir el vhost: {e}"

        rc, _, err = self.execute_command(["nginx", "-t"], check=False)
        if rc != 0:
            # revertir para no dejar nginx roto
            try:
                os.remove(enabled)
            except OSError:
                pass
            return False, f"nginx -t falló: {err[:300]}"
        self.execute_command(["systemctl", "reload", "nginx"], check=False)
        logger.info(f"Webmail vhost activado: {webmail_host(domain)} (ssl={ssl})")
        return True, f"Webmail disponible en https://{webmail_host(domain)}" if ssl \
            else f"Webmail disponible en http://{webmail_host(domain)}"

    def remove(self, domain: str) -> Tuple[bool, str]:
        """Elimina el vhost webmail.{dominio} y recarga nginx."""
        avail = os.path.join(SITES_AVAILABLE, vhost_name(domain))
        enabled = os.path.join(SITES_ENABLED, vhost_name(domain))
        for p in (enabled, avail):
            try:
                if os.path.islink(p) or os.path.exists(p):
                    os.remove(p)
            except OSError as e:
                logger.warning(f"No se pudo borrar {p}: {e}")
        self.execute_command(["nginx", "-t"], check=False)
        self.execute_command(["systemctl", "reload", "nginx"], check=False)
        logger.info(f"Webmail vhost eliminado: {webmail_host(domain)}")
        return True, "Webmail desactivado"
