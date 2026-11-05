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
no reescribe ni recarga nginx. Si la descarga falla (o viene sospechosamente
corta) usa los rangos que ya había; solo sin ninguno cae a la lista embebida.

Los mismos rangos alimentan `geo $realip_remote_addr $svq_from_cf` (conf.d
svqpanel-cloudflare-geo.conf), que usa la opción por dominio «Solo tráfico desde
Cloudflare» (scripts/geo_access.py). $realip_remote_addr es la IP de la conexión
ANTES del real_ip (la de Cloudflare), no la del visitante. Se refresca a diario:
si Cloudflare publica un rango nuevo y no se añade, esas webs no responderían
desde él.
"""
from __future__ import annotations

import ipaddress
import logging
import re
import subprocess
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

CONF_PATH = Path("/etc/nginx/conf.d/svqpanel-cloudflare-realip.conf")
RANGES_FILE = Path("/var/lib/svqpanel/geo/cloudflare.conf")
GEO_CONF = Path("/etc/nginx/conf.d/svqpanel-cloudflare-geo.conf")
GEO_VAR = "$svq_from_cf"

# Una respuesta con menos rangos que esto no es la lista de Cloudflare (hoy son
# 15 v4 + 7 v6): se descarta y se mantienen los que ya había.
_MIN_V4, _MIN_V6 = 8, 4

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


def _render_ranges(v4: list[str], v6: list[str]) -> str:
    return ("# SVQPanel — rangos de Cloudflare para $svq_from_cf (NO editar: refresh_cloudflare_ips)\n"
            + "".join(f"{c} 1;\n" for c in list(v4) + list(v6)))


def render_geo_conf() -> str:
    return ("# SVQPanel — ¿la conexión viene de Cloudflare? (dominios con «Solo tráfico\n"
            "# desde Cloudflare»). $realip_remote_addr = IP de la conexión, antes del real_ip.\n"
            f"geo $realip_remote_addr {GEO_VAR} {{\n"
            "    default 0;\n"
            f"    include {RANGES_FILE.as_posix()};\n"
            "}\n")


def current_ranges() -> tuple[list[str], list[str]]:
    """Rangos que el servidor usa ahora (del conf de real_ip); [] si no hay."""
    try:
        text = CONF_PATH.read_text(encoding="utf-8")
    except OSError:
        return [], []
    nets = _valid_cidrs(re.findall(r"^set_real_ip_from\s+(\S+);", text, re.M))
    return ([n for n in nets if ":" not in n], [n for n in nets if ":" in n])


def get_ranges(fetch: bool = True) -> tuple[list[str], list[str]]:
    """Rangos de Cloudflare: los descargados si la descarga parece buena; si no,
    los que ya tenía el servidor; y sin ninguno, la lista embebida."""
    old_v4, old_v6 = current_ranges()
    v4 = _valid_cidrs(_fetch(CF_V4_URL)) if fetch else []
    v6 = _valid_cidrs(_fetch(CF_V6_URL)) if fetch else []
    if len(v4) < _MIN_V4:
        if fetch:
            logger.warning(f"Cloudflare v4: {len(v4)} rangos descargados; se mantienen los anteriores")
        v4 = old_v4 or _FALLBACK_V4
    if len(v6) < _MIN_V6:
        if fetch:
            logger.warning(f"Cloudflare v6: {len(v6)} rangos descargados; se mantienen los anteriores")
        v6 = old_v6 or _FALLBACK_V6
    return sorted(set(v4)), sorted(set(v6))


def is_cloudflare_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    v4, v6 = get_ranges(fetch=False)
    return any(addr in ipaddress.ip_network(n, strict=False) for n in v4 + v6)


def _write_if_changed(path: Path, content: str) -> bool:
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    if old == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.chmod(0o644)
    tmp.replace(path)
    return True


def ensure_geo() -> None:
    """El geo $svq_from_cf debe existir mientras algún vhost lo use (si no, nginx
    no arranca: "unknown variable"). No descarga nada (va en la regeneración de
    vhosts): usa los rangos que ya tiene el servidor."""
    v4, v6 = get_ranges(fetch=False)
    _write_if_changed(RANGES_FILE, _render_ranges(v4, v6))
    _write_if_changed(GEO_CONF, render_geo_conf())


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
    v4, v6 = get_ranges(fetch=True)

    changed = _write_if_changed(CONF_PATH, _render(v4, v6))
    changed |= _write_if_changed(RANGES_FILE, _render_ranges(v4, v6))
    changed |= _write_if_changed(GEO_CONF, render_geo_conf())
    if not changed and not force:
        logger.info("Cloudflare real_ip ya actualizado (sin cambios)")
        return True
    logger.info(f"Cloudflare real_ip y $svq_from_cf escritos ({len(v4)} v4 + {len(v6)} v6)")

    return _reload_nginx()
