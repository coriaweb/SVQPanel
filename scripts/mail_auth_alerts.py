"""
Detección de cuentas de correo mal configuradas a partir de los fallos de
autenticación (Dovecot / Postfix SASL) del journal de systemd.

Objetivo: avisar al cliente (y al admin) cuando un dispositivo suyo está
fallando el login repetidamente, lo que provoca el bloqueo temporal por
fail2ban. Distingue dos casos:

  - wrong_password: el buzón EXISTE y acumula muchos fallos recientes
    (contraseña mal puesta en algún dispositivo).
  - wrong_username: el usuario NO existe pero el dominio es nuestro
    (cliente con el nombre de usuario equivocado en su cliente de correo).

Solo lee el journal (no toca disco de buzones) y cachea el resultado crudo
unos segundos, igual que el monitor de correo. La geolocalización de la IP
se obtiene con `whois` local (operador + país), cacheada en memoria.
"""
from __future__ import annotations

import re
import subprocess
import time as _time
from collections import defaultdict
from datetime import datetime, timedelta

import logging

logger = logging.getLogger(__name__)

# Umbral de fallos (en la ventana) para levantar alerta. Coincide con el
# maxretry de fail2ban: a partir de aquí hay riesgo real de bloqueo.
MIN_FAILURES = 5
# Ventana de tiempo: solo fallos recientes (un problema viejo ya resuelto no
# debe seguir alarmando).
WINDOW_HOURS = 24

# ── Caché del journal parseado (la parte cara) ───────────────────────────────
_CACHE_TTL = 60           # s
_cache: dict = {"ts": 0.0, "fails": None}

# Caché de geo (IP → "Operador · Ciudad, País"); no caduca en la vida del proceso.
_geo_cache: dict[str, str] = {}

# Bases GeoIP (MaxMind/DB-IP). ASN da el operador; City/Country dan la ubicación.
# La del panel la mantiene web_stats (DB-IP country); las de CrowdSec son GeoLite2.
_GEOIP_ASN_DBS = [
    "/var/lib/crowdsec/data/GeoLite2-ASN.mmdb",
]
_GEOIP_CITY_DBS = [
    "/var/lib/crowdsec/data/GeoLite2-City.mmdb",
    "/var/lib/svqpanel/geoip/dbip-country.mmdb",  # solo país, pero sirve de fallback
]
# Lectores mmdb abiertos perezosamente y cacheados.
_mmdb_readers: dict[str, object] = {}

# Dovecot: "...(auth failed, N attempts...): user=<X>, method=.., rip=1.2.3.4..."
_RE_DOVE = re.compile(
    r"(?P<proto>imap|pop3|submission|managesieve)-login:.*?"
    r"auth failed[^)]*\):\s*user=<(?P<user>[^>]*)>.*?rip=(?P<ip>[\d.]+)"
)
# Postfix SASL: "warning: host[ip]: SASL LOGIN authentication failed: ...,
#   sasl_username=user@dom"
_RE_SASL = re.compile(
    r"\[(?P<ip>[\d.]+)\]:\s+SASL\s+\w+\s+authentication failed.*?"
    r"sasl_username=(?P<user>\S+)"
)


def _journalctl_since(hours: int) -> list[str]:
    """Líneas de Dovecot + Postfix del journal en las últimas `hours` horas."""
    try:
        out = subprocess.run(
            ["journalctl", "-u", "dovecot", "-u", "postfix@-.service",
             "--since", f"-{hours}h", "--no-pager", "-o", "short-iso"],
            capture_output=True, text=True, timeout=60,
        )
        return out.stdout.splitlines()
    except Exception as e:
        logger.warning(f"mail_auth_alerts: no se pudo leer el journal: {e}")
        return []


def _parse_ts(line: str):
    m = re.match(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})", line)
    if not m:
        return None
    try:
        return datetime.fromisoformat(m.group(1).replace("T", " "))
    except ValueError:
        return None


def _collect_failures(hours: int) -> dict:
    """Agrega fallos por usuario (en minúsculas). Devuelve:
    { user: {count, ips:{ip:n}, protos:{p:n}, last:datetime} }.
    Usa caché TTL para no releer el journal en cada petición."""
    now = _time.monotonic()
    if _cache["fails"] is not None and (now - _cache["ts"]) < _CACHE_TTL:
        return _cache["fails"]

    cutoff = datetime.now() - timedelta(hours=hours)
    data: dict = defaultdict(
        lambda: {"count": 0, "ips": defaultdict(int),
                 "protos": defaultdict(int), "last": None}
    )
    for line in _journalctl_since(hours):
        user = ip = proto = None
        m = _RE_DOVE.search(line)
        if m:
            user = m.group("user").lower()
            ip = m.group("ip")
            proto = m.group("proto")
        else:
            m = _RE_SASL.search(line)
            if m:
                u = m.group("user")
                if u in ("(unavailable)", "()", ""):
                    continue
                user = u.strip("<>").lower()
                ip = m.group("ip")
                proto = "smtp"
        if not user or "@" not in user:
            continue
        ts = _parse_ts(line)
        if ts and ts < cutoff:
            continue
        d = data[user]
        d["count"] += 1
        d["ips"][ip] += 1
        d["protos"][proto] += 1
        if ts and (d["last"] is None or ts > d["last"]):
            d["last"] = ts

    _cache["fails"] = data
    _cache["ts"] = now
    return data


