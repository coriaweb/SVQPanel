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
from .utils import SSL_PROTOCOLS, SSL_CIPHERS, SSL_SIGN_ALGS

logger = logging.getLogger(__name__)

# Roundcube compartido (symlink creado por install.sh)
WEBMAIL_ROOT = "/var/www/webmail"
SITES_AVAILABLE = "/etc/nginx/sites-available"
SITES_ENABLED = "/etc/nginx/sites-enabled"

# Margen sobre el message_size_limit de Postfix para las capas HTTP del webmail
# (nginx + PHP). Al adjuntar por webmail, el fichero viaja codificado MIME/base64,
# lo que infla su tamaño ~33 %; un adjunto de N MB reales ocupa ~1,33·N en el POST.
# Con un 40 % de margen, un adjunto que Postfix aceptaría (N MB) no muere antes en
# PHP/nginx por el overhead de codificación. Postfix sigue siendo el tope real.
WEBMAIL_UPLOAD_MARGIN = 1.40


def webmail_http_limit_mb(postfix_mb: int) -> int:
    """MB que deben aceptar nginx y PHP del webmail para un límite de correo dado.

    Aplica WEBMAIL_UPLOAD_MARGIN y redondea hacia arriba. Función pura (testeable).
    """
    import math
    try:
        base = int(postfix_mb)
    except (ValueError, TypeError):
        base = 25  # default de correo del panel si el valor es ilegible
    if base < 1:
        base = 1
    return max(1, math.ceil(base * WEBMAIL_UPLOAD_MARGIN))


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
    """
    ¿Hay un certificado SSL válido para webmail.{dominio}?
    Comprueba dos fuentes:
      1. Cert propio de webmail.{dominio} (emitido con --webroot independiente).
      2. Cert del dominio padre que incluya webmail.{dominio} como SAN (expand legacy).
    """
    host = webmail_host(domain)
    # 1. Cert propio para webmail.{dominio}
    own_cert = f"/etc/letsencrypt/live/{host}/cert.pem"
    if os.path.exists(own_cert):
        return True
    # 2. SAN en el cert del dominio padre
    parent_cert = f"/etc/letsencrypt/live/{domain}/cert.pem"
    if not os.path.exists(parent_cert):
        return False
    try:
        import subprocess
        r = subprocess.run(
            ["/usr/bin/openssl", "x509", "-noout", "-text", "-in", parent_cert],
            capture_output=True, text=True, timeout=10,
        )
        return f"DNS:{host}" in r.stdout
    except Exception:
        return False


