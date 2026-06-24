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


# Línea qmgr: hay EXACTAMENTE una por correo entregado, con su queue-id y el
# envelope sender. Es la fuente fiable para contar (no duplica como pickup/cleanup).
#   ...postfix/qmgr[..]: <QID>: from=<x@y>, size=..., nrcpt=N (queue active)
_QMGR_RE = re.compile(r"postfix/qmgr\[\d+\]:\s+([0-9A-F]{6,}):\s+from=<([^>]*)>")
# Destinatario en líneas de entrega:  <QID>: to=<dest@dominio>, ...
_TO_RE = re.compile(r"([0-9A-F]{6,}):\s+to=<([^>]*)>")


def scan_last_hour():
    """Escanea el log de la última hora. Devuelve (counts, recipients):
      counts:     {usuario_sistema: n_correos}   (1 por queue-id, sin duplicar)
      recipients: {usuario_sistema: [dest, ...]} (destinatarios de esos correos)
    Solo correo NO autenticado (sender = usuario@<hostname-del-servidor>).
    """
    cutoff = datetime.now() - timedelta(hours=1)
    host = _local_hostname()
    accepted = accepted_hostnames(host)

    # queue-id → usuario de sistema (solo de los correos no-auth recientes).
    qid_user = {}
    # queue-id → destinatarios (de cualquier línea con to=, en la ventana).
    qid_rcpts = {}

    for path in MAIL_LOGS:
        if not os.path.isfile(path):
            continue
        try:
            f = open(path, "r", errors="replace")
        except OSError:
            continue
        with f:
            for line in f:
                tsm = _TS_RE.match(line)
                if not tsm:
                    continue
                try:
                    ts = datetime.strptime(tsm.group(1), "%Y-%m-%dT%H:%M:%S")
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
                # 1) línea qmgr → identifica el correo y su remitente
                qm = _QMGR_RE.search(line)
                if qm:
                    qid, sender = qm.group(1), qm.group(2).lower()
                    local, _, dom = sender.partition("@")
                    if local and (not host or dom in accepted):
                        qid_user[qid] = local
                    continue
                # 2) línea con destinatario → la guardamos por queue-id
                tm = _TO_RE.search(line)
                if tm:
                    qid, rcpt = tm.group(1), tm.group(2)
                    if rcpt:
                        qid_rcpts.setdefault(qid, []).append(rcpt)

    counts, recipients = {}, {}
    for qid, user in qid_user.items():
        counts[user] = counts.get(user, 0) + 1
        for r in qid_rcpts.get(qid, []):
            recipients.setdefault(user, []).append(r)
    return counts, recipients


def sent_last_hour() -> dict:
    """Compat: solo los contadores por usuario."""
    counts, _ = scan_last_hour()
    return counts


def _top_recipients(rcpts, top=8):
    """Lista de destinatarios con su conteo, los más frecuentes primero."""
    from collections import Counter
    c = Counter(r.lower() for r in (rcpts or []))
    return [{"to": addr, "count": n} for addr, n in c.most_common(top)]


def build_rows(limits: dict, sent: dict, recipients: dict = None) -> list:
    """Combina límites + enviados en filas con %/estado. Función PURA (testeable)."""
    recipients = recipients or {}
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
            "recipients": _top_recipients(recipients.get(u)),
        })
    # Ordenar: primero los que más cerca/superan el límite.
    rows.sort(key=lambda r: (-r["pct"], -r["sent_last_hour"]))
    return rows


def summary() -> dict:
    """Resumen por usuario del sistema: límite no-auth + enviados última hora +
    destinatarios (para ver a quién se ha enviado)."""
    counts, recipients = scan_last_hour()
    rows = build_rows(_read_limits(), counts, recipients)
    return {"available": True, "rows": rows, "hostname": _local_hostname()}
