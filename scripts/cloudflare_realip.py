"""
Cloudflare real_ip para nginx.

Cuando un dominio está tras Cloudflare, nginx ve la IP de Cloudflare (172.x,
104.2x…) en vez de la del visitante real. Eso rompe:
  - los rate-limit por IP (limit_req $binary_remote_addr) → limitan por IP de CF,
    no por atacante → esquivable + falsos positivos a usuarios legítimos que
    comparten IP de CF con el bot.
  - fail2ban/CrowdSec → banearían a Cloudflare (inútil o contraproducente).
  - los logs → registran la IP de CF, no la real.

La solución estándar: declarar los rangos de Cloudflare como proxies de confianza
(`set_real_ip_from`) y tomar la IP real de la cabecera `CF-Connecting-IP`. A partir
de ahí `$remote_addr`/`$binary_remote_addr` pasan a ser la IP real del visitante.

Este módulo descarga los rangos oficiales (https://www.cloudflare.com/ips-v4 y
ips-v6) y escribe un único conf.d global. Idempotente: si el contenido no cambia,
no reescribe ni recarga nginx. Si no hay red, cae a una lista embebida conocida
para que un install/update nunca quede sin protección.
"""
from __future__ import annotations

import ipaddress
import logging
import subprocess
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

CONF_PATH = Path("/etc/nginx/conf.d/svqpanel-cloudflare-realip.conf")

CF_V4_URL = "https://www.cloudflare.com/ips-v4"
CF_V6_URL = "https://www.cloudflare.com/ips-v6"

# Fallback embebido (rangos publicados por Cloudflare). Solo se usa si la
# descarga falla, para no dejar el conf.d vacío en un install sin red.
_FALLBACK_V4 = [
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
]
_FALLBACK_V6 = [
    "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32",
    "2405:8100::/32", "2a06:98c0::/29", "2c0f:f248::/32",
]


def _fetch(url: str, timeout: int = 15) -> list[str]:
    """Descarga una lista de rangos (uno por línea). [] si falla."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SVQPanel"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
        return [ln.strip() for ln in body.splitlines() if ln.strip()]
    except Exception as e:
        logger.warning(f"No se pudo descargar {url}: {e}")
        return []


def _valid_cidrs(raw: list[str]) -> list[str]:
    """Filtra a CIDRs válidos (descarta basura/HTML inesperado)."""
    out = []
    for item in raw:
        try:
            ipaddress.ip_network(item, strict=False)
            out.append(item)
        except ValueError:
            continue
    return out


def _render(v4: list[str], v6: list[str]) -> str:
    lines = [
        "# SVQPanel — real_ip de Cloudflare (generado por scripts/cloudflare_realip.py)",
        "# NO editar a mano: se regenera por cron mensual (refresh_cloudflare_ips).",
        "# Recupera la IP real del visitante tras Cloudflare para rate-limit, logs",
        "# y fail2ban/CrowdSec. Rangos: https://www.cloudflare.com/ips",
        "",
    ]
    for cidr in v4:
        lines.append(f"set_real_ip_from {cidr};")
    for cidr in v6:
        lines.append(f"set_real_ip_from {cidr};")
    lines += [
        "",
        "real_ip_header CF-Connecting-IP;",
        "real_ip_recursive on;",
        "",
    ]
    return "\n".join(lines)


def _reload_nginx() -> bool:
    """Valida y recarga nginx. Devuelve False si el test falla."""
    try:
        test = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
        if test.returncode != 0:
            logger.error(f"nginx -t falló, no se recarga: {test.stderr.strip()}")
            return False
        subprocess.run(["systemctl", "reload", "nginx"], check=False)
        return True
    except FileNotFoundError:
        logger.warning("nginx no encontrado; se escribió el conf pero no se recargó")
        return False


def refresh(force: bool = False) -> bool:
    """Descarga los rangos de Cloudflare y (re)escribe el conf.d. Idempotente:
    si el contenido no cambia y no se fuerza, no recarga nginx.

    Devuelve True si el estado quedó correcto (aunque no haya cambios)."""
    v4 = _valid_cidrs(_fetch(CF_V4_URL)) or _FALLBACK_V4
    v6 = _valid_cidrs(_fetch(CF_V6_URL)) or _FALLBACK_V6

    content = _render(sorted(v4), sorted(v6))

    old = CONF_PATH.read_text(encoding="utf-8") if CONF_PATH.exists() else ""
    if old == content and not force:
        logger.info("Cloudflare real_ip ya actualizado (sin cambios)")
        return True

    CONF_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONF_PATH.write_text(content, encoding="utf-8")
    CONF_PATH.chmod(0o644)
    logger.info(f"Cloudflare real_ip escrito ({len(v4)} v4 + {len(v6)} v6)")

    return _reload_nginx()
