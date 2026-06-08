"""
Estadísticas de correo EN VIVO para el monitor de servicios (estilo eximstats de
Hestia, pero para el stack Postfix + Dovecot + Rspamd de SVQPanel).

Fuentes (sin dependencias extra):
  - postqueue -j   → cola de correo (mensajes en espera, motivo, antigüedad)
  - rspamc stat    → antispam (escaneados, spam/ham, reject/greylist)
  - /var/log/mail.log → resumen del día (recibidos/entregados/rechazados,
    rebotes, top remitentes/destinos, errores recientes)
  - systemctl is-active → estado de postfix/dovecot/rspamd

Todo en lectura; no modifica nada. Pensado para llamarse bajo demanda desde el
panel (no cada 5 min): parsear el log entero es algo costoso, así que se limita.
"""

import json
import logging
import os
import re
import subprocess
from collections import Counter
from datetime import datetime

logger = logging.getLogger(__name__)

_ENV = {**os.environ, "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}
MAIL_LOG = "/var/log/mail.log"
# Cuántas líneas del final del log analizar (suficiente para "hoy" sin tardar).
_LOG_TAIL_LINES = 20000


def _run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=_ENV)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", str(e)


# ─────────────────────────────────────────────────────────────────────────────
# Estado de los servicios de correo
# ─────────────────────────────────────────────────────────────────────────────
def services_status() -> dict:
    out = {}
    for svc in ("postfix", "dovecot", "rspamd"):
        rc, so, _ = _run(["systemctl", "is-active", svc], timeout=5)
        out[svc] = (so.strip() == "active")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Cola de correo (postqueue)
