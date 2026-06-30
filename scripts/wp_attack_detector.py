"""
Detección de ataques de fuerza bruta a WordPress por dominio.

Cuenta los accesos a /xmlrpc.php y /wp-login.php en el access.log del dominio
durante una ventana reciente. Si superan un umbral y el dominio NO tiene la
protección activada, el panel muestra un aviso al cliente en su dashboard con un
botón para activarla (bloquear xmlrpc + rate-limit wp-login).

Diseño:
- Bajo demanda (lo llama el dashboard), no un hilo permanente: leer la cola del
  log solo cuando alguien mira es más barato que vigilar 24/7.
- Solo lee la COLA del fichero (últimos N KB) para no recorrer logs enormes.
- No escala privilegios: el panel ya corre como root y lee estos logs.
"""

import os
import re
from datetime import datetime, timedelta

# Umbral por defecto: a partir de estos hits en la ventana, se considera ataque.
DEFAULT_THRESHOLD = 500
# Ventana de análisis (minutos) sobre las líneas leídas de la cola del log.
DEFAULT_WINDOW_MIN = 60
# Cuántos bytes leer de la cola del log (evita leer ficheros de cientos de MB).
TAIL_BYTES = 3 * 1024 * 1024  # 3 MB ≈ decenas de miles de líneas

# Formato de fecha del access.log de nginx: [01/Jul/2026:00:31:56 +0200]
_TS_RE = re.compile(r"\[(\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2})")
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _domain_access_log(username: str, domain: str) -> str:
    return f"/home/{username}/web/{domain}/logs/nginx.access.log"


def _parse_ts(line: str):
    """Devuelve el datetime (naive, hora local del log) de una línea, o None."""
    m = _TS_RE.search(line)
    if not m:
        return None
    try:
        d, mon, rest = m.group(1).split("/", 2)
        day = int(d)
        month = _MONTHS.get(mon)
        y, hh, mm, ss = re.split(r"[:]", rest)
        return datetime(int(y), month, day, int(hh), int(mm), int(ss))
    except Exception:
        return None


def _tail_lines(path: str, max_bytes: int = TAIL_BYTES):
    """Lee los últimos max_bytes del fichero y devuelve sus líneas (texto)."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()  # descarta la primera línea (probablemente partida)
            data = f.read()
        return data.decode("utf-8", errors="replace").splitlines()
    except (FileNotFoundError, PermissionError, OSError):
        return []


def analyze_domain(username: str, domain: str,
                   window_min: int = DEFAULT_WINDOW_MIN,
                   threshold: int = DEFAULT_THRESHOLD) -> dict:
    """
    Cuenta hits a xmlrpc.php y wp-login.php en la ventana reciente.

    Devuelve dict:
      {
        "xmlrpc_hits": int, "wplogin_hits": int,
        "window_min": int, "threshold": int,
        "under_attack": bool,   # algún contador supera el umbral
        "attack_targets": [...] # cuáles ("xmlrpc"/"wp-login")
      }
    """
    log = _domain_access_log(username, domain)
    lines = _tail_lines(log)
    cutoff = datetime.now() - timedelta(minutes=window_min)

    xmlrpc = 0
    wplogin = 0
    for ln in lines:
        # Filtro barato primero (substring) antes de parsear la fecha.
        is_xmlrpc = "xmlrpc.php" in ln
        is_wplogin = "wp-login.php" in ln
        if not (is_xmlrpc or is_wplogin):
            continue
        ts = _parse_ts(ln)
        if ts is not None and ts < cutoff:
            continue
        if is_xmlrpc:
            xmlrpc += 1
        if is_wplogin:
            wplogin += 1

    targets = []
    if xmlrpc >= threshold:
        targets.append("xmlrpc")
    if wplogin >= threshold:
        targets.append("wp-login")

    return {
        "xmlrpc_hits": xmlrpc,
        "wplogin_hits": wplogin,
        "window_min": window_min,
        "threshold": threshold,
        "under_attack": bool(targets),
        "attack_targets": targets,
    }
