"""
Resumen de correo SALIENTE no autenticado (formularios PHP / scripts web).

El correo que inyecta PHP por localhost sale con envelope sender
"usuario_sistema@hostname". Aquí contamos, por usuario del sistema, cuántos
correos ha enviado en la última hora (del log de Postfix) y lo cruzamos con su
límite (mapa de Rspamd), para que el admin detecte sitios que abusan/están
comprometidos.

No depende de Redis (las claves de Rspamd van hasheadas): el consumo se cuenta
del propio mail.log, que refleja lo realmente enviado.
"""

import os
import re
import glob
import gzip
from datetime import datetime, timedelta

SYSUSER_MAP = "/etc/rspamd/maps/sysuser_ratelimit.map"
MAIL_LOGS = ["/var/log/mail.log", "/var/log/mail.log.1"]
SYSTEM_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# Línea qmgr con el envelope sender:  ... postfix/qmgr[..]: ABC123: from=<x@y>, size=..
_FROM_RE = re.compile(r"from=<([^>]*)>")
# Timestamp ISO al inicio: 2026-06-24T12:38:08.727909+02:00
_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")


def accepted_hostnames(host: str) -> set:
    """Hostnames válidos del sender no autenticado: el FQDN y el nombre corto."""
    host = (host or "").lower()
    s = {host} if host else set()
    if "." in host:
        s.add(host.split(".", 1)[0])
    return s


def _read_limits() -> dict:
    """Lee el mapa sysuser → límite/hora. {'weblab94': 50, ...}."""
    limits = {}
    try:
        with open(SYSUSER_MAP) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # "weblab94 50 / 1h"
                m = re.match(r"^(\S+)\s+(\d+)", line)
                if m:
                    limits[m.group(1).lower()] = int(m.group(2))
    except FileNotFoundError:
        pass
    return limits


def _local_hostname() -> str:
    """Hostname con el que Postfix firma el correo local (el dominio del envelope
    sender del correo de PHP). Fuente de verdad: `postconf -h myhostname`; si no,
    socket.getfqdn(). socket.gethostname() suele dar solo el nombre corto."""
    import subprocess
    try:
        env = os.environ.copy()
        env["PATH"] = SYSTEM_PATH
        r = subprocess.run(["postconf", "-h", "myhostname"],
                           capture_output=True, text=True, timeout=5, env=env)
        h = (r.stdout or "").strip().lower()
        if h:
            return h
    except Exception:
        pass
    try:
        import socket
        return socket.getfqdn().lower()
    except Exception:
        return ""


def sent_last_hour() -> dict:
    """Cuenta envíos por parte-local del envelope sender en los últimos 60 min.

    Solo cuenta el correo cuyo sender es 'algo@<hostname-del-servidor>' (el patrón
    del correo no autenticado de PHP). Devuelve {usuario_sistema: n_enviados}.
    """
    cutoff = datetime.now() - timedelta(hours=1)
    host = _local_hostname()
    # Aceptar tanto el FQDN (svqhostpanel.svqhost.red) como el nombre corto
    # (svqhostpanel): según la config, Postfix puede firmar con cualquiera.
    accepted = accepted_hostnames(host)
    counts = {}
    # Evitar contar dos veces el mismo queue-id (qmgr loguea varias líneas).
    seen = set()

    for path in MAIL_LOGS:
        if not os.path.isfile(path):
            continue
        try:
            f = open(path, "r", errors="replace")
        except OSError:
            continue
        with f:
            for line in f:
                if "from=<" not in line:
                    continue
                tsm = _TS_RE.match(line)
                if not tsm:
                    continue
                try:
                    ts = datetime.strptime(tsm.group(1), "%Y-%m-%dT%H:%M:%S")
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
                fm = _FROM_RE.search(line)
                if not fm or "@" not in fm.group(1):
                    continue
                sender = fm.group(1).lower()
                local, _, dom = sender.partition("@")
                # Solo el correo no autenticado: sender en el hostname del server
                # (FQDN o nombre corto). Sin local válido, descartar.
                if not local:
                    continue
                if host and dom not in accepted:
                    continue
                # Dedup por queue-id (primer token "XXXX:" de la línea postfix).
                qid_m = re.search(r"\]: ([0-9A-F]{6,}):", line)
                key = (qid_m.group(1) if qid_m else line)
                if key in seen:
                    continue
                seen.add(key)
                counts[local] = counts.get(local, 0) + 1
    return counts


def build_rows(limits: dict, sent: dict) -> list:
    """Combina límites + enviados en filas con %/estado. Función PURA (testeable)."""
    rows = []
    for u in sorted(set(limits) | set(sent)):
        limit = limits.get(u, 0)
        n = sent.get(u, 0)
        pct = round(100 * n / limit) if limit > 0 else 0
        if limit and n >= limit:
            state = "blocked"
        elif limit and pct >= 80:
            state = "warn"
        else:
            state = "ok"
        rows.append({
            "user": u, "limit": limit, "sent_last_hour": n,
            "pct": pct, "state": state,
        })
    # Ordenar: primero los que más cerca/superan el límite.
    rows.sort(key=lambda r: (-r["pct"], -r["sent_last_hour"]))
    return rows


def summary() -> dict:
    """Resumen por usuario del sistema: límite no-auth + enviados última hora."""
    rows = build_rows(_read_limits(), sent_last_hour())
    return {"available": True, "rows": rows, "hostname": _local_hostname()}
