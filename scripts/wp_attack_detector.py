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

# Ventana de análisis por defecto: 24h. El cron corre cada ~3h y una ventana de
# un día da una cifra estable (no un valle puntual). Ajustable por env.
import os as _os
DEFAULT_WINDOW_MIN = int(_os.environ.get("SVQ_WP_ATTACK_WINDOW_MIN", "1440"))
# Umbral por defecto: a partir de estos hits EN LA VENTANA (24h) se considera
# ataque. ~2000/día es tráfico que un sitio legítimo no alcanza en xmlrpc/wp-login
# pero un ataque de fuerza bruta sí (los que vimos tenían 12k-32k/día).
DEFAULT_THRESHOLD = int(_os.environ.get("SVQ_WP_ATTACK_THRESHOLD", "2000"))
# Cuántos bytes leer de la cola del log (evita leer ficheros de cientos de MB).
# 24h de un log muy activo puede ser grande; leemos hasta 20 MB de cola (cientos
# de miles de líneas), suficiente para cubrir un día en sitios bajo ataque fuerte.
TAIL_BYTES = 20 * 1024 * 1024

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


def refresh_all_domains() -> int:
    """
    Analiza TODOS los dominios activos (ventana por defecto = 24h) y guarda los
    hits en la BD (wp_xmlrpc_hits / wp_wplogin_hits / wp_attack_checked_at). Lo
    llama el cron cada ~3h para que la vista admin lea de BD (instantáneo) sin
    escanear los access.log en vivo. Devuelve el nº de dominios actualizados.

    Se apoya en el mismo patrón que el cacheo del peso en disco.
    """
    from datetime import datetime as _dt
    from concurrent.futures import ThreadPoolExecutor
    # Import perezoso para no crear dependencia circular al importar el módulo.
    from api.models.database import SessionLocal, load_all_models
    load_all_models()
    from api.models.models_domain import Domain
    from api.models.models_user import User

    db = SessionLocal()
    try:
        domains = db.query(Domain).filter(Domain.is_active == True).all()  # noqa: E712
        if not domains:
            return 0
        uids = {d.user_id for d in domains}
        users = {u.id: u.username for u in db.query(User).filter(User.id.in_(uids)).all()}

        def _measure(d):
            u = users.get(d.user_id)
            if not u:
                return (d.id, 0, 0)
            try:
                r = analyze_domain(u, d.domain_name)  # ventana/umbral por defecto
                return (d.id, r["xmlrpc_hits"], r["wplogin_hits"])
            except Exception:
                return (d.id, 0, 0)

        with ThreadPoolExecutor(max_workers=min(8, len(domains))) as ex:
            results = list(ex.map(_measure, domains))

        now = _dt.utcnow()
        by_id = {d.id: d for d in domains}
        n = 0
        for did, xh, wh in results:
            d = by_id.get(did)
            if not d:
                continue
            d.wp_xmlrpc_hits = xh
            d.wp_wplogin_hits = wh
            d.wp_attack_checked_at = now
            n += 1
        db.commit()
        return n
    finally:
        db.close()
