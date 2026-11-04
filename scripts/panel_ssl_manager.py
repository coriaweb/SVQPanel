"""
Panel SSL Manager — emite y revoca el certificado SSL para el propio hostname del panel.

Genera el vhost nginx del panel (puerto dedicado) desde plantilla: HTTP-only
antes de tener cert y SSL después. ensure_panel_vhost_limits() repara in situ
los vhosts ya generados (límite de subida, timeouts de /pma, cabeceras).
"""

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


# Directivas a nivel server del panel. Sin client_max_body_size nginx aplica su
# 1 MB por defecto y corta con 413 los imports de phpMyAdmin, las subidas del
# gestor de archivos y los .tar de migración (install.sh ponía 6g, pero estas
# plantillas reescriben el vhost entero al emitir el SSL y lo perdían).
# El CSP NO va aquí: /webmail, /pma y /rspamd rompen con un CSP estricto.
PANEL_UPLOAD_LIMIT = "6g"
PANEL_SERVER_COMMON = f"""    client_max_body_size {PANEL_UPLOAD_LIMIT};

    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "geolocation=(), microphone=(), camera=(), payment=()" always;
"""

# Imports/exports grandes de phpMyAdmin: el fastcgi_read_timeout por defecto
# (60s) corta antes que el max_execution_time de PHP.
PMA_FASTCGI_TIMEOUT = "            fastcgi_read_timeout 600s;\n"

# phpMyAdmin fija session_cache_limiter('private') y su redirección al login
# (sesión caducada) sale con "Cache-Control: private, max-age=10800": el
# navegador la guardaba 3 h y, aunque se volviera a entrar bien desde el panel,
# «Importar» seguía saltando al login sin preguntar al servidor (Oskarbi,
# nov 2026). Sus páginas ya mandan no-cache; aquí se fuerza no-store en todas.
# Un add_header dentro del location anula los del server: se repiten aquí.
PMA_NO_CACHE = (
    "            fastcgi_hide_header Cache-Control;\n"
    "            fastcgi_hide_header Expires;\n"
    "            add_header Cache-Control \"no-store, no-cache, must-revalidate\" always;\n"
    + "".join("        " + ln + "\n" for ln in PANEL_SERVER_COMMON.splitlines()
              if ln.strip().startswith("add_header"))
)


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
            + PMA_FASTCGI_TIMEOUT + PMA_NO_CACHE +
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


def _server_blocks(text: str) -> list[tuple[int, int]]:
    """(inicio, fin) de cada bloque `server { ... }` de primer nivel."""
    blocks = []
    for m in re.finditer(r'(?m)^server\s*\{', text):
        depth = 0
        for i in range(text.index("{", m.start()), len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append((m.start(), i + 1))
                    break
    return blocks


def patch_panel_vhost(text: str) -> str:
    """Añade al server del panel (el que tiene /api/) lo que le falte de
    PANEL_SERVER_COMMON y el timeout de /pma. Respeta un client_max_body_size
    o una cabecera ya presentes (puestos a mano). Idempotente."""
    for start, end in reversed(_server_blocks(text)):
        block = text[start:end]
        if "location /api/" not in block:
            continue
        # Clave de cada directiva: el nombre, o "add_header Cabecera".
        def key(ln):
            w = ln.split()
            return " ".join(w[:2]) if w[0] == "add_header" else w[0]
        # Sin el location /pma/ (repite las cabeceras dentro) para no confundirlas
        # con las del server.
        outer = re.sub(r"location /pma/ \{.*?\n    \}\n", "", block, flags=re.S)
        missing = [ln for ln in PANEL_SERVER_COMMON.splitlines()
                   if ln.strip() and key(ln) not in outer]
        if missing:
            m = re.search(r'\n[ \t]*server_name[^;]*;\n', block)
            at = m.end() if m else block.index("{") + 2
            block = block[:at] + "\n" + "\n".join(missing) + "\n" + block[at:]
        pma = block.find("location /pma/")
        if pma != -1:
            close = block.find("\n    }\n", pma)
            inc = block.find("include fastcgi_params;\n", pma, close)
            if close != -1 and inc != -1:
                at = inc + len("include fastcgi_params;\n")
                add = ""
                if "fastcgi_read_timeout" not in block[pma:close]:
                    add += PMA_FASTCGI_TIMEOUT
                if "fastcgi_hide_header Cache-Control" not in block[pma:close]:
                    add += PMA_NO_CACHE
                block = block[:at] + add + block[at:]
        text = text[:start] + block + text[end:]
    return text


def ensure_panel_vhost_limits() -> bool:
    """Repara in situ el vhost del panel ya generado (ver patch_panel_vhost).
    Valida con nginx -t y restaura el original si falla. True si cambió algo."""
    import subprocess
    try:
        with open(PANEL_NGINX_CONF) as fh:
            old = fh.read()
    except OSError:
        return False
    new = patch_panel_vhost(old)
    if new == old:
        return False
    with open(PANEL_NGINX_CONF, "w") as fh:
        fh.write(new)
    test = subprocess.run(["nginx", "-t"], capture_output=True, text=True, timeout=30)
    if test.returncode != 0:
        with open(PANEL_NGINX_CONF, "w") as fh:
            fh.write(old)
        raise RuntimeError(f"nginx -t falló, vhost restaurado: {test.stderr.strip()}")
    subprocess.run(["systemctl", "reload", "nginx"], check=False, timeout=30)
    return True


def _validate_hostname(hostname: str) -> bool:
    """Valida que el hostname sea un FQDN razonable."""
    pattern = r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
    return bool(re.match(pattern, hostname))


class PanelSSLManager(SystemManager):
    """Gestiona el certificado SSL del propio hostname del panel."""

    def __init__(self):
        super().__init__(require_root=True)

    def check_acme_reachable(self, hostname: str, email: str) -> tuple:
        """Prueba de emisión contra el staging de Let's Encrypt (--dry-run).

        Que el DNS apunte aquí no basta: un cortafuegos perimetral (Proxmox,
        el del proveedor…) puede cerrar el puerto 80 y desde el propio
        servidor no se ve. El staging valida DESDE FUERA igual que producción,
        sin gastar los límites de fallos del certificado real.

        Returns: (ok, detalle del error de certbot)
        """
        if not _validate_hostname(hostname):
            return False, f"Hostname inválido: {hostname}"
        os.makedirs("/var/www/html/.well-known/acme-challenge", exist_ok=True)
        self._write_nginx_http_only(hostname)
        self._nginx_reload()
        rc, out, err = self.execute_command([
            "certbot", "certonly", "--dry-run",
            "--webroot", "-w", "/var/www/html",
            "-d", hostname,
            "--non-interactive",
            "--agree-tos",
            "-m", email,
        ], check=False)
        return rc == 0, (err or out).strip()

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

{PANEL_SERVER_COMMON}
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
    ssl_conf_command SignatureAlgorithms {SSL_SIGN_ALGS};

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
    ssl_conf_command SignatureAlgorithms {SSL_SIGN_ALGS};
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 10m;
    # NO enviamos HSTS: el panel corre en un puerto no estándar ({PANEL_WEB_PORT}).
    # HSTS forzaría al navegador a usar HTTPS:443 para el hostname (sin puerto),
    # donde no hay nada escuchando -> timeout. Sin HSTS, http(s)://hostname (sin
    # puerto) cae en el vhost de bienvenida y el panel sigue solo en su puerto.

{PANEL_SERVER_COMMON}
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