class WebmailManager(SystemManager):
    """Genera y gestiona los vhosts nginx de webmail.{dominio}."""

    def __init__(self):
        super().__init__(require_root=True)

    # ── Generación del vhost ──────────────────────────────────────────────────
    def _postfix_message_size_mb(self) -> int:
        """Lee message_size_limit de Postfix en MB (25 si no se puede leer)."""
        import subprocess
        try:
            r = subprocess.run(["postconf", "-h", "message_size_limit"],
                               capture_output=True, text=True, timeout=5)
            bytes_ = int((r.stdout or "").strip())
            mb = round(bytes_ / (1024 * 1024))
            return mb if mb >= 1 else 25
        except Exception:
            return 25

    def _vhost_content(self, domain: str, ssl: bool) -> str:
        host = webmail_host(domain)
        sock = _find_php_sock()
        # Límite de subida HTTP del webmail = message_size_limit de Postfix + margen
        # (base64). Sin esto nginx aplica su default de 1 MB y el adjunto muere antes
        # de llegar a PHP/Postfix.
        upload_mb = webmail_http_limit_mb(self._postfix_message_size_mb())

        # Roundcube 1.7+ sirve desde public_html/ como docroot público.
        # Los directorios internos (config, logs, etc.) quedan fuera del docroot.
        WEBMAIL_DOCROOT = f"{WEBMAIL_ROOT}/public_html"
        rc_locations = f"""    root {WEBMAIL_DOCROOT};
    index index.php;

    location / {{
        try_files $uri $uri/ /index.php?$query_string;
    }}

    location ~ ^/static\\.php {{
        fastcgi_split_path_info ^(/static\\.php)(/.+)$;
        fastcgi_pass unix:{sock};
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME {WEBMAIL_DOCROOT}/static.php;
        fastcgi_param PATH_INFO $fastcgi_path_info;
        fastcgi_param SCRIPT_NAME /static.php;
    }}

    location ~ \\.php$ {{
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:{sock};
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        include fastcgi_params;
    }}

    # Rutas internas de Roundcube fuera del docroot — denegadas por seguridad
    location ~ ^/(config|temp|logs|SQL|bin|vendor|program)/ {{ deny all; }}
    location ~ /\\.  {{ deny all; }}
    location ~ ^/(README|INSTALL|LICENSE|CHANGELOG|UPGRADING|composer\\.(json|lock)|Makefile)$ {{ deny all; }}
"""

        # Preferir siempre el cert del dominio padre si incluye webmail como SAN.
        # Usar un cert separado para webmail causa conflictos SNI en nginx cuando
        # múltiples vhosts comparten el mismo listen 443 (el primer cert cargado
        # gana para toda la IP antes de leer el SNI del cliente).
        import os as _os, subprocess as _sp
        domain_cert  = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
        domain_key   = f"/etc/letsencrypt/live/{domain}/privkey.pem"
        webmail_cert = f"/etc/letsencrypt/live/{host}/fullchain.pem"
        webmail_key  = f"/etc/letsencrypt/live/{host}/privkey.pem"

        def _cert_has_san(cert_path, san):
            try:
                r = _sp.run(["openssl", "x509", "-noout", "-ext", "subjectAltName",
                              "-in", cert_path], capture_output=True, text=True, timeout=5)
                return san in r.stdout
            except Exception:
                return False

        if _os.path.exists(domain_cert) and _cert_has_san(domain_cert, host):
            # El cert del dominio padre ya incluye webmail — usarlo directamente
            ssl_cert, ssl_key = domain_cert, domain_key
        elif _os.path.exists(webmail_cert):
            ssl_cert, ssl_key = webmail_cert, webmail_key
        else:
            ssl_cert, ssl_key = domain_cert, domain_key

        # listen GENÉRICO (sin atar a la IP). Atar el listen a la IP concreta
        # (listen <IP>:443) hace que ESTE vhost sea el default de esa IP y capture
        # tráfico de otros server_name (p.ej. www.dominio acababa en webmail), y
        # además crea asimetría IPv4/IPv6 (el [::]:443 no se ata). El enrutado
        # correcto lo hace server_name; nginx ya elige el cert por SNI.
        out = f"""# SVQPanel — Webmail de {domain} (Roundcube compartido)
server {{
    listen 80;
    listen [::]:80;
    server_name {host};

    # .well-known con ^~ tiene prioridad sobre regex — necesario para certbot ACME
    location ^~ /.well-known {{
        root {WEBMAIL_ROOT};
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

    # Adjuntos: aceptar hasta el límite de correo de Postfix + margen base64.
    client_max_body_size {upload_mb}m;

    ssl_certificate {ssl_cert};
    ssl_certificate_key {ssl_key};
    ssl_protocols {SSL_PROTOCOLS};
    ssl_ciphers {SSL_CIPHERS};
    ssl_prefer_server_ciphers on;
    ssl_conf_command SignatureAlgorithms {SSL_SIGN_ALGS};

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
    # Adjuntos: aceptar hasta el límite de correo de Postfix + margen base64.
    client_max_body_size {upload_mb}m;

{rc_locations}
    error_log /var/log/nginx/webmail-{domain}.error.log;
    access_log /var/log/nginx/webmail-{domain}.access.log;
}}
"""
        return out

    # ── Operaciones ───────────────────────────────────────────────────────────
    def is_enabled(self, domain: str) -> bool:
        avail = os.path.join(SITES_AVAILABLE, vhost_name(domain))
        if not os.path.exists(avail):
            return False
        # Un vhost "desactivado" contiene return 503 — no está realmente activo
        try:
            with open(avail) as f:
                return "return 503" not in f.read()
        except OSError:
            return False

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
        """
        Desactiva el webmail del dominio.
        En lugar de eliminar el vhost (lo que haría que nginx sirva el dominio padre),
        lo reemplaza por un vhost mínimo que devuelve 503 con mensaje claro.
        Así el subdominio webmail.{dominio} no muestra el sitio web del dominio.
        """
        host = webmail_host(domain)
        avail   = os.path.join(SITES_AVAILABLE, vhost_name(domain))
        enabled = os.path.join(SITES_ENABLED,   vhost_name(domain))

        # Detectar si hay cert disponible para mantener HTTPS
        domain_cert = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
        domain_key  = f"/etc/letsencrypt/live/{domain}/privkey.pem"
        own_cert    = f"/etc/letsencrypt/live/{host}/fullchain.pem"
        own_key     = f"/etc/letsencrypt/live/{host}/privkey.pem"

        if os.path.exists(domain_cert):
            ssl_cert, ssl_key = domain_cert, domain_key
        elif os.path.exists(own_cert):
            ssl_cert, ssl_key = own_cert, own_key
        else:
            ssl_cert = ssl_key = None

        if ssl_cert:
            vhost = f"""server {{
    listen 80;
    listen [::]:80;
    server_name {host};
    return 301 https://$host$request_uri;
}}
server {{
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name {host};
    ssl_certificate {ssl_cert};
    ssl_certificate_key {ssl_key};
    ssl_protocols {SSL_PROTOCOLS};
    ssl_ciphers {SSL_CIPHERS};
    ssl_prefer_server_ciphers on;
    ssl_conf_command SignatureAlgorithms {SSL_SIGN_ALGS};
    return 503;
    error_page 503 @webmail_disabled;
    location @webmail_disabled {{
        default_type text/html;
        return 503 '<html><meta charset="utf-8"><body style="font-family:sans-serif;text-align:center;padding:4rem"><h2>Webmail no disponible</h2><p>El webmail de {domain} esta desactivado.</p></body></html>';
    }}
}}
"""
        else:
            vhost = f"""server {{
    listen 80;
    listen [::]:80;
    server_name {host};
    return 503;
    error_page 503 @webmail_disabled;
    location @webmail_disabled {{
        default_type text/html;
        return 503 '<html><meta charset="utf-8"><body style="font-family:sans-serif;text-align:center;padding:4rem"><h2>Webmail no disponible</h2><p>El webmail de {domain} esta desactivado.</p></body></html>';
    }}
}}
"""
        try:
            with open(avail, "w") as f:
                f.write(vhost)
            if not os.path.exists(enabled):
                os.symlink(avail, enabled)
        except OSError as e:
            logger.warning(f"No se pudo escribir vhost desactivado para {host}: {e}")

        self.execute_command(["nginx", "-t"], check=False)
        self.execute_command(["nginx", "-s", "reload"], check=False)
        logger.info(f"Webmail desactivado (503): {host}")
        return True, "Webmail desactivado"

    def destroy(self, domain: str) -> Tuple[bool, str]:
        """
        Elimina POR COMPLETO el vhost de webmail (available + enabled). A
        diferencia de remove() —que deja un vhost 503 porque el dominio sigue
        existiendo—, esto es para cuando se borra el dominio entero: no debe
        quedar ningún fichero huérfano de webmail.{dominio}.
        """
        avail   = os.path.join(SITES_AVAILABLE, vhost_name(domain))
        enabled = os.path.join(SITES_ENABLED,   vhost_name(domain))
        removed = False
        for path in (enabled, avail):
            try:
                if os.path.islink(path) or os.path.exists(path):
                    os.remove(path)
                    removed = True
            except OSError as e:
                logger.warning(f"No se pudo borrar {path}: {e}")
        if removed:
            self.execute_command(["nginx", "-t"], check=False)
            self.execute_command(["systemctl", "reload", "nginx"], check=False)
            logger.info(f"Webmail vhost eliminado por completo: {webmail_host(domain)}")
        return True, "Webmail eliminado"

    # ── Límite de subida (adjuntos): PHP + Roundcube + vhosts ─────────────────
    # El webmail es UNO SOLO compartido por todos los dominios; su límite de
    # subida es, por tanto, global y acompaña al message_size_limit de Postfix.
    # Se propaga a las tres capas que intervienen al adjuntar por HTTP:
    #   1) nginx  → client_max_body_size en cada vhost webmail.{dominio}
    #   2) PHP    → upload_max_filesize / post_max_size del PHP que sirve Roundcube
    #   3) Roundcube → $config['max_message_size']
    # Sin esto, el adjunto muere en PHP (default 2 MB) mucho antes de llegar a
    # Postfix, aunque el panel diga que el correo admite 25 MB.

    # Drop-in de PHP-FPM para el webmail (afecta al pool que sirve Roundcube).
    PHP_INI_NAME = "zz-svqpanel-webmail.ini"

    def _php_fpm_ini_paths(self):
        """Rutas de drop-in a escribir: un .ini en conf.d de cada versión de
        PHP-FPM instalada. Devuelve [(ini_path, service_name), ...].

        Roundcube se sirve por el socket PHP-FPM más nuevo (_find_php_sock), pero
        escribimos en TODAS las versiones instaladas para que el límite valga sin
        importar cuál acabe sirviendo el webmail (idempotente y barato)."""
        import glob
        out = []
        for confd in sorted(glob.glob("/etc/php/*/fpm/conf.d")):
            ver = confd.split("/")[3]  # /etc/php/<ver>/fpm/conf.d
            out.append((os.path.join(confd, self.PHP_INI_NAME), f"php{ver}-fpm"))
        return out

    def _write_php_ini(self, upload_mb: int) -> list:
        """Escribe el drop-in PHP con los límites de subida. Devuelve la lista de
        servicios PHP-FPM a recargar."""
        content = (
            "; SVQPanel — límite de subida del webmail (Roundcube).\n"
            "; Gestionado automáticamente: acompaña al message_size_limit de\n"
            "; Postfix (Configuración → Email → Tamaño máximo de mensaje) + margen\n"
            "; base64. No editar a mano.\n"
            f"upload_max_filesize = {upload_mb}M\n"
            f"post_max_size = {upload_mb}M\n"
        )
        services = []
        for ini_path, service in self._php_fpm_ini_paths():
            try:
                with open(ini_path, "w") as f:
                    f.write(content)
                services.append(service)
            except OSError as e:
                logger.warning(f"No se pudo escribir {ini_path}: {e}")
        return services

    def _patch_roundcube_max_message_size(self, upload_mb: int) -> bool:
        """Fija $config['max_message_size'] en el config de Roundcube.

        Roundcube usa max_message_size para su propio control de tamaño del
        adjunto (además de PHP). Lo mantenemos alineado con el resto."""
        cfg = os.path.join(WEBMAIL_ROOT, "config", "config.inc.php")
        if not os.path.exists(cfg):
            return False
        try:
            import re
            with open(cfg, "r") as f:
                content = f.read()
            bytes_ = upload_mb * 1024 * 1024
            line = f"$config['max_message_size'] = {bytes_}; // SVQPanel: = límite de correo + margen\n"
            pattern = r"\$config\['max_message_size'\]\s*=.*?;.*\n?"
            if re.search(pattern, content):
                content = re.sub(pattern, line, content, count=1)
            else:
                # Insertar antes del cierre PHP si existe, o al final.
                if content.rstrip().endswith("?>"):
                    idx = content.rstrip().rfind("?>")
                    content = content[:idx] + line + content[idx:]
                else:
                    content = content.rstrip() + "\n" + line
            with open(cfg, "w") as f:
                f.write(content)
            return True
        except OSError as e:
            logger.warning(f"No se pudo parchear config de Roundcube: {e}")
            return False

    def regenerate_all_vhosts(self) -> int:
        """Regenera todos los vhosts webmail.{dominio} existentes (para que
        recojan el client_max_body_size nuevo). Devuelve cuántos se tocaron.

        Solo reescribe los que están ACTIVOS (no los desactivados con 503)."""
        import glob
        n = 0
        prefix = "svqpanel-webmail-"
        for avail in glob.glob(os.path.join(SITES_AVAILABLE, prefix + "*")):
            name = os.path.basename(avail)
            domain = name[len(prefix):]
            if not domain:
                continue
            if not self.is_enabled(domain):
                continue  # vhost desactivado (503): no lo tocamos
            ssl = cert_includes_webmail(domain)
            try:
                with open(avail, "w") as f:
                    f.write(self._vhost_content(domain, ssl))
                n += 1
            except OSError as e:
                logger.warning(f"No se pudo regenerar vhost webmail {domain}: {e}")
        return n

    def sync_upload_limit(self, postfix_mb: int = None) -> dict:
        """Alinea el límite de subida del webmail con el de Postfix.

        postfix_mb=None → lee el message_size_limit actual de Postfix. Regenera
        las tres capas (nginx, PHP, Roundcube) y recarga los servicios. Es
        idempotente: seguro de llamar tras cada cambio del tamaño de mensaje.
        """
        if postfix_mb is None:
            postfix_mb = self._postfix_message_size_mb()
        upload_mb = webmail_http_limit_mb(postfix_mb)

        # 1) nginx: regenerar vhosts + recargar (solo si Roundcube está montado)
        vhosts = 0
        if os.path.exists(WEBMAIL_ROOT):
            vhosts = self.regenerate_all_vhosts()
            if vhosts:
                rc, _, err = self.execute_command(["nginx", "-t"], check=False)
                if rc == 0:
                    self.execute_command(["systemctl", "reload", "nginx"], check=False)
                else:
                    logger.warning(f"nginx -t falló tras sync_upload_limit: {err[:200]}")

        # 2) PHP: drop-in + reload de los PHP-FPM
        services = self._write_php_ini(upload_mb)
        for svc in services:
            self.execute_command(["systemctl", "reload", svc], check=False)

        # 3) Roundcube config
        rc_patched = self._patch_roundcube_max_message_size(upload_mb)

        logger.info(f"sync_upload_limit: correo={postfix_mb}MB → webmail={upload_mb}MB "
                    f"(vhosts={vhosts}, php={len(services)}, roundcube={rc_patched})")
        return {"success": True, "postfix_mb": postfix_mb, "upload_mb": upload_mb,
                "vhosts": vhosts, "php_services": services, "roundcube": rc_patched}
