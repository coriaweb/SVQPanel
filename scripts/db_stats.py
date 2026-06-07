"""
Estadísticas de BASES DE DATOS en vivo para el monitor de servicios.

  - MariaDB: reutiliza MySQLTuner (SHOW GLOBAL STATUS/VARIABLES vía CLI) para
    conexiones, uptime, queries/s, threads, hit ratio, nº de BDs.
  - PostgreSQL: consulta pg_stat_activity / pg_database con el cliente psql,
    usando el DATABASE_URL del panel.

Solo lectura. Pensado para llamarse bajo demanda desde el panel.
"""

import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)

_ENV = {**os.environ, "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}


def _run(cmd, timeout=10, env=None):
    try:
        e = {**_ENV, **(env or {})}
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=e)
        return r.returncode, r.stdout, r.stderr
    except Exception as ex:
        return -1, "", str(ex)


def _is_active(svc: str) -> bool:
    rc, so, _ = _run(["systemctl", "is-active", svc], timeout=5)
    return so.strip() == "active"


def _fmt_uptime(seconds: int) -> str:
    if seconds <= 0:
        return "—"
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


# ─────────────────────────────────────────────────────────────────────────────
# MariaDB (vía el tuner ya existente)
# ─────────────────────────────────────────────────────────────────────────────
def mariadb_stats() -> dict:
    out = {"available": False, "running": _is_active("mariadb") or _is_active("mysql")}
    host = os.getenv("MARIADB_HOST", "localhost")
    user = os.getenv("MARIADB_PANEL_USER", "")
    pw   = os.getenv("MARIADB_PANEL_PASSWORD", "")
    if os.getenv("MARIADB_ENABLED", "false").lower() != "true" or not user:
        return out
    try:
        from scripts.mysql_tuner import MySQLTuner
        t = MySQLTuner(host, user, pw)
        st = t.get_status()
        va = t.get_variables()
    except Exception as e:
        out["error"] = str(e)
        return out

    def _i(d, k, default=0):
        try:
            return int(float(d.get(k, default)))
        except (ValueError, TypeError):
            return default

    uptime = _i(st, "Uptime", 1) or 1
    questions = _i(st, "Questions")
    # Nº de bases de datos de cliente (excluye las del sistema)
    db_count = None
    rc, so, _ = _run(["/usr/bin/mariadb", f"--host={host}", f"--user={user}",
                      f"--password={pw}", "--silent", "--skip-column-names",
                      "--execute",
                      "SELECT COUNT(*) FROM information_schema.schemata "
                      "WHERE schema_name NOT IN ('mysql','information_schema',"
                      "'performance_schema','sys')"], timeout=8)
    if rc == 0 and so.strip().isdigit():
        db_count = int(so.strip())

    out.update({
        "available":         True,
        "version":           va.get("version", "?"),
        "uptime":            _fmt_uptime(uptime),
        "connections_now":   _i(st, "Threads_connected"),
        "connections_max":   _i(va, "max_connections"),
        "connections_peak":  _i(st, "Max_used_connections"),
        "queries_per_sec":   round(questions / uptime, 1),
        "slow_queries":      _i(st, "Slow_queries"),
        "aborted_connects":  _i(st, "Aborted_connects"),
        "databases":         db_count,
        "threads_running":   _i(st, "Threads_running"),
    })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# PostgreSQL (BD del panel)
# ─────────────────────────────────────────────────────────────────────────────
def _parse_database_url(url: str) -> dict:
    """postgresql://user:pass@host:port/db → dict."""
    m = re.match(r"postgresql://([^:]+):([^@]+)@([^:/]+)(?::(\d+))?/(.+)", url or "")
    if not m:
        return {}
    return {"user": m.group(1), "pass": m.group(2), "host": m.group(3),
            "port": m.group(4) or "5432", "db": m.group(5)}


def _psql(cfg: dict, sql: str):
    if not cfg:
        return None
    env = {"PGPASSWORD": cfg["pass"]}
    rc, so, _ = _run(["psql", "-h", cfg["host"], "-p", cfg["port"], "-U", cfg["user"],
                      "-d", cfg["db"], "-tAc", sql], timeout=8, env=env)
    if rc != 0:
        return None
    return so.strip()


def postgres_stats() -> dict:
    out = {"available": False, "running": _is_active("postgresql")}
    cfg = _parse_database_url(os.getenv("DATABASE_URL", ""))
    if not cfg:
        return out
    try:
        version = _psql(cfg, "SHOW server_version")
        conns   = _psql(cfg, "SELECT count(*) FROM pg_stat_activity")
        active  = _psql(cfg, "SELECT count(*) FROM pg_stat_activity WHERE state='active'")
        maxc    = _psql(cfg, "SHOW max_connections")
        dbcount = _psql(cfg, "SELECT count(*) FROM pg_database WHERE NOT datistemplate")
        uptime  = _psql(cfg, "SELECT EXTRACT(EPOCH FROM (now()-pg_postmaster_start_time()))::bigint")
        size    = _psql(cfg, f"SELECT pg_size_pretty(pg_database_size('{cfg['db']}'))")
        if version is None:
            out["error"] = "psql no respondió"
            return out
        out.update({
            "available":       True,
            "version":         (version or "").split()[0] if version else "?",
            "uptime":          _fmt_uptime(int(uptime)) if (uptime or "").isdigit() else "—",
            "connections_now": int(conns) if (conns or "").isdigit() else 0,
            "connections_active": int(active) if (active or "").isdigit() else 0,
            "connections_max": int(maxc) if (maxc or "").isdigit() else 0,
            "databases":       int(dbcount) if (dbcount or "").isdigit() else 0,
            "panel_db_size":   size or "—",
        })
    except Exception as e:
        out["error"] = str(e)
    return out


def collect() -> dict:
    return {
        "mariadb":    mariadb_stats(),
        "postgresql": postgres_stats(),
    }