def _mmdb_reader(path: str):
    """Devuelve (y cachea) un lector mmdb para `path`, o None si no se puede."""
    if path in _mmdb_readers:
        return _mmdb_readers[path]
    reader = None
    try:
        import os as _os
        if _os.path.isfile(path) and _os.path.getsize(path) > 0:
            import maxminddb
            reader = maxminddb.open_database(path)
    except Exception:
        reader = None
    _mmdb_readers[path] = reader
    return reader


def _geo_mmdb(ip: str) -> str:
    """Operador · Ciudad, País usando las bases GeoIP. '' si no hay datos."""
    org = ""
    for p in _GEOIP_ASN_DBS:
        r = _mmdb_reader(p)
        if not r:
            continue
        try:
            rec = r.get(ip) or {}
            org = rec.get("autonomous_system_organization", "") or ""
            if org:
                break
        except Exception:
            pass
    place = ""
    for p in _GEOIP_CITY_DBS:
        r = _mmdb_reader(p)
        if not r:
            continue
        try:
            rec = r.get(ip) or {}
            country = (rec.get("country", {}).get("names", {}).get("es")
                       or rec.get("country", {}).get("names", {}).get("en") or "")
            city = (rec.get("city", {}).get("names", {}).get("es")
                    or rec.get("city", {}).get("names", {}).get("en") or "")
            place = f"{city}, {country}".strip(", ") if (city or country) else ""
            if place:
                break
        except Exception:
            pass
    if org and place:
        return f"{org} · {place}"
    return org or place


def _geo_whois(ip: str) -> str:
    """Fallback: operador + país de una IP vía whois local."""
    try:
        out = subprocess.run(["whois", ip], capture_output=True,
                             text=True, timeout=8).stdout
    except Exception:
        return ""
    org = country = ""
    for ln in out.splitlines():
        low = ln.lower()
        if not org and (low.startswith("descr:") or low.startswith("netname:")
                        or low.startswith("org-name:") or low.startswith("orgname:")):
            org = ln.split(":", 1)[1].strip()
        elif not country and low.startswith("country:"):
            country = ln.split(":", 1)[1].strip().upper()
    if org and country:
        return f"{org} ({country})"
    return org or country


def _geo(ip: str) -> str:
    """Geolocalización de una IP (operador + lugar). Cacheada. Best-effort:
    primero GeoIP (MaxMind/DB-IP), y si no hay datos cae a whois local."""
    if ip in _geo_cache:
        return _geo_cache[ip]
    label = _geo_mmdb(ip) or _geo_whois(ip)
    _geo_cache[ip] = label
    return label


_PROTO_ES = {
    "imap": "IMAP (correo entrante)",
    "pop3": "POP3 (correo entrante)",
    "smtp": "SMTP (correo saliente)",
    "submission": "SMTP (correo saliente)",
    "managesieve": "filtros (Sieve)",
}


def detect_account_issues(mail_domains, db) -> list[dict]:
    """Devuelve la lista de alertas para los dominios de correo dados.

    `mail_domains`: iterable de MailDomain ya filtrados por permiso (el caller
    decide qué dominios ve cada rol). `db`: sesión para leer los buzones reales.
    """
    from api.models.models_mail import Mailbox

    if not mail_domains:
        return []

    domains_by_name = {md.domain_name.lower(): md for md in mail_domains}
    dom_ids = [md.id for md in mail_domains]

    # Buzones reales (de BD) de esos dominios: dom → set(local_parts)
    boxes_by_dom: dict[str, set] = defaultdict(set)
    if dom_ids:
        rows = db.query(Mailbox).filter(Mailbox.mail_domain_id.in_(dom_ids)).all()
        id_to_name = {md.id: md.domain_name.lower() for md in mail_domains}
        for mb in rows:
            dn = id_to_name.get(mb.mail_domain_id)
            if dn:
                boxes_by_dom[dn].add(mb.username.lower())

    fails = _collect_failures(WINDOW_HOURS)
    alerts: list[dict] = []

    for user, d in fails.items():
        if d["count"] < MIN_FAILURES:
            continue
        try:
            local, dom = user.split("@", 1)
        except ValueError:
            continue
        dom = dom.lower()
        md = domains_by_name.get(dom)
        if not md:
            continue  # dominio no es de este usuario / no alojado → bot, ignorar

        exists = local in boxes_by_dom.get(dom, set())
        kind = "wrong_password" if exists else "wrong_username"

        top_ips = sorted(d["ips"].items(), key=lambda x: x[1], reverse=True)[:2]
        top_proto = max(d["protos"].items(), key=lambda x: x[1])[0] if d["protos"] else "?"
        devices = [{"ip": ip, "hits": n, "geo": _geo(ip)} for ip, n in top_ips]

        suggestions = []
        if kind == "wrong_username":
            suggestions = sorted(boxes_by_dom.get(dom, set()))[:6]

        alerts.append({
            # id estable por (tipo, cuenta) para descartar en el front
            "id": f"{kind}:{user}",
            "kind": kind,
            "account": user,
            "domain": dom,
            "domain_id": md.id,
            "failures": d["count"],
            "protocol": top_proto,
            "protocol_label": _PROTO_ES.get(top_proto, top_proto),
            "devices": devices,
            "last_attempt": d["last"].strftime("%Y-%m-%d %H:%M") if d["last"] else None,
            "suggestions": suggestions,
            "at_risk": d["count"] >= MIN_FAILURES,  # ya en zona de bloqueo
        })

    # Más fallos primero
    alerts.sort(key=lambda a: a["failures"], reverse=True)
    return alerts