# ─────────────────────────────────────────────────────────────────────────────
def mail_queue() -> dict:
    """
    Devuelve {count, size_kb, messages:[{id, sender, recipients, age_s, reason}]}.
    Usa 'postqueue -j' (una línea JSON por mensaje en Postfix moderno).
    """
    rc, so, _ = _run(["/usr/sbin/postqueue", "-j"], timeout=15)
    messages = []
    total_size = 0
    if rc == 0 and so.strip():
        now = datetime.utcnow().timestamp()
        for line in so.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                m = json.loads(line)
            except ValueError:
                continue
            size = int(m.get("message_size", 0))
            total_size += size
            recips = m.get("recipients", [])
            reason = ""
            if recips and isinstance(recips, list):
                reason = recips[0].get("delay_reason", "") or ""
            arrival = m.get("arrival_time", 0)
            messages.append({
                "id":         m.get("queue_id", "?"),
                "sender":     m.get("sender", "") or "<>",
                "recipients": [r.get("address", "") for r in recips][:5],
                "size":       size,
                "age_s":      int(now - arrival) if arrival else 0,
                "reason":     reason[:140],
            })
    # Orden: más antiguos primero
    messages.sort(key=lambda x: x["age_s"], reverse=True)
    return {
        "count":   len(messages),
        "size_kb": round(total_size / 1024, 1),
        "messages": messages[:50],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Antispam (rspamd)
# ─────────────────────────────────────────────────────────────────────────────
def rspamd_stats() -> dict:
    rc, so, _ = _run(["/usr/bin/rspamc", "stat"], timeout=10)
    if rc != 0:
        return {"available": False}
    out = {"available": True, "scanned": 0, "spam": 0, "ham": 0,
           "reject": 0, "greylist": 0, "soft_reject": 0, "learned": 0}
    patterns = {
        "scanned":     r"Messages scanned:\s*(\d+)",
        "reject":      r"action reject:\s*(\d+)",
        "soft_reject": r"action soft reject:\s*(\d+)",
        "greylist":    r"action greylist:\s*(\d+)",
        "spam":        r"treated as spam:\s*(\d+)",
        "ham":         r"treated as ham:\s*(\d+)",
        "learned":     r"Messages learned:\s*(\d+)",
    }
    for key, pat in patterns.items():
        m = re.search(pat, so)
        if m:
            out[key] = int(m.group(1))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Resumen del log de correo (hoy): recibidos/entregados/rechazados, tops, errores
# ─────────────────────────────────────────────────────────────────────────────
def log_summary() -> dict:
    """
    Parsea las últimas líneas de /var/log/mail.log y resume la actividad de HOY.
    No depende de pflogsumm. Cuenta eventos de Postfix:
      - received  → 'postfix/smtpd' ... 'client='  (mensaje entrante aceptado)
      - delivered → 'status=sent'
      - bounced   → 'status=bounced'
      - deferred  → 'status=deferred'
      - rejected  → 'NOQUEUE: reject:'
    """
    summary = {
        "available": False, "received": 0, "delivered": 0, "bounced": 0,
        "deferred": 0, "rejected": 0, "top_senders": [], "top_recipients": [],
        "top_reject_reasons": [], "recent_errors": [], "since": None,
    }
    if not os.path.isfile(MAIL_LOG):
        return summary

    today = datetime.utcnow().strftime("%Y-%m-%d")
    # Leer solo el tramo final del log (rápido) con tail
    rc, so, _ = _run(["tail", "-n", str(_LOG_TAIL_LINES), MAIL_LOG], timeout=20)
    if rc != 0 or not so:
        return summary
    summary["available"] = True

    senders = Counter()
    recipients = Counter()
    reject_reasons = Counter()
    errors = []

    for line in so.splitlines():
        # Solo líneas de hoy (el log empieza con ISO8601: 2026-06-07T...)
        if not line.startswith(today):
            continue
        if summary["since"] is None:
            summary["since"] = line[:19]

        # Rechazos en la conversación SMTP (spam/relay denegado/etc.)
        if "NOQUEUE: reject:" in line or "NOQUEUE: milter-reject:" in line:
            summary["rejected"] += 1
            mr = re.search(r"reject:\s*\w+\s+from\s+\S+:\s*\d+\s+[\d.]+\s+(.+?);", line)
            if not mr:
                mr = re.search(r"reject:\s*(.+?)(?:;|$)", line)
            if mr:
                reason = re.sub(r"<[^>]*>", "", mr.group(1)).strip()
                reject_reasons[reason[:80]] += 1
            continue

        # Estados de entrega (postfix/smtp, lmtp, pipe, virtual...)
        if "status=sent" in line:
            summary["delivered"] += 1
        elif "status=bounced" in line:
            summary["bounced"] += 1
            m = re.search(r"to=<([^>]+)>", line)
            errors.append({"to": m.group(1) if m else "?", "msg": _extract_bounce_reason(line)})
        elif "status=deferred" in line:
            summary["deferred"] += 1

        # Remitente / destinatario para los tops (solo en líneas con direcciones)
        mf = re.search(r"\bfrom=<([^>]+)>", line)
        if mf and mf.group(1):
            senders[mf.group(1)] += 1
        mt = re.search(r"\bto=<([^>]+)>", line)
        if mt and mt.group(1):
            recipients[mt.group(1)] += 1

        # Mensajes recibidos/inyectados: línea de qmgr con tamaño de mensaje
        if "postfix/qmgr" in line and "from=<" in line and "size=" in line:
            summary["received"] += 1

    summary["top_senders"]        = [{"addr": a, "count": c} for a, c in senders.most_common(10)]
    summary["top_recipients"]     = [{"addr": a, "count": c} for a, c in recipients.most_common(10)]
    summary["top_reject_reasons"] = [{"reason": r, "count": c} for r, c in reject_reasons.most_common(8)]
    summary["recent_errors"]      = errors[-10:]
    return summary


def _extract_bounce_reason(line: str) -> str:
    m = re.search(r"status=bounced\s*\((.+)\)", line)
    if m:
        return m.group(1)[:160]
    return line[-160:]


# ─────────────────────────────────────────────────────────────────────────────
# Correos enviados por buzón en la última hora (para la barra de límite de envío)
# ─────────────────────────────────────────────────────────────────────────────
def sent_last_hour(emails=None) -> dict:
    """Cuenta los correos ENVIADOS por cada buzón autenticado en los últimos 60 min.

    En Postfix el envío autenticado deja `sasl_username=<email>` en la línea de
    `smtpd` (al recibir el mensaje del cliente) y el `status=sent` aparece después
    en una línea de `smtp`/`lmtp`; ambas se enlazan por el QUEUE-ID. Aquí
    correlacionamos: queue-id → sasl_username, y contamos los que acabaron en
    status=sent dentro de la última hora.

    `emails`: lista opcional para filtrar (solo cuenta esos buzones). Devuelve
    {email: nº enviado}.
    """
    result = {}
    if not os.path.isfile(MAIL_LOG):
        return result
    rc, so, _ = _run(["tail", "-n", str(_LOG_TAIL_LINES), MAIL_LOG], timeout=20)
    if rc != 0 or not so:
        return result

    wanted = set(e.lower() for e in emails) if emails else None
    cutoff = datetime.utcnow().timestamp() - 3600

    qid_user = {}      # queue-id → sasl_username (remitente autenticado)
    counts = Counter()

    for line in so.splitlines():
        ts = _line_ts(line)
        if ts is not None and ts < cutoff:
            # Línea antigua: si ya guardamos su qid, podemos olvidarlo luego.
            continue

        # 1) Línea smtpd con sasl_username: asociar queue-id ↔ usuario.
        if "sasl_username=" in line and "postfix/smtpd" in line:
            mu = re.search(r"sasl_username=([^\s,]+)", line)
            mq = re.search(r"postfix/smtpd\[\d+\]:\s+([0-9A-F]{6,}):", line)
            if mu and mq:
                user = mu.group(1).lower()
                if user and user != "(unavailable)":
                    qid_user[mq.group(1)] = user
            continue

        # 2) Línea de entrega con status=sent: contar contra el usuario del qid.
        if "status=sent" in line:
            mq = re.search(r"postfix/(?:smtp|lmtp|pipe|virtual)\[\d+\]:\s+([0-9A-F]{6,}):", line)
            if mq:
                user = qid_user.get(mq.group(1))
                if user and (wanted is None or user in wanted):
                    counts[user] += 1

    result = dict(counts)
    return result


def _line_ts(line: str):
    """Timestamp epoch de una línea de mail.log (ISO8601 al inicio), o None."""
    try:
        # 2026-06-08T03:44:31.189840+00:00 …
        iso = line[:19]
        dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S")
        return dt.timestamp()
    except (ValueError, IndexError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Agregador
# ─────────────────────────────────────────────────────────────────────────────
def collect() -> dict:
    """Junta todo para el endpoint del panel."""
    return {
        "services": services_status(),
        "queue":    mail_queue(),
        "rspamd":   rspamd_stats(),
        "summary":  log_summary(),
        "generated_at": datetime.utcnow().isoformat(),
    }
