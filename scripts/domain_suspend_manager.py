"""
Gestión de suspensión/reactivación individual de dominios.
"""

import logging
import os
from pathlib import Path
from .base import SystemManager
from .utils import get_nginx_config_path, reload_nginx

logger = logging.getLogger(__name__)

SITES_ENABLED   = "/etc/nginx/sites-enabled"
SITES_AVAILABLE = "/etc/nginx/sites-available"
SUSPENDED_DIR   = "/var/www/svqpanel-suspended"

_SUSPENDED_HTML = '''<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Sitio suspendido</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #0f1117;
      color: #e2e8f0;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 1.5rem;
    }
    .card {
      background: #1a1d27;
      border: 1px solid #2d3148;
      border-radius: 16px;
      padding: 3rem 2.5rem;
      max-width: 480px;
      width: 100%;
      text-align: center;
      box-shadow: 0 20px 60px rgba(0,0,0,.5);
    }
    .icon {
      width: 64px; height: 64px;
      background: rgba(239,68,68,.12);
      border: 1px solid rgba(239,68,68,.25);
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      margin: 0 auto 1.5rem;
      font-size: 1.75rem;
    }
    h1 {
      font-size: 1.5rem;
      font-weight: 600;
      color: #f1f5f9;
      margin-bottom: .5rem;
    }
    p {
      font-size: .95rem;
      color: #94a3b8;
      line-height: 1.6;
      margin-bottom: 1.75rem;
    }
    .badge {
      display: inline-block;
      background: rgba(239,68,68,.1);
      border: 1px solid rgba(239,68,68,.2);
      color: #f87171;
      font-size: .75rem;
      font-weight: 600;
      letter-spacing: .05em;
      text-transform: uppercase;
      padding: .3rem .8rem;
      border-radius: 999px;
      margin-bottom: 1.5rem;
    }
    .divider {
      border: none;
      border-top: 1px solid #2d3148;
      margin: 1.5rem 0;
    }
    .contact {
      font-size: .82rem;
      color: #64748b;
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">&#128683;</div>
    <span class="badge">Suspendido</span>
    <h1>Este sitio ha sido suspendido</h1>
    <p>El dominio ha sido suspendido temporalmente por el administrador del servidor.</p>
    <hr class="divider">
    <p class="contact">Si eres el propietario, contacta con el soporte para reactivarlo.</p>
  </div>
</body>
</html>'''


def _server_block(domain: str, listen: str, ssl_lines: str = "") -> str:
    # Escuchar en IPv4 E IPv6: si el dominio tiene AAAA, el navegador entra por
    # IPv6 y, sin el listen [::], nginx cae al server por defecto y presenta un
    # cert ajeno → ERR_CERT_COMMON_NAME_INVALID en la página de suspensión.
    return (
        f"server {{\n"
        f"    listen {listen};\n"
        f"    listen [::]:{listen};\n"
        f"{ssl_lines}"
        f"    server_name {domain} www.{domain};\n"
        f"    error_page 503 /suspended.html;\n"
        f"    location = /suspended.html {{\n"
        f"        root {SUSPENDED_DIR};\n"
        f"        internal;\n"
        f"    }}\n"
        f"    location / {{ return 503; }}\n"
        f"}}\n"
    )


class DomainSuspendManager(SystemManager):
    def __init__(self):
        super().__init__(require_root=True)

    def _ensure_suspended_page(self):
        html_dir = Path(SUSPENDED_DIR)
        html_dir.mkdir(parents=True, exist_ok=True)
        (html_dir / "suspended.html").write_text(_SUSPENDED_HTML)

    def suspend_domain(self, domain: str) -> dict:
        self._ensure_suspended_page()

        available    = Path(SITES_AVAILABLE) / domain
        active_backup = Path(SITES_AVAILABLE) / f"{domain}.active"
        enabled_link = Path(SITES_ENABLED) / domain

        if available.exists() and not active_backup.exists():
            self.execute_command(["cp", str(available), str(active_backup)], check=False)

        ssl_cert = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
        ssl_key  = f"/etc/letsencrypt/live/{domain}/privkey.pem"
        has_ssl  = os.path.exists(ssl_cert)

        conf = f"# SVQPanel — Dominio suspendido: {domain}\n"
        conf += _server_block(domain, "80")
        if has_ssl:
            ssl_lines = (
                f"    ssl_certificate     {ssl_cert};\n"
                f"    ssl_certificate_key {ssl_key};\n"
                f"    http2 on;\n"
            )
            conf += _server_block(domain, "443 ssl", ssl_lines)

        available.write_text(conf)

        if not enabled_link.exists():
            self.execute_command(["ln", "-sf", str(available), str(enabled_link)], check=False)

        reload_nginx()
        return {"success": True, "message": f"Dominio {domain} suspendido"}

    def unsuspend_domain(self, domain: str) -> dict:
        available     = Path(SITES_AVAILABLE) / domain
        active_backup = Path(SITES_AVAILABLE) / f"{domain}.active"
        enabled_link  = Path(SITES_ENABLED) / domain

        if active_backup.exists():
            self.execute_command(["cp", str(active_backup), str(available)], check=False)
            active_backup.unlink(missing_ok=True)
        else:
            return {
                "success": False,
                "message": f"No se encontró el config original para {domain}."
            }

        if not enabled_link.exists():
            self.execute_command(["ln", "-sf", str(available), str(enabled_link)], check=False)

        reload_nginx()
        return {"success": True, "message": f"Dominio {domain} reactivado"}
