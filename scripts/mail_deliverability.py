"""
Diagnóstico de deliverability del CORREO DEL PROPIO SERVIDOR.

El servidor reescribe (SRS) el envelope-from de los reenvíos a "...@<mydomain>",
donde mydomain es el dominio del servidor (p. ej. svqhost.red). Para que Gmail/
Outlook acepten esos reenvíos, ese dominio del servidor necesita estar autenticado:
  - SPF    declarando que la IP del servidor puede enviar por él.
  - DKIM    (clave del servidor publicada como TXT).
  - DMARC   (recomendado).
  - PTR/rDNS (que la IP resuelva al hostname).

A diferencia de los dominios de cliente (cuyo DNS gestiona el panel y publica
estos registros solo), el dominio del servidor suele tener el DNS en un proveedor
EXTERNO, así que el admin tiene que copiar los registros a mano. Esta vista se los
da hechos y verifica en vivo cuáles ya están publicados.

No tiene dependencias externas: usa `dig` (bind9-dnsutils) para las consultas y
reutiliza DkimManager para la clave del servidor.
"""

import re
import socket
import logging
import subprocess

logger = logging.getLogger(__name__)

SERVER_DKIM_SELECTOR = "mail"


def _run(cmd, timeout=6):
    """Ejecuta un comando y devuelve stdout (str) o '' si falla."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception as e:
        logger.debug(f"comando falló {cmd}: {e}")
        return ""


def get_server_mail_domain():
    """Dominio con el que el servidor firma/reescribe el correo (mydomain de Postfix).

    Fuente de verdad: `postconf -h mydomain`; fallback a la parte de dominio del
    FQDN del host.
    """
    dom = _run(["postconf", "-h", "mydomain"])
    if dom:
        return dom.strip().rstrip(".").lower()
    fqdn = socket.getfqdn()
    if "." in fqdn:
        return fqdn.split(".", 1)[1].lower()
    return fqdn.lower()


def _dig_txt(name):
    """Devuelve la lista de valores TXT publicados para `name` (DNS público).

    Usa el resolver del sistema. Limpia comillas y junta cadenas partidas.
    """
    out = _run(["dig", "+short", "TXT", name])
    values = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        # dig devuelve los TXT entre comillas; cadenas largas vienen partidas:
        #   "v=DKIM1; k=rsa; " "p=MIIB..."
        parts = re.findall(r'"((?:[^"\\]|\\.)*)"', line)
        joined = "".join(parts) if parts else line
        values.append(joined)
    return values


def _dig_ptr(ip):
    out = _run(["dig", "+short", "-x", ip])
    return out.splitlines()[0].strip().rstrip(".") if out else ""


def _check(name_present, ok, expected, found, severity="error", help_text=""):
    return {
        "name": name_present,
        "ok": ok,
        "expected": expected,
        "found": found,
        "severity": severity,   # "error" | "warn" | "ok"
        "help": help_text,
    }


def diagnose(server_ipv4=None, server_ipv6=None):
    """Diagnóstico completo del correo del servidor.

    Devuelve dict con: domain, dns_external (bool), records (lista de chequeos),
    all_ok (bool). Cada record trae el valor exacto a publicar y si ya está OK.
    """
    domain = get_server_mail_domain()

    # IP del servidor: la pasada (de Settings) o, en su defecto, autodetectada.
    ipv4 = (server_ipv4 or "").strip()
    if not ipv4:
        ipv4 = _run(["dig", "+short", "A", domain]) .splitlines()
        ipv4 = ipv4[0].strip() if ipv4 else ""

    records = []

    # ── SPF ──────────────────────────────────────────────────────────────────
    spf_published = [v for v in _dig_txt(domain) if v.lower().startswith("v=spf1")]
    ip_part = f" ip4:{ipv4}" if ipv4 else ""
    ip6_part = f" ip6:{server_ipv6}" if server_ipv6 else ""
    spf_expected = f"v=spf1 a mx{ip_part}{ip6_part} ~all"
    spf_ok = False
    spf_found = spf_published[0] if spf_published else ""
    if spf_published:
        # Aceptamos como OK si declara la IP del servidor (ip4:) o un mecanismo que
        # pueda autorizarla (a / mx / include) — no exigimos texto literal idéntico,
        # el admin puede tener un SPF más completo.
        toks = spf_published[0].lower().split()
        spf_ok = (
            (ipv4 and f"ip4:{ipv4}" in toks)
            or "a" in toks or "mx" in toks
            or any(t.startswith(("a:", "mx:", "include:", "ip4:")) for t in toks)
        )
    records.append(_check(
        "SPF", spf_ok, spf_expected, spf_found,
        severity="error",
        help_text=f"Registro TXT en la raíz (@) de {domain}. Sin SPF, los reenvíos "
                  f"a Gmail/Outlook se rechazan ('unauthenticated')."))

    # ── DKIM (clave del servidor) ─────────────────────────────────────────────
    dkim_name = f"{SERVER_DKIM_SELECTOR}._domainkey.{domain}"
    dkim_expected = ""
    dkim_have_key = False
    try:
        from scripts.dkim_manager import DkimManager
        dk = DkimManager()
        if dk.dkim_available():
            info = dk.get_key_info(domain, SERVER_DKIM_SELECTOR)
            if info:
                dkim_have_key = True
                dkim_expected = info["dns_record_value"]
    except Exception as e:
        logger.warning(f"No se pudo leer la clave DKIM del servidor: {e}")

    dkim_published = [v for v in _dig_txt(dkim_name) if "DKIM1" in v or v.startswith("k=") or "p=" in v]
    dkim_found = dkim_published[0] if dkim_published else ""
    # OK si está publicado y, si tenemos la clave local, coincide la parte p=.
    dkim_ok = False
    if dkim_published:
        if dkim_have_key:
            exp_p = _extract_p(dkim_expected)
            got_p = _extract_p(dkim_found)
            dkim_ok = bool(exp_p) and exp_p == got_p
        else:
            dkim_ok = True  # hay algo publicado y no tenemos clave local con que comparar
    records.append(_check(
        dkim_name, dkim_ok, dkim_expected, dkim_found,
        severity="error",
        help_text=("Registro TXT con la clave pública DKIM del servidor. "
                   + ("" if dkim_have_key else
                      "Aún no hay clave DKIM generada en el servidor; genérala primero."))))

    # ── DMARC ──────────────────────────────────────────────────────────────────
    dmarc_name = f"_dmarc.{domain}"
    dmarc_published = [v for v in _dig_txt(dmarc_name) if v.lower().startswith("v=dmarc1")]
    dmarc_expected = f"v=DMARC1; p=quarantine; rua=mailto:dmarc@{domain}; fo=1"
    dmarc_found = dmarc_published[0] if dmarc_published else ""
    records.append(_check(
        dmarc_name, bool(dmarc_published), dmarc_expected, dmarc_found,
        severity="warn",
        help_text="Recomendado. Indica a los destinatarios qué hacer con el correo "
                  "que no pase SPF/DKIM."))

    # ── PTR / rDNS ──────────────────────────────────────────────────────────────
    # FQDN esperado: el hostname del propio servidor. socket.getfqdn() a veces da
    # solo el nombre corto, así que lo componemos con `postconf -h myhostname`.
    expected_ptr = (_run(["postconf", "-h", "myhostname"]) or socket.getfqdn()).rstrip(".")
    ptr_found = _dig_ptr(ipv4) if ipv4 else ""
    ptr_ok = bool(ptr_found) and ptr_found.lower() == expected_ptr.lower()
    records.append(_check(
        "PTR (rDNS)", ptr_ok, expected_ptr, ptr_found,
        severity="warn",
        help_text="El reverso de la IP debe apuntar al hostname del servidor. "
                  "Esto se configura en el panel del proveedor del VPS, no en el DNS."))

    # ── ¿El DNS del dominio del servidor lo gestiona este panel? ───────────────
    dns_external = not _domain_zone_local(domain)

    # all_ok: los 'error' deben estar OK (SPF + DKIM). Los 'warn' no bloquean.
    all_ok = all(r["ok"] for r in records if r["severity"] == "error")

    return {
        "domain": domain,
        "server_ipv4": ipv4,
        "dns_external": dns_external,
        "dkim_key_present": dkim_have_key,
        "dkim_selector": SERVER_DKIM_SELECTOR,
        "records": records,
        "all_ok": all_ok,
    }


def _extract_p(txt):
    """Saca el valor de p= (clave pública) de un TXT DKIM, normalizado."""
    m = re.search(r"p=([A-Za-z0-9+/=]+)", txt or "")
    return m.group(1) if m else ""


def _domain_zone_local(domain):
    """True si la zona DNS del dominio la sirve el BIND local (panel/cluster)."""
    # Si hay un fichero de zona o la BD del panel tiene la zona, es interno.
    import os
    candidates = [
        f"/etc/bind/zones/db.{domain}",
        f"/etc/bind/zones/{domain}.db",
        f"/var/lib/bind/db.{domain}",
    ]
    return any(os.path.exists(p) for p in candidates)
