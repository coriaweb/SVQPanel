"""
Estadísticas WEB en vivo para el monitor de servicios.

Fuentes (sin dependencias extra):
  - nginx stub_status (127.0.0.1:8089/nginx_status) → conexiones activas,
    accepted/handled/requests, reading/writing/waiting.
  - systemctl is-active → estado de nginx / apache2 / php*-fpm.
  - /run/php/*.sock + pgrep → workers PHP-FPM por versión.
  - BD del panel → nº de dominios (lo añade la ruta, no este módulo).
"""

import logging
import os
import re
import subprocess
import urllib.request

logger = logging.getLogger(__name__)

_ENV = {**os.environ, "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}
STUB_URL = "http://127.0.0.1:8089/nginx_status"


def _run(cmd, timeout=8):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=_ENV)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", str(e)


def _is_active(svc: str) -> bool:
    rc, so, _ = _run(["systemctl", "is-active", svc], timeout=5)
    return so.strip() == "active"


def nginx_status() -> dict:
    """
    Parsea el stub_status de nginx. Formato:
        Active connections: 28
        server accepts handled requests
         727768 727768 1608459
        Reading: 0 Writing: 11 Waiting: 17
    Devuelve {available, active, accepted, handled, requests, reading, writing,
    waiting, req_per_conn}.
    """
    out = {"available": False}
    try:
        with urllib.request.urlopen(STUB_URL, timeout=5) as r:
            txt = r.read().decode("utf-8", "replace")
    except Exception as e:
        out["error"] = str(e)
        return out

    m_active = re.search(r"Active connections:\s*(\d+)", txt)
    m_counts = re.search(r"^\s*(\d+)\s+(\d+)\s+(\d+)\s*$", txt, re.MULTILINE)
    m_rww = re.search(r"Reading:\s*(\d+)\s+Writing:\s*(\d+)\s+Waiting:\s*(\d+)", txt)
    if not (m_active and m_counts and m_rww):
        out["error"] = "formato stub_status no reconocido"
        return out

    accepted = int(m_counts.group(1))
    handled = int(m_counts.group(2))
    requests = int(m_counts.group(3))
    out.update({
        "available": True,
        "active":    int(m_active.group(1)),
        "accepted":  accepted,
        "handled":   handled,
        "requests":  requests,
        "reading":   int(m_rww.group(1)),
        "writing":   int(m_rww.group(2)),
        "waiting":   int(m_rww.group(3)),
        # peticiones medias por conexión (eficiencia keep-alive)
        "req_per_conn": round(requests / handled, 1) if handled else 0,
        # conexiones rechazadas = accepted - handled (debería ser 0)
        "dropped": accepted - handled,
    })
    return out


def php_fpm_pools() -> list:
    """
    Estado de cada versión de PHP-FPM instalada: activo y nº de procesos worker.
    Cuenta procesos 'php-fpm: pool' por versión via pgrep sobre el master.
    """
    pools = []
    for ver in ("7.4", "8.0", "8.1", "8.2", "8.3", "8.4", "8.5"):
        svc = f"php{ver}-fpm"
        rc, so, _ = _run(["systemctl", "is-active", svc], timeout=4)
        if so.strip() not in ("active", "activating"):
            continue
        # Contar workers: procesos cuyo cmdline contiene 'php-fpm' y la versión
        rc2, out2, _ = _run(["pgrep", "-c", "-f", f"php-fpm.*{ver}"], timeout=4)
        try:
            workers = int(out2.strip())
        except ValueError:
            workers = 0
        # El master cuenta como 1; los workers son los demás
        pools.append({
            "version": ver,
            "active":  True,
            "workers": max(0, workers - 1),
        })
    return pools


