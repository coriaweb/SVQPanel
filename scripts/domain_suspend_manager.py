"""
Gestión de suspensión/reactivación individual de dominios.

Cuando un dominio se suspende:
 - Se renombra el symlink de sites-enabled → domain.conf.suspended
 - Nginx sirve un 503 con página de mantenimiento
 - El dominio sigue en BD, solo desaparece de nginx

Cuando se reactiva:
 - Se restaura el symlink
 - Se recarga nginx
"""

import logging
import os
from pathlib import Path
from .base import SystemManager
from .utils import get_nginx_config_path, reload_nginx

logger = logging.getLogger(__name__)

SITES_ENABLED  = "/etc/nginx/sites-enabled"
SITES_AVAILABLE = "/etc/nginx/sites-available"

# Plantilla HTML 503 para dominio suspendido
_SUSPENDED_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Sitio suspendido</title>
  <style>
    body{font-family:sans-serif;display:flex;align-items:center;justify-content:center;
         min-height:100vh;margin:0;background:#f8f9fa}
    .box{text-align:center;padding:2rem;max-width:480px}
    h1{font-size:3rem;color:#dc3545;margin:0}
    h2{color:#333;font-weight:400}
    p{color:#666}
  </style>
</head>
<body>
  <div class="box">
    <h1>503</h1>
    <h2>Sitio temporalmente suspendido</h2>
    <p>Este dominio ha sido suspendido. Contacta con el soporte para más información.</p>
  </div>
</body>
</html>
"""

_SUSPENDED_NGINX = """\
# SVQPanel — Dominio suspendido: {domain}
server {{
    listen 80;
    server_name {domain} www.{domain};
    return 503;
}}
server {{
    listen 443 ssl http2;
    server_name {domain} www.{domain};
    ssl_certificate     /etc/nginx/snippets/self-signed.crt;
    ssl_certificate_key /etc/nginx/snippets/self-signed.key;
    return 503;
}}
error_page 503 /suspended.html;
location = /suspended.html {{
    root /var/www/svqpanel-suspended;
    internal;
}}
"""


class DomainSuspendManager(SystemManager):
    def __init__(self):
        super().__init__(require_root=True)

    def _ensure_suspended_page(self):
        """Crea la página 503 estática si no existe."""
        html_dir = Path("/var/www/svqpanel-suspended")
        html_dir.mkdir(parents=True, exist_ok=True)
        html_file = html_dir / "suspended.html"
        if not html_file.exists():
            html_file.write_text(_SUSPENDED_HTML)

    def suspend_domain(self, domain: str) -> dict:
        """
        Suspende el dominio: reemplaza el config de nginx por uno que devuelve 503.
        Guarda el config original en sites-available/{domain}.active
        """
        self._ensure_suspended_page()

        available = Path(SITES_AVAILABLE) / domain
        active_backup = Path(SITES_AVAILABLE) / f"{domain}.active"
        enabled_link = Path(SITES_ENABLED) / domain

        # Backup del config activo
        if available.exists() and not active_backup.exists():
            rc, _, err = self.execute_command(
                ["cp", str(available), str(active_backup)], check=False
            )

        # Escribir config de suspensión
        # Verificar si hay cert SSL real
        ssl_cert = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
        ssl_key  = f"/etc/letsencrypt/live/{domain}/privkey.pem"

        if os.path.exists(ssl_cert):
            suspended_conf = (
                f"# SVQPanel — Dominio suspendido: {domain}\n"
                f"server {{\n"
                f"    listen 80;\n"
                f"    server_name {domain} www.{domain};\n"
                f"    return 503;\n"
                f"}}\n"
                f"server {{\n"
                f"    listen 443 ssl http2;\n"
                f"    server_name {domain} www.{domain};\n"
                f"    ssl_certificate {ssl_cert};\n"
                f"    ssl_certificate_key {ssl_key};\n"
                f"    return 503;\n"
                f"}}\n"
                f"error_page 503 /suspended.html;\n"
            )
        else:
            suspended_conf = (
                f"# SVQPanel — Dominio suspendido: {domain}\n"
                f"server {{\n"
                f"    listen 80;\n"
                f"    server_name {domain} www.{domain};\n"
                f"    return 503;\n"
                f"}}\n"
                f"error_page 503 /suspended.html;\n"
            )

        available.write_text(suspended_conf)

        # Asegurarse de que el symlink en sites-enabled apunta al available
        if not enabled_link.exists():
            self.execute_command(
                ["ln", "-sf", str(available), str(enabled_link)], check=False
            )

        reload_nginx()
        return {"success": True, "message": f"Dominio {domain} suspendido"}

    def unsuspend_domain(self, domain: str) -> dict:
        """
        Reactiva el dominio restaurando el config original.
        """
        available    = Path(SITES_AVAILABLE) / domain
        active_backup = Path(SITES_AVAILABLE) / f"{domain}.active"
        enabled_link = Path(SITES_ENABLED) / domain

        if active_backup.exists():
            self.execute_command(
                ["cp", str(active_backup), str(available)], check=False
            )
            active_backup.unlink(missing_ok=True)
        else:
            # No hay backup — puede que el dominio no tuviera config, no forzamos
            return {
                "success": False,
                "message": f"No se encontró el config original para {domain}. "
                           "Puede que el dominio no estuviera en nginx."
            }

        # Restaurar symlink si no existe
        if not enabled_link.exists():
            self.execute_command(
                ["ln", "-sf", str(available), str(enabled_link)], check=False
            )

        reload_nginx()
        return {"success": True, "message": f"Dominio {domain} reactivado"}
