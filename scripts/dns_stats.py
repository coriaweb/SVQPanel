"""
Estadísticas DNS (BIND9) en vivo para el monitor de servicios.

Fuentes (sin dependencias extra):
  - rndc status  → versión, uptime, nº de zonas, clientes recursivos/tcp, xfers.
  - rndc stats   → vuelca contadores a named.stats; parseamos las queries por
    tipo (A, AAAA, MX, ...) y los totales de éxito/fallo.
  - systemctl    → estado de named/bind9.
"""

import logging
import os
import re
import subprocess
from datetime import datetime

logger = logging.getLogger(__name__)

_ENV = {**os.environ, "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}
RNDC = "/usr/sbin/rndc"
# Ubicaciones típicas del statistics-file de BIND en Debian
_STATS_PATHS = ["/var/cache/bind/named.stats", "/var/named/named.stats",
                "/var/cache/bind/named_stats.txt"]


def _run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=_ENV)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", str(e)


def _is_active() -> bool:
    for svc in ("named", "bind9"):
        rc, so, _ = _run(["systemctl", "is-active", svc], timeout=5)
        if so.strip() == "active":
            return True
    return False


def _fmt_uptime_since(boot_str: str) -> str:
    """boot time de rndc: 'Thu, 04 Jun 2026 14:20:07 GMT' → '3d 2h'."""
    try:
        bt = datetime.strptime(boot_str.strip(), "%a, %d %b %Y %H:%M:%S %Z")
        secs = int((datetime.utcnow() - bt).total_seconds())
        if secs < 0:
            return "—"
        d, rem = divmod(secs, 86400)
        h = rem // 3600
        if d:
            return f"{d}d {h}h"
        m = (rem % 3600) // 60
        return f"{h}h {m}m" if h else f"{m}m"
    except Exception:
        return "—"


def rndc_status() -> dict:
    """Parsea 'rndc status'. Devuelve dict con los campos clave."""
    rc, so, err = _run([RNDC, "status"], timeout=8)
    if rc != 0:
        return {"available": False, "error": (err or so).strip()[:200]}

    out = {"available": True}
    m = re.search(r"version:\s*BIND\s*(\S+)", so)
    out["version"] = m.group(1) if m else "?"
    m = re.search(r"boot time:\s*(.+)", so)
    out["uptime"] = _fmt_uptime_since(m.group(1)) if m else "—"

    # number of zones: 104 (98 automatic) → reales = 104 - 98
    m = re.search(r"number of zones:\s*(\d+)(?:\s*\((\d+)\s*automatic\))?", so)
    if m:
        total = int(m.group(1))
        auto = int(m.group(2)) if m.group(2) else 0
        out["zones_total"] = total
        out["zones_user"] = max(0, total - auto)

    m = re.search(r"recursive clients:\s*(\d+)/(\d+)/(\d+)", so)
    if m:
        out["recursive_clients"] = int(m.group(1))
        out["recursive_limit"] = int(m.group(3))
    m = re.search(r"tcp clients:\s*(\d+)/(\d+)", so)
    if m:
        out["tcp_clients"] = int(m.group(1))
        out["tcp_limit"] = int(m.group(2))
    m = re.search(r"xfers running:\s*(\d+)", so)
    if m:
        out["xfers_running"] = int(m.group(1))
    out["query_logging"] = "ON" if "query logging is ON" in so else "OFF"
    return out


def _stats_file() -> str | None:
    for p in _STATS_PATHS:
        if os.path.isfile(p):
            return p
    return None


def query_stats() -> dict:
    """
    Fuerza 'rndc stats' y parsea el bloque 'Incoming Queries' del named.stats:
        12345 A
         678 AAAA
    Devuelve {available, total, by_type:[{type,count}], success, ...}.
    """
    out = {"available": False, "total": 0, "by_type": []}
    _run([RNDC, "stats"], timeout=8)   # regenera/actualiza el fichero
    path = _stats_file()
    if not path:
        return out
    try:
        with open(path) as f:
            content = f.read()
    except OSError:
        return out

    by_type = {}
    # Sección de queries entrantes por tipo de registro
    qsec = re.search(r"\+\+ Incoming Queries \+\+(.*?)(?:\+\+|--- Statistics Dump)",
                     content, re.DOTALL)
    if qsec:
        for line in qsec.group(1).splitlines():
            m = re.match(r"\s*(\d+)\s+([A-Z0-9!]+)\s*$", line)
            if m:
                by_type[m.group(2)] = int(m.group(1))

    # Totales de resolución (éxito / fallo) del bloque de servidor
    def _grab(label):
        m = re.search(rf"(\d+)\s+{re.escape(label)}", content)
        return int(m.group(1)) if m else 0

    out["available"] = bool(by_type)
    out["by_type"] = [{"type": t, "count": c}
                      for t, c in sorted(by_type.items(), key=lambda x: -x[1])][:10]
    out["total"] = sum(by_type.values())
    out["queries_success"] = _grab("queries resulted in successful answer")
    out["queries_nxdomain"] = _grab("queries resulted in NXDOMAIN")
    out["queries_referral"] = _grab("queries resulted in referral")
    return out


def collect() -> dict:
    running = _is_active()
    data = {"running": running, "status": {"available": False}, "queries": {"available": False}}
    if running:
        data["status"] = rndc_status()
        data["queries"] = query_stats()
    return data
