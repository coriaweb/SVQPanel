"""
Cálculo de estadísticas por usuario:

  - disk_used_mb:           tamaño total bajo /home/{user}/web/  (du -sb)
  - traffic_used_mb_month:  bytes transferidos según los access logs nginx
                            del MES EN CURSO (campo $body_bytes_sent + $request_length)

Llamado desde un timer systemd cada hora (api.cli refresh_user_stats).
"""

import gzip
import logging
import os
import re
import subprocess
from datetime import datetime
from typing import Tuple

logger = logging.getLogger(__name__)

# Regex del log nginx por defecto (combined). Suficiente para extraer
# fecha y bytes; tolerante con variaciones menores.
#
# Ejemplo:
# 1.2.3.4 - - [27/May/2026:18:42:01 +0000] "GET / HTTP/1.1" 200 4321 "..." "..."
#                                                                 ^^^^ body_bytes_sent
LOG_LINE_RE = re.compile(
    r'^\S+\s+\S+\s+\S+\s+\[(?P<date>[^\]]+)\]\s+'
    r'"[^"]*"\s+\d+\s+(?P<bytes>\d+|-)',
)

MONTH_ABBR = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


# ─────────────────────────────────────────────────────────────────────────────
# Disco
# ─────────────────────────────────────────────────────────────────────────────
def compute_user_disk_mb(home_dir: str) -> int:
    """
    Devuelve el tamaño en MB de /home/{user}/web. Si no existe, devuelve 0.
    Usa `du -sb --apparent-size` para que coincida con lo que ve el usuario.
    """
    web_dir = os.path.join(home_dir, "web")
    if not os.path.isdir(web_dir):
        return 0
    try:
        r = subprocess.run(
            ["/usr/bin/du", "-sb", "--apparent-size", web_dir],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            logger.warning(f"du falló en {web_dir}: {r.stderr.strip()}")
            return 0
        bytes_total = int(r.stdout.split()[0])
        return bytes_total // (1024 * 1024)
    except (subprocess.TimeoutExpired, ValueError, IndexError, FileNotFoundError) as e:
        logger.warning(f"du error en {web_dir}: {e}")
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# Tráfico
# ─────────────────────────────────────────────────────────────────────────────
def _iter_log_files(logs_dir: str):
    """Yield rutas de access logs (actual + rotados .gz/.1) en un dir."""
    if not os.path.isdir(logs_dir):
        return
    for name in os.listdir(logs_dir):
        if name.startswith("nginx.access.log"):
            yield os.path.join(logs_dir, name)


def _open_log(path: str):
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, "r", encoding="utf-8", errors="replace")


def _parse_log_for_month(path: str, year: int, month: int) -> int:
    """Devuelve bytes servidos en `path` del mes/año dado."""
    total = 0
    try:
        with _open_log(path) as f:
            for line in f:
                m = LOG_LINE_RE.match(line)
                if not m:
                    continue
                date_str = m.group("date")            # "27/May/2026:18:42:01 +0000"
                bytes_str = m.group("bytes")
                if bytes_str == "-":
                    continue
                try:
                    day, mon, rest = date_str.split("/", 2)
                    yr = int(rest[:4])
                    mo = MONTH_ABBR.get(mon, 0)
                except (ValueError, IndexError):
                    continue
                if yr != year or mo != month:
                    continue
                try:
                    total += int(bytes_str)
                except ValueError:
                    continue
    except (OSError, EOFError) as e:
        logger.warning(f"No pude leer {path}: {e}")
    return total


def compute_user_traffic_mb(home_dir: str, when: datetime = None) -> int:
    """
    Suma los bytes servidos en el mes en curso entre todos los logs nginx
    de todos los dominios del usuario:
        /home/{user}/web/{dominio}/logs/nginx.access.log[.N[.gz]]
    """
    web_dir = os.path.join(home_dir, "web")
    if not os.path.isdir(web_dir):
        return 0

    when = when or datetime.utcnow()
    year, month = when.year, when.month
    total_bytes = 0

    try:
        for entry in os.scandir(web_dir):
            if not entry.is_dir(follow_symlinks=False):
                continue
            logs_dir = os.path.join(entry.path, "logs")
            for log_path in _iter_log_files(logs_dir):
                total_bytes += _parse_log_for_month(log_path, year, month)
    except OSError as e:
        logger.warning(f"scandir {web_dir} falló: {e}")

    return total_bytes // (1024 * 1024)


# ─────────────────────────────────────────────────────────────────────────────
# Wrapper combinado
# ─────────────────────────────────────────────────────────────────────────────
def compute_user_stats(home_dir: str) -> Tuple[int, int]:
    """Devuelve (disk_used_mb, traffic_used_mb_month)."""
    return (
        compute_user_disk_mb(home_dir),
        compute_user_traffic_mb(home_dir),
    )
