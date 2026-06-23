"""
Panel SSL Manager — emite y revoca el certificado SSL para el propio hostname del panel.

Flujo:
  1. Asegura el vhost nginx con el challenge ACME disponible en HTTP.
  2. Ejecuta certbot --nginx para emitir el certificado.
  3. Transforma el vhost existente: añade bloque HTTPS conservando TODA
     la configuración (phpMyAdmin, Roundcube, Rspamd, etc.) y opcionalmente
     un redirect HTTP → HTTPS.
  4. Recarga nginx.
"""

import logging
import os
import re
import shutil
from datetime import datetime
from .base import SystemManager
from .utils import SSL_PROTOCOLS, SSL_CIPHERS, SSL_SIGN_ALGS

logger = logging.getLogger(__name__)

# Ruta del vhost nginx que gestiona el acceso al panel
PANEL_NGINX_CONF = "/etc/nginx/sites-available/svqpanel"
PANEL_NGINX_LINK = "/etc/nginx/sites-enabled/svqpanel"


def _validate_hostname(hostname: str) -> bool:
    """Valida que el hostname sea un FQDN razonable."""
    pattern = r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
    return bool(re.match(pattern, hostname))


class PanelSSLManager(SystemManager):
    """Gestiona el certificado SSL del propio hostname del panel."""

    def __init__(self):
        super().__init__(require_root=True)

    # ──────────────────────────────────────────────────────────────────────────
    # Emisión
    # ──────────────────────────────────────────────────────────────────────────

    def issue_ssl(self, hostname: str, email: str, force_https: bool = True) -> dict:
        """
        Emite un certificado Let's Encrypt para el hostname del panel.

        Args:
            hostname:    FQDN del panel (ej: panel.midominio.com)
            email:       Email para Let's Encrypt
            force_https: Si True, configura nginx para redirigir HTTP → HTTPS

        Returns:
            {"success": True, "hostname": "...", "expires": "..."}
        """
        if not _validate_hostname(hostname):
            raise ValueError(f"Hostname inválido: {hostname}")

        logger.info(f"Emitiendo SSL para el panel en {hostname}")

        # 1. Hacer backup del vhost actual
        self._backup_conf()

        # 2. Aseguramos que el server_name del vhost incluye el hostname
        #    (certbot lo necesita para el challenge --nginx)
        self._patch_server_name(hostname)
        self._nginx_reload()

        # 3. Emitir con certbot --nginx
        rc, out, err = self.execute_command([
            "certbot", "certonly",
            "--nginx",
            "-d", hostname,
            "--non-interactive",
            "--agree-tos",
            "-m", email,
        ], check=False)

        if rc != 0:
            logger.error(f"certbot falló:\n{err}")
            # Restaurar configuración original
            self._restore_conf()
            self._nginx_reload()
            raise RuntimeError(f"certbot falló (código {rc}): {err.strip()}")

        # 4. Transformar el vhost para incluir SSL
        self._add_ssl_to_vhost(hostname, force_https)
        self._nginx_reload()

        # 5. Leer fecha de expiración del certificado
        expires = self._get_cert_expiry(hostname)

        logger.info(f"SSL del panel emitido correctamente para {hostname}")
        return {
            "success": True,
            "hostname": hostname,
            "expires": expires.isoformat() if expires else None,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Revocación / eliminación
    # ──────────────────────────────────────────────────────────────────────────

    def revoke_ssl(self, hostname: str) -> dict:
        """
        Revoca el certificado del panel y vuelve a configuración HTTP.

        Args:
            hostname: FQDN del panel

        Returns:
            {"success": True}
        """
        if not _validate_hostname(hostname):
            raise ValueError(f"Hostname inválido: {hostname}")

        logger.info(f"Revocando SSL del panel para {hostname}")

        self.execute_command([
            "certbot", "revoke",
            "--cert-name", hostname,
            "--non-interactive",
        ], check=False)

        self.execute_command([
            "certbot", "delete",
            "--cert-name", hostname,
            "--non-interactive",
        ], check=False)

        # Restaurar vhost a HTTP (backup o eliminar SSL del vhost actual)
        self._remove_ssl_from_vhost()
        self._nginx_reload()

        return {"success": True}

    # ──────────────────────────────────────────────────────────────────────────
    # Transformaciones del vhost nginx
    # ──────────────────────────────────────────────────────────────────────────

    def _patch_server_name(self, hostname: str) -> None:
        """Sustituye 'server_name _;' por el hostname real para que certbot funcione."""
        config = self._read_conf()
        # Reemplazar server_name _; o server_name el_viejo; por el hostname
        new_config = re.sub(
            r'(server_name\s+)[^;]+;',
            rf'\g<1>{hostname};',
            config,
            count=1,
        )
        self._write_conf(new_config)

    def _add_ssl_to_vhost(self, hostname: str, force_https: bool) -> None:
        """
        Transforma el vhost HTTP existente en uno HTTPS, conservando todo el
        contenido (phpMyAdmin, Roundcube, Rspamd, etc.).
        """
        cert_path = f"/etc/letsencrypt/live/{hostname}/fullchain.pem"
        key_path  = f"/etc/letsencrypt/live/{hostname}/privkey.pem"

        config = self._read_conf()

        # Extraer el contenido interior del bloque server { ... }
        # (todo lo que está entre la primera { y su } de cierre)
        inner = self._extract_server_inner(config)
        if inner is None:
            raise RuntimeError("No se pudo parsear el bloque server{} del vhost")

        # Preparar bloque HTTP (redirect o mantener)
        if force_https:
            http_block = (
                f"server {{\n"
                f"    listen 80;\n"
                f"    listen [::]:80;\n"
                f"    server_name {hostname};\n"
                f"    return 301 https://$host$request_uri;\n"
                f"}}\n"
            )
        else:
            # Conservar el bloque HTTP tal cual pero con el listen correcto
            http_block = (
                f"server {{\n"
                f"    listen 80;\n"
                f"    listen [::]:80;\n"
                f"    server_name {hostname};\n"
                + inner +
                f"}}\n"
            )

        # Bloque HTTPS: copiar el contenido existente añadiendo directivas SSL
        ssl_directives = (
            f"    listen 443 ssl;\n"
            f"    listen [::]:443 ssl;\n"
            f"    http2 on;\n"
            f"    server_name {hostname};\n"
            f"\n"
            f"    ssl_certificate     {cert_path};\n"
            f"    ssl_certificate_key {key_path};\n"
            f"    ssl_protocols       {SSL_PROTOCOLS};\n"
            f"    ssl_ciphers         {SSL_CIPHERS};\n"
            f"    ssl_prefer_server_ciphers on;\n"
            f"    ssl_conf_command Signature_Algorithms {SSL_SIGN_ALGS};\n"
            f"    ssl_session_cache   shared:SSL:10m;\n"
            f"    ssl_session_timeout 10m;\n"
            f"    add_header Strict-Transport-Security \"max-age=31536000; includeSubDomains\" always;\n"
            f"\n"
        )

        # Eliminar del inner las líneas listen y server_name (las ponemos nosotros)
        inner_clean = re.sub(r'\s*listen\s+[^;]+;\n', '', inner)
        inner_clean = re.sub(r'\s*server_name\s+[^;]+;\n', '', inner_clean)
        inner_clean = re.sub(r'\s*client_max_body_size\s+[^;]+;\n', '', inner_clean)

        https_block = (
            f"server {{\n"
            + ssl_directives
            + f"    client_max_body_size 100M;\n"
            + inner_clean
            + f"}}\n"
        )

        new_config = f"# SVQPanel — vhost SSL (generado automáticamente)\n\n{http_block}\n{https_block}"
        self._write_conf(new_config)

        # Red de seguridad: reinyectar /pma y /webmail si se perdieron al
        # reconstruir el bloque (se sirven en este mismo vhost).
        self._ensure_service_locations()

        # Verificar sintaxis
        rc, _, err = self.execute_command(["nginx", "-t"], check=False)
        if rc != 0:
            # Restaurar backup si falla
            self._restore_conf()
            raise RuntimeError(f"nginx -t falló tras añadir SSL: {err.strip()}")

    def _remove_ssl_from_vhost(self) -> None:
        """
        Intenta restaurar el backup o, si no existe, elimina los bloques SSL
        del vhost actual dejando solo HTTP.
        """
        backup = PANEL_NGINX_CONF + ".bak"
        if os.path.exists(backup):
            shutil.copy2(backup, PANEL_NGINX_CONF)
            logger.info("Vhost restaurado desde backup")
        else:
            # Fallback: reemplazar listen 443 por listen 80 y eliminar ssl_*
            config = self._read_conf()
            config = re.sub(r'\s*listen\s+443\s+ssl[^;]*;\n', '', config)
            config = re.sub(r'\s*listen\s+\[::\]:443\s+ssl[^;]*;\n', '', config)
            config = re.sub(r'\s*ssl_[^\n]+\n', '', config)
            # Cambiar server_name a default_server catch-all
            config = re.sub(
                r'server_name\s+[^;]+;',
                'server_name _;',
                config,
                count=1,
            )
            # Eliminar bloque redirect
            config = re.sub(
                r'server\s*\{[^}]*return\s+301[^}]*\}',
                '',
                config,
                flags=re.DOTALL,
            )
            self._write_conf(config)

        rc, _, err = self.execute_command(["nginx", "-t"], check=False)
        if rc != 0:
            raise RuntimeError(f"nginx -t falló al eliminar SSL: {err.strip()}")

    # ──────────────────────────────────────────────────────────────────────────
    # I/O de ficheros
    # ──────────────────────────────────────────────────────────────────────────

    def _read_conf(self) -> str:
        with open(PANEL_NGINX_CONF, "r") as fh:
            return fh.read()

    def _write_conf(self, config: str) -> None:
        """Escribe el fichero y asegura el enlace simbólico."""
        with open(PANEL_NGINX_CONF, "w") as fh:
            fh.write(config)
        if not os.path.exists(PANEL_NGINX_LINK):
            os.symlink(PANEL_NGINX_CONF, PANEL_NGINX_LINK)

    def _backup_conf(self) -> None:
        backup = PANEL_NGINX_CONF + ".bak"
        if os.path.exists(PANEL_NGINX_CONF):
            shutil.copy2(PANEL_NGINX_CONF, backup)

    def _restore_conf(self) -> None:
        backup = PANEL_NGINX_CONF + ".bak"
        if os.path.exists(backup):
            shutil.copy2(backup, PANEL_NGINX_CONF)

    @staticmethod
    def _extract_server_inner(config: str) -> str | None:
        """
        Extrae el contenido interior del primer bloque server { ... }
        respetando el anidamiento de llaves.
        """
        start = config.find("server {")
        if start == -1:
            start = config.find("server{")
        if start == -1:
            return None

        brace_start = config.index("{", start)
        depth = 0
        for i, ch in enumerate(config[brace_start:], start=brace_start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return config[brace_start + 1:i]
        return None

    @staticmethod
    def _php_fpm_socket() -> str | None:
        """Devuelve un socket PHP-FPM disponible (el compartido de mayor versión)."""
        import glob
        socks = sorted(glob.glob("/run/php/php*-fpm.sock"), reverse=True)
        return socks[0] if socks else None

    def _ensure_service_locations(self) -> None:
        """
        Reinyecta los bloques location de phpMyAdmin (/pma/) y Roundcube
        (/webmail/) en el vhost del panel si los servicios están instalados y
        el bloque no está presente. Idempotente: no duplica.

        Esto evita que una regeneración del vhost (p.ej. al activar SSL) deje
        sin acceso a phpMyAdmin/webmail, que se sirven en el mismo vhost.
        """
        sock = self._php_fpm_socket()
        if not sock:
            return
        try:
            config = self._read_conf()
        except Exception:
            return

        changed = False

        # phpMyAdmin
        if os.path.isdir("/var/www/pma") and "location /pma/" not in config:
            pma_block = (
                "\n    # phpMyAdmin — acceso autenticado via panel SVQPanel\n"
                "    location /pma/ {\n"
                "        root /var/www;\n"
                "        index index.php index.html;\n"
                "        location ~ \\.php$ {\n"
                "            include snippets/fastcgi-php.conf;\n"
                f"            fastcgi_pass unix:{sock};\n"
                "            fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;\n"
                "            include fastcgi_params;\n"
                "        }\n"
                "    }\n"
            )
            config = self._inject_into_https(config, pma_block)
            changed = True

        # Roundcube webmail
        if os.path.islink("/var/www/webmail") and "location /webmail" not in config:
            wm_block = (
                "\n    # Roundcube Webmail — autologin desde SVQPanel\n"
                "    location /webmail {\n"
                "        root /var/www;\n"
                "        index index.php;\n"
                "        location ~ ^/webmail/.*\\.php$ {\n"
                "            include snippets/fastcgi-php.conf;\n"
                f"            fastcgi_pass unix:{sock};\n"
                "            fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;\n"
                "            include fastcgi_params;\n"
                "        }\n"
                "    }\n"
            )
            config = self._inject_into_https(config, wm_block)
            changed = True

        if changed:
            self._write_conf(config)

    @staticmethod
    def _inject_into_https(config: str, block: str) -> str:
        """
        Inserta `block` justo antes del 'location / {' del bloque HTTPS
        (el último server{} del fichero, que es el de 443).
        """
        # Buscar el último 'location / {' (pertenece al server HTTPS)
        idx = config.rfind("    location / {")
        if idx == -1:
            return config
        return config[:idx] + block + "\n" + config[idx:]

    # ──────────────────────────────────────────────────────────────────────────
    # nginx y certbot
    # ──────────────────────────────────────────────────────────────────────────

    def _nginx_reload(self) -> None:
        # restart (no reload): un SIGHUP no siempre recarga los certificados SSL
        # nuevos en los workers; con un cert recién emitido/renovado el restart
        # garantiza que nginx sirva el certificado correcto y no uno cacheado.
        self.execute_command(["systemctl", "restart", "nginx"])

    def _get_cert_expiry(self, hostname: str) -> datetime | None:
        """Devuelve la fecha de expiración del certificado emitido."""
        cert_file = f"/etc/letsencrypt/live/{hostname}/fullchain.pem"
        if not os.path.exists(cert_file):
            return None
        try:
            rc, out, _ = self.execute_command(
                ["openssl", "x509", "-enddate", "-noout", "-in", cert_file],
                check=False,
            )
            # out: "notAfter=Jun 26 12:00:00 2025 GMT"
            if rc == 0 and "=" in out:
                date_str = out.strip().split("=", 1)[1]
                return datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z")
        except Exception:
            pass
        return None


import logging
import os
import re
from datetime import datetime
from .base import SystemManager
from .utils import SSL_PROTOCOLS, SSL_CIPHERS, SSL_SIGN_ALGS

logger = logging.getLogger(__name__)

# Ruta del vhost nginx que gestiona el acceso al panel
PANEL_NGINX_CONF = "/etc/nginx/sites-available/svqpanel"
PANEL_NGINX_LINK = "/etc/nginx/sites-enabled/svqpanel"

# Puerto en el que escucha uvicorn internamente
PANEL_BACKEND_PORT = int(os.environ.get("PANEL_PORT", 8001))

# Puerto PÚBLICO dedicado en el que nginx sirve el panel (no 80/443, para poder
# cerrarlo en el firewall perimetral). Se detecta del vhost actual si existe,
# con fallback a PANEL_WEB_PORT del entorno o 8083.
def _detect_panel_web_port() -> int:
    try:
        with open(PANEL_NGINX_CONF) as fh:
            txt = fh.read()
        # Buscar el primer 'listen <puerto>' que NO sea 80/443
        for m in re.finditer(r'listen\s+(?:\[::\]:)?(\d+)', txt):
            p = int(m.group(1))
            if p not in (80, 443):
                return p
    except (OSError, ValueError):
        pass
    return int(os.environ.get("PANEL_WEB_PORT", 8083))

PANEL_WEB_PORT = _detect_panel_web_port()

# Puerto público del frontend (Vite build servido por nginx)
PANEL_FRONTEND_PATH = "/opt/svqpanel/frontend/dist"

# Proxy a la UI web de Rspamd (controller en 127.0.0.1:11334).
# Debe incluirse en todas las plantillas de vhost, si no /rspamd/ da 404.
RSPAMD_LOCATION = """    # Rspamd web UI
    location /rspamd/ {
        proxy_pass http://127.0.0.1:11334/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
"""


def _php_fpm_socket() -> str | None:
    """Devuelve un socket PHP-FPM compartido disponible (mayor versión)."""
    import glob
    socks = sorted(glob.glob("/run/php/php*-fpm.sock"), reverse=True)
    return socks[0] if socks else None


def _service_locations() -> str:
    """
    Genera los bloques location de phpMyAdmin (/pma/) y Roundcube (/webmail/)
    si los servicios están instalados. Se incluyen en TODAS las plantillas de
    vhost del panel para que no se pierdan al regenerar (igual que rspamd).
    """
    sock = _php_fpm_socket()
    if not sock:
        return ""
    blocks = []
    if os.path.isdir("/var/www/pma"):
        blocks.append(
            "    # phpMyAdmin — acceso autenticado via panel SVQPanel\n"
            "    location /pma/ {\n"
            "        root /var/www;\n"
            "        index index.php index.html;\n"
            "        location ~ \\.php$ {\n"
            "            include snippets/fastcgi-php.conf;\n"
            f"            fastcgi_pass unix:{sock};\n"
            "            fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;\n"
            "            include fastcgi_params;\n"
            "        }\n"
            "    }\n"
        )
    if os.path.islink("/var/www/webmail") or os.path.isdir("/var/www/roundcube/public_html"):
        # Roundcube 1.7+: el docroot público es public_html/.
        # Truco nginx: root /var/www + symlink /var/www/webmailpub → public_html
        # + symlink /var/www/webmailpub/webmail → public_html.
        # Así SCRIPT_FILENAME = /var/www/webmailpub + $fastcgi_script_name
        # (/webmail/index.php) = /var/www/webmailpub/webmail/index.php → existe.
        import subprocess as _sp
        _sp.run(["mkdir", "-p", "/var/www/webmailpub"], check=False)
        _sp.run(["ln", "-sfn", "/var/www/webmail/public_html", "/var/www/webmailpub/webmail"],
                check=False)
        blocks.append(
            "    # Roundcube Webmail — autologin desde SVQPanel\n"
            "    location = /webmail { return 301 /webmail/; }\n"
            "    location /webmail/ {\n"
            "        root /var/www;\n"
            "        index index.php;\n"
            "        location ~ ^/webmail/static\\.php {\n"
            "            fastcgi_split_path_info ^(/webmail/static\\.php)(/.+)$;\n"
            f"            fastcgi_pass unix:{sock};\n"
            "            include fastcgi_params;\n"
            "            fastcgi_param SCRIPT_FILENAME /var/www/webmail/public_html/static.php;\n"
            "            fastcgi_param PATH_INFO $fastcgi_path_info;\n"
            "            fastcgi_param SCRIPT_NAME /webmail/static.php;\n"
            "        }\n"
            "        location ~ \\.php$ {\n"
            "            include snippets/fastcgi-php.conf;\n"
            f"            fastcgi_pass unix:{sock};\n"
            "            fastcgi_param SCRIPT_FILENAME /var/www/webmailpub$fastcgi_script_name;\n"
            "            include fastcgi_params;\n"
            "        }\n"
            "        location ~ ^/webmail/(config|logs|temp|vendor/bin)/ {\n"
            "            deny all;\n"
            "        }\n"
            "    }\n"
        )
    return ("\n" + "\n".join(blocks)) if blocks else ""


def _validate_hostname(hostname: str) -> bool:
    """Valida que el hostname sea un FQDN razonable."""
    pattern = r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
    return bool(re.match(pattern, hostname))


class PanelSSLManager(SystemManager):
    """Gestiona el certificado SSL del propio hostname del panel."""

    def __init__(self):
        super().__init__(require_root=True)

    # ──────────────────────────────────────────────────────────────────────────
    # Emisión
    # ──────────────────────────────────────────────────────────────────────────

    def issue_ssl(self, hostname: str, email: str, force_https: bool = True) -> dict:
        """
        Emite un certificado Let's Encrypt para el hostname del panel.

        Args:
            hostname:    FQDN del panel (ej: panel.midominio.com)
            email:       Email para Let's Encrypt
            force_https: Si True, configura nginx para redirigir HTTP → HTTPS

        Returns:
            {"success": True, "hostname": "...", "expires": "..."}
        """
        if not _validate_hostname(hostname):
            raise ValueError(f"Hostname inválido: {hostname}")

        logger.info(f"Emitiendo SSL para el panel en {hostname}")

        # 1. Aseguramos un vhost HTTP básico para que certbot pueda validar.
        #    El bloque 'listen 80' sirve /.well-known/acme-challenge desde
        #    /var/www/html (el panel real va en su puerto dedicado).
        os.makedirs("/var/www/html/.well-known/acme-challenge", exist_ok=True)
        self._write_nginx_http_only(hostname)
        self._nginx_reload()

        # 2. Emitir con certbot --webroot (no toca nginx; valida por el puerto
        #    80 que ya queda abierto para los sitios de clientes). Es robusto
        #    aunque el panel se sirva en un puerto dedicado.
        rc, out, err = self.execute_command([
            "certbot", "certonly",
            "--webroot", "-w", "/var/www/html",
            "-d", hostname,
            "--non-interactive",
            "--agree-tos",
            "-m", email,
        ], check=False)

        if rc != 0:
            logger.error(f"certbot falló:\n{err}")
            raise RuntimeError(f"certbot falló (código {rc}): {err.strip()}")

        # 3. Reescribir vhost nginx con SSL (y redirect si force_https)
        self._write_nginx_ssl(hostname, force_https)
        self._nginx_reload()

        # 4. Leer fecha de expiración del certificado
        expires = self._get_cert_expiry(hostname)

        # 5. Persistir el estado en la BD del panel. Así el estado queda correcto
        #    tanto si se emite desde la UI como desde el install (que llama a este
        #    manager directamente). Sin esto, la UI mostraría "Sin SSL" pese a
        #    tener el cert. No debe romper una emisión ya exitosa.
        self._persist_ssl_state(True, hostname, expires, force_https)

        logger.info(f"SSL del panel emitido correctamente para {hostname}")
        return {
            "success": True,
            "hostname": hostname,
            "expires": expires.isoformat() if expires else None,
        }

    def _persist_ssl_state(self, enabled: bool, hostname: str | None,
                           expires, force_https: bool) -> None:
        """Refleja el estado del SSL del panel en settings (idempotente).

        Tolerante a fallos: si la BD no está disponible no debe abortar la
        emisión/revocación (que ya ocurrió a nivel de sistema). El estado se
        puede recuperar luego con `python -m api.cli sync_panel_ssl`.
        """
        try:
            from api.models.database import SessionLocal, load_all_models
            load_all_models()
            from api.routes.settings import get_or_create_settings
            db = SessionLocal()
            try:
                s = get_or_create_settings(db)
                s.ssl_panel_enabled = enabled
                if hostname:
                    s.panel_hostname = hostname
                s.force_https = bool(force_https)
                s.ssl_panel_expires = expires if enabled else None
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning("No se pudo persistir el estado SSL en settings: %s", e)

    # ──────────────────────────────────────────────────────────────────────────
    # Revocación / eliminación
    # ──────────────────────────────────────────────────────────────────────────

    def revoke_ssl(self, hostname: str) -> dict:
        """
        Revoca el certificado del panel y vuelve a configuración HTTP.

        Args:
            hostname: FQDN del panel

        Returns:
            {"success": True}
        """
        if not _validate_hostname(hostname):
            raise ValueError(f"Hostname inválido: {hostname}")

        logger.info(f"Revocando SSL del panel para {hostname}")

        self.execute_command([
            "certbot", "revoke",
            "--cert-name", hostname,
            "--non-interactive",
        ], check=False)

        self.execute_command([
            "certbot", "delete",
            "--cert-name", hostname,
            "--non-interactive",
        ], check=False)

        # Volver a HTTP simple
        self._write_nginx_http_only(hostname)
        self._nginx_reload()

        # Reflejar en la BD que ya no hay SSL.
        self._persist_ssl_state(False, hostname, None, False)

        return {"success": True}

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers nginx
    # ──────────────────────────────────────────────────────────────────────────

    def _write_nginx_http_only(self, hostname: str) -> None:
        """
        Vhost básico (solo HTTP) para el panel en su puerto dedicado.
        El puerto 80 queda reservado para la validación ACME de certbot;
        el panel se sirve en PANEL_WEB_PORT.
        """
        config = f"""# SVQPanel — vhost HTTP (pre-SSL o fallback)
# Puerto 80: SOLO para la validación ACME de Let's Encrypt (no sirve el panel).
server {{
    listen 80;
    server_name {hostname};
    location /.well-known/acme-challenge/ {{
        root /var/www/html;
    }}
    location / {{ return 404; }}
}}

# El panel se sirve en su puerto dedicado.
server {{
    listen {PANEL_WEB_PORT};
    server_name {hostname} _;

    root {PANEL_FRONTEND_PATH};
    index index.html;

    error_page 502 503 504 /502.html;
    location = /502.html {{ internal; root {PANEL_FRONTEND_PATH}; }}

    location / {{
        include snippets/svqpanel-whitelist.conf;
        try_files $uri $uri/ /index.html;
    }}

{RSPAMD_LOCATION}{_service_locations()}
    # API backend
    location /api/ {{
        include snippets/svqpanel-whitelist.conf;
        proxy_pass http://127.0.0.1:{PANEL_BACKEND_PORT};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
"""
        self._write_conf(config)

    def _write_nginx_ssl(self, hostname: str, force_https: bool) -> None:
        """Escribe el vhost nginx con SSL habilitado."""
        cert_path = f"/etc/letsencrypt/live/{hostname}/fullchain.pem"
        key_path = f"/etc/letsencrypt/live/{hostname}/privkey.pem"

        # Puerto 80: NO lo gestiona el vhost del panel. El tráfico HTTP (por IP
        # o por hostname) lo sirve el vhost 'svqpanel-welcome' (default_server),
        # que muestra una página de bienvenida neutra y atiende el ACME challenge.
        # El panel se sirve EXCLUSIVAMENTE por HTTPS en su puerto dedicado.
        http_block = ""

        # Puerto 443: bienvenida por HTTPS (sin puerto). Como ya tenemos cert del
        # hostname, servimos aquí la misma página neutra que en el 80. Así
        # https://hostname (sin :puerto) carga la bienvenida en vez de timeout.
        # El panel sigue solo en su puerto dedicado. Es default_server del 443.
        welcome_https_block = f"""
server {{
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    http2 on;
    server_name _;

    ssl_certificate     {cert_path};
    ssl_certificate_key {key_path};
    ssl_protocols       {SSL_PROTOCOLS};
    ssl_ciphers         {SSL_CIPHERS};
    ssl_prefer_server_ciphers on;
    ssl_conf_command Signature_Algorithms {SSL_SIGN_ALGS};

    root /var/www/html;
    index index.html;
    location / {{
        try_files $uri $uri/ =200;
    }}
}}
"""

        # El panel HTTPS se sirve en el puerto dedicado.
        https_block = f"""
server {{
    listen {PANEL_WEB_PORT} ssl;
    listen [::]:{PANEL_WEB_PORT} ssl;
    http2 on;
    server_name {hostname} _;

    ssl_certificate     {cert_path};
    ssl_certificate_key {key_path};
    ssl_protocols       {SSL_PROTOCOLS};
    ssl_ciphers         {SSL_CIPHERS};
    ssl_prefer_server_ciphers on;
    ssl_conf_command Signature_Algorithms {SSL_SIGN_ALGS};
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 10m;
    # NO enviamos HSTS: el panel corre en un puerto no estándar ({PANEL_WEB_PORT}).
    # HSTS forzaría al navegador a usar HTTPS:443 para el hostname (sin puerto),
    # donde no hay nada escuchando -> timeout. Sin HSTS, http(s)://hostname (sin
    # puerto) cae en el vhost de bienvenida y el panel sigue solo en su puerto.

    # Si llega HTTP plano a este puerto SSL (p.ej. http://host:{PANEL_WEB_PORT}),
    # nginx devuelve 497; lo redirigimos a HTTPS en el mismo puerto en vez de
    # mostrar "400 Bad Request: plain HTTP request sent to HTTPS port".
    error_page 497 =301 https://$host:{PANEL_WEB_PORT}$request_uri;
    error_page 502 503 504 /502.html;
    location = /502.html {{ internal; root {PANEL_FRONTEND_PATH}; }}

    root {PANEL_FRONTEND_PATH};
    index index.html;

    location / {{
        include snippets/svqpanel-whitelist.conf;
        try_files $uri $uri/ /index.html;
    }}

{RSPAMD_LOCATION}{_service_locations()}
    location /api/ {{
        include snippets/svqpanel-whitelist.conf;
        proxy_pass http://127.0.0.1:{PANEL_BACKEND_PORT};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Port {PANEL_WEB_PORT};
    }}
}}
"""

        config = (
            f"# SVQPanel — vhost SSL generado automáticamente\n"
            f"{http_block}\n{welcome_https_block}\n{https_block}"
        )
        self._write_conf(config)

    def _write_conf(self, config: str) -> None:
        """Escribe el fichero de configuración y activa el enlace simbólico."""
        with open(PANEL_NGINX_CONF, "w") as fh:
            fh.write(config)

        # Crear enlace simbólico si no existe
        if not os.path.exists(PANEL_NGINX_LINK):
            os.symlink(PANEL_NGINX_CONF, PANEL_NGINX_LINK)

        # Verificar sintaxis antes de recargar
        rc, _, err = self.execute_command(["nginx", "-t"], check=False)
        if rc != 0:
            raise RuntimeError(f"nginx -t falló: {err.strip()}")

    def _nginx_reload(self) -> None:
        # restart (no reload): un SIGHUP no siempre recarga los certificados SSL
        # nuevos en los workers; con un cert recién emitido/renovado el restart
        # garantiza que nginx sirva el certificado correcto y no uno cacheado.
        self.execute_command(["systemctl", "restart", "nginx"])

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers certbot
    # ──────────────────────────────────────────────────────────────────────────

    def _get_cert_expiry(self, hostname: str) -> datetime | None:
        """Devuelve la fecha de expiración del certificado emitido."""
        cert_file = f"/etc/letsencrypt/live/{hostname}/fullchain.pem"
        if not os.path.exists(cert_file):
            return None
        try:
            rc, out, _ = self.execute_command(
                ["openssl", "x509", "-enddate", "-noout", "-in", cert_file],
                check=False,
            )
            # out: "notAfter=Jun 26 12:00:00 2025 GMT"
            if rc == 0 and "=" in out:
                date_str = out.strip().split("=", 1)[1]
                return datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z")
        except Exception:
            pass
        return None
