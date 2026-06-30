"""
Gestión de bloqueo de user-agents maliciosos (nginx y Apache).

Para NGINX:
  Escribe /etc/nginx/conf.d/bad-bots.conf con un bloque `map` que asigna
  $bad_bot=1 para los user-agents bloqueados. El vhost de cada dominio ya
  incluye `if ($bad_bot) { return 444; }` gracias a apache_vhost_generator.

Para APACHE:
  Se inyecta en cada vhost Apache via apache_vhost_generator (RewriteCond).
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

NGINX_CONF = Path("/etc/nginx/conf.d/bad-bots.conf")
NGINX_MAIN_CONF = Path("/etc/nginx/nginx.conf")

# Catálogo de bots maliciosos conocidos
KNOWN_BAD_BOTS = [
    {"id": "terrabot",      "label": "Terrabot",           "pattern": "terrabot",       "description": "Bot de ataque conocido"},
    {"id": "masscan",       "label": "Masscan",            "pattern": "masscan",        "description": "Scanner de puertos masivo"},
    {"id": "zgrab",         "label": "ZGrab",              "pattern": "zgrab",          "description": "Scanner de vulnerabilidades"},
    {"id": "nikto",         "label": "Nikto",              "pattern": "nikto",          "description": "Scanner de vulnerabilidades web"},
    {"id": "sqlmap",        "label": "SQLMap",             "pattern": "sqlmap",         "description": "Herramienta de SQL injection"},
    {"id": "nmap",          "label": "Nmap",               "pattern": "nmap",           "description": "Scanner de red"},
    {"id": "nuclei",        "label": "Nuclei",             "pattern": "nuclei",         "description": "Scanner de vulnerabilidades"},
    {"id": "python_requests","label": "Python-requests",   "pattern": "python-requests","description": "Scripts de scraping/ataque en Python"},
    {"id": "go_http",       "label": "Go HTTP client",     "pattern": "Go-http-client", "description": "Bots escritos en Go"},
    {"id": "curl_attack",   "label": "curl (bots)",        "pattern": "curl/7.6",       "description": "Versiones antiguas de curl usadas por bots"},
    {"id": "semrush",       "label": "SemrushBot",         "pattern": "SemrushBot",     "description": "Bot de SEO agresivo"},
    {"id": "ahrefsbot",     "label": "AhrefsBot",          "pattern": "AhrefsBot",      "description": "Bot de SEO agresivo"},
    {"id": "mj12bot",       "label": "MJ12bot",            "pattern": "MJ12bot",        "description": "Bot de SEO agresivo"},
    {"id": "dotbot",        "label": "DotBot",             "pattern": "DotBot",         "description": "Bot de SEO agresivo"},
    {"id": "petalbot",      "label": "PetalBot",           "pattern": "PetalBot",       "description": "Bot de Huawei"},
    {"id": "claudebot",     "label": "ClaudeBot (scraper)","pattern": "ClaudeBot",      "description": "Bot de scraping de Anthropic"},
    {"id": "gptbot",        "label": "GPTBot",             "pattern": "GPTBot",         "description": "Bot de scraping de OpenAI"},
    {"id": "ccbot",         "label": "CCBot",              "pattern": "CCBot",          "description": "Bot de Common Crawl (datos de IA)"},
    {"id": "bytespider",    "label": "ByteSpider",         "pattern": "Bytespider",     "description": "Bot de TikTok/ByteDance"},
    {"id": "amazonbot",     "label": "AmazonBot",          "pattern": "Amazonbot",      "description": "Bot de scraping de Amazon"},
    {"id": "silvy_x_ran",   "label": "Silvy X Ran",        "pattern": "Silvy X Ran",    "description": "Bot que roba credenciales de cloud (.env, gcloud, AWS...)"},
    {"id": "leakix",        "label": "LeakIX (l9scan)",    "pattern": "l9scan",         "description": "Scanner de vulnerabilidades (leakix.net)"},
    {"id": "leakix_ua",     "label": "LeakIX (LEAKIX)",    "pattern": "LEAKIX",         "description": "Sonda de LeakIX (método HTTP inválido)"},
    {"id": "censys",        "label": "Censys",             "pattern": "CensysInspect",  "description": "Scanner de superficie de ataque"},
    {"id": "internetmeasure","label": "InternetMeasurement","pattern": "InternetMeasurement","description": "Sonda de escaneo masivo de Internet"},
    {"id": "expanse",       "label": "Expanse/Palo Alto",  "pattern": "Expanse",        "description": "Scanner de exposición (Palo Alto)"},
]


def get_known_bots() -> list:
    """Devuelve el catálogo con el estado activo/inactivo de cada bot."""
    blocked = _read_blocked_patterns()
    result = []
    for bot in KNOWN_BAD_BOTS:
        result.append({**bot, "enabled": bot["pattern"].lower() in blocked})
    return result


def get_custom_bots() -> list:
    """Devuelve los patrones custom (no del catálogo) que están bloqueados."""
    blocked = _read_blocked_patterns()
    known = {b["pattern"].lower() for b in KNOWN_BAD_BOTS}
    return [p for p in blocked if p not in known]


def update_bad_bots(enabled_ids: list, custom_patterns: list) -> dict:
    """
    Actualiza el bloqueo de bots según el webserver detectado.
    enabled_ids: lista de IDs del catálogo a activar (ej: ["terrabot", "zgrab"])
    custom_patterns: patrones libres adicionales (ej: ["mymalbbot", "evilcrawler"])

    Para Nginx: escribe /etc/nginx/conf.d/bad-bots.conf y recarga nginx
    Para Apache: los patrones se inyectan en cada vhost al regenerar (backend)
    """
    from scripts.webserver_config import get_webserver

    patterns = []

    # Patrones del catálogo seleccionados
    id_set = set(enabled_ids)
    for bot in KNOWN_BAD_BOTS:
        if bot["id"] in id_set:
            patterns.append(bot["pattern"])

    # Patrones custom (limpiar espacios y vacíos)
    for p in custom_patterns:
        p = p.strip()
        if p and p not in patterns:
            patterns.append(p)

    ws = get_webserver()

    # Para nginx, escribir el conf global
    if ws in ("nginx", "apache+nginx"):
        _write_nginx_conf(patterns)
        if ws == "nginx":
            _reload_nginx()
        # Si es apache+nginx, solo escribimos nginx pero no recargamos aquí
        # Los vhosts Apache se regenerarán en el backend cuando se asignen a un dominio

    # Para Apache, la inyección de patrones ocurre en apache_vhost_generator
    # cuando el backend regenera los vhosts de los dominios asignados a Apache.
    # Por ahora, solo marcamos que se actualizaron.

    return {"blocked_count": len(patterns), "patterns": patterns}


def ensure_catalog_bots_blocked(bot_ids: list) -> dict:
    """
    Asegura que los bots del catálogo indicados (por id) estén activos, SIN
    tocar el resto de la selección actual (otros bots del catálogo ni los
    patrones custom). Idempotente.

    Pensado para updates/instalación que quieren forzar el bloqueo de bots
    nuevos (p. ej. scanners de credenciales cloud) en servidores ya instalados,
    respetando lo que el admin ya tuviera marcado.

    Devuelve {"added": [...], "blocked_count": N}.
    """
    known = get_known_bots()
    valid_ids = {b["id"] for b in known}
    already_on = {b["id"] for b in known if b["enabled"]}

    want = [bid for bid in bot_ids if bid in valid_ids]
    added = [bid for bid in want if bid not in already_on]
    if not added:
        return {"added": [], "blocked_count": len(_read_blocked_patterns())}

    enabled_ids = sorted(already_on | set(want))
    custom = get_custom_bots()   # preservar patrones custom existentes
    result = update_bad_bots(enabled_ids, custom)
    return {"added": added, "blocked_count": result["blocked_count"]}


def _read_blocked_patterns() -> set:
    """Lee el archivo nginx actual y extrae los patrones bloqueados."""
    if not NGINX_CONF.exists():
        return set()
    patterns = set()
    for line in NGINX_CONF.read_text().splitlines():
        line = line.strip()
        # Líneas del tipo: ~*pattern    1;
        if line.startswith("~*") and line.endswith("1;"):
            pattern = line[2:].split()[0].rstrip(";").lower()
            patterns.add(pattern)
    return patterns


def _write_nginx_conf(patterns: list):
    """Escribe el archivo nginx con los patrones dados."""
    lines = [
        "# Generado por SVQPanel — Bad Bots Blocker",
        "# No editar manualmente",
        "map $http_user_agent $bad_bot {",
        "    default 0;",
    ]
    for p in patterns:
        # Escapar caracteres especiales nginx en el patrón
        safe = p.replace('"', '\\"')
        lines.append(f'    ~*{safe} 1;')
    lines.append("}")
    lines.append("")
    NGINX_CONF.write_text("\n".join(lines))
    logger.info(f"bad-bots.conf actualizado con {len(patterns)} patrones")


def _reload_nginx():
    """Recarga nginx si la configuración es válida."""
    try:
        test = subprocess.run(
            ["nginx", "-t"], capture_output=True, text=True, timeout=10
        )
        if test.returncode != 0:
            raise RuntimeError(f"nginx -t falló: {test.stderr[:200]}")
        subprocess.run(
            ["systemctl", "reload", "nginx"],
            capture_output=True, text=True, timeout=10
        )
        logger.info("nginx recargado correctamente")
    except Exception as e:
        logger.error(f"Error recargando nginx: {e}")
        raise