def collect() -> dict:
    return {
        "services": {
            "nginx":   _is_active("nginx"),
            "apache2": _is_active("apache2"),
        },
        "nginx":   nginx_status(),
        "php_fpm": php_fpm_pools(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Informe de visitas por dominio (GoAccess) — bajo demanda
# ─────────────────────────────────────────────────────────────────────────────
class WebStatsError(RuntimeError):
    """Error legible al generar el informe de estadísticas."""


def goaccess_available() -> bool:
    import shutil
    return shutil.which("goaccess") is not None


# ── GeoIP (DB-IP gratis) para mostrar países en el informe ───────────────────
GEOIP_DIR = "/var/lib/svqpanel/geoip"
GEOIP_DB = os.path.join(GEOIP_DIR, "dbip-country.mmdb")
# Base gratuita de DB-IP (sin registro ni license key). El nombre lleva el mes.
DBIP_URL_TMPL = "https://download.db-ip.com/free/dbip-country-lite-{ym}.mmdb.gz"


def geoip_db_path() -> "str | None":
    """Ruta de la base GeoIP si existe (para pasarla a GoAccess), o None."""
    return GEOIP_DB if os.path.isfile(GEOIP_DB) and os.path.getsize(GEOIP_DB) > 0 else None


def update_geoip_db(force: bool = False) -> bool:
    """Descarga/actualiza la base GeoIP de DB-IP (gratis). Idempotente: si ya hay
    una base de este mes y no se fuerza, no hace nada. Devuelve True si quedó una
    base utilizable. No lanza: ante fallo de red deja la base previa si la había."""
    import gzip
    import shutil as _sh
    from datetime import date

    os.makedirs(GEOIP_DIR, exist_ok=True)
    ym = date.today().strftime("%Y-%m")
    stamp = os.path.join(GEOIP_DIR, ".month")
    have = geoip_db_path() is not None
    if have and not force:
        try:
            with open(stamp) as f:
                if f.read().strip() == ym:
                    return True  # ya está la de este mes
        except OSError:
            pass

    url = DBIP_URL_TMPL.format(ym=ym)
    tmp_gz = GEOIP_DB + ".gz.tmp"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SVQPanel"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(tmp_gz, "wb") as fh:
            _sh.copyfileobj(resp, fh)
        # Descomprimir a un .tmp y mover atómicamente sobre la base final.
        tmp_db = GEOIP_DB + ".tmp"
        with gzip.open(tmp_gz, "rb") as gz, open(tmp_db, "wb") as out:
            _sh.copyfileobj(gz, out)
        os.replace(tmp_db, GEOIP_DB)
        with open(stamp, "w") as f:
            f.write(ym)
        logger.info(f"GeoIP DB-IP actualizada ({ym})")
        return True
    except Exception as e:
        logger.warning(f"No se pudo actualizar la base GeoIP ({url}): {e}")
        return have  # si ya teníamos una, seguimos sirviéndola
    finally:
        if os.path.exists(tmp_gz):
            try:
                os.remove(tmp_gz)
            except OSError:
                pass


def _domain_access_logs(username: str, domain: str) -> list:
    """Logs de acceso del dominio, del más reciente al más antiguo (incluye .1)."""
    from scripts.utils import get_domain_logs
    logs_dir = get_domain_logs(username, domain)
    candidates = []
    for base in ("nginx.access.log", "apache.access.log"):
        p = os.path.join(logs_dir, base)
        if os.path.isfile(p) and os.path.getsize(p) > 0:
            candidates.append(p)
        # Log rotado del día anterior
        p1 = p + ".1"
        if os.path.isfile(p1) and os.path.getsize(p1) > 0:
            candidates.append(p1)
    return candidates


def generate_goaccess_report(username: str, domain: str) -> str:
    """Genera un informe HTML de GoAccess del access.log del dominio.

    Devuelve la ruta de un fichero HTML temporal (el caller lo sirve y lo borra).
    Lanza WebStatsError si GoAccess no está, o no hay logs con datos.
    """
    if not goaccess_available():
        raise WebStatsError("GoAccess no está instalado en el servidor "
                            "(apt install goaccess).")
    logs = _domain_access_logs(username, domain)
    if not logs:
        raise WebStatsError("Todavía no hay registros de visitas para este "
                            "dominio (el access.log está vacío).")

    import tempfile
    fd, tmp_html = tempfile.mkstemp(prefix="svq_goaccess_", suffix=".html")
    os.close(fd)
    # COMBINED es el formato estándar de nginx/apache. --no-global-config evita
    # depender de un goaccess.conf del sistema. -o genera HTML autocontenido.
    cmd = ["goaccess", *logs,
           "-o", tmp_html,
           "--log-format=COMBINED",
           "--no-global-config",
           "--html-report-title=" + domain,
           "--html-prefs={\"theme\":\"darkBlue\"}"]
    # Geolocalización: si hay base GeoIP, GoAccess añade el panel de PAÍSES.
    geo = geoip_db_path()
    if geo:
        cmd += ["--geoip-database=" + geo]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=_ENV)
    except subprocess.TimeoutExpired:
        os.path.exists(tmp_html) and os.remove(tmp_html)
        raise WebStatsError("GoAccess tardó demasiado (log muy grande).")
    if r.returncode != 0 or not os.path.isfile(tmp_html) or os.path.getsize(tmp_html) == 0:
        os.path.exists(tmp_html) and os.remove(tmp_html)
        raise WebStatsError(f"GoAccess falló: {(r.stderr or r.stdout)[:300]}")
    return tmp_html
