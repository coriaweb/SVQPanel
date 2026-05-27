"""
IP List fetcher: descarga, parsea y aplica listas IP desde URL externa.

Cada lista se materializa en dos sets de nftables (uno IPv4, otro IPv6)
dentro de la tabla 'inet svqpanel'. Las reglas que los usan se generan en
/etc/nftables/svqpanel-iplists.nft.

Refresco diario vía systemd timer (ver install.sh + scripts/svqpanel-iplist-refresh*).
"""

import os
import re
import logging
import hashlib
import ipaddress
import socket
from datetime import datetime
from typing import List, Tuple, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from api.utils import nftables_helper as nft
from api.models.models_security import IpList

logger = logging.getLogger(__name__)

NFT_IPLISTS_FILE = "/etc/nftables/svqpanel-iplists.nft"
USER_AGENT       = "SVQPanel/0.1 (+https://github.com/coriaweb/SVQPanel)"
MAX_BYTES        = 10 * 1024 * 1024   # 10 MB
REQUEST_TIMEOUT  = 30                  # segundos

# IPs/CIDRs privados que NO permitimos como destino del fetch (SSRF)
_PRIVATE_RANGES_V4 = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
]
_PRIVATE_RANGES_V6 = [
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::/128"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Validación de URL y SSRF guard
# ─────────────────────────────────────────────────────────────────────────────
def url_resolves_safe(url: str) -> Tuple[bool, str]:
    """Bloquea URLs que apuntan a IPs privadas / link-local / loopback."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, f"Esquema no permitido: {parsed.scheme}"
    if not parsed.hostname:
        return False, "URL sin host"
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as e:
        return False, f"DNS no resuelve: {e}"
    for af, _stype, _proto, _cn, sa in infos:
        ip_str = sa[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        ranges = _PRIVATE_RANGES_V4 if ip.version == 4 else _PRIVATE_RANGES_V6
        for net in ranges:
            if ip in net:
                return False, f"Host resuelve a rango privado: {ip_str}"
    return True, "ok"


# ─────────────────────────────────────────────────────────────────────────────
# Parser de contenido
# ─────────────────────────────────────────────────────────────────────────────
_LINE_CLEAN_RE = re.compile(r"[#;].*$")


def parse_list_content(text: str, max_entries: int = 500_000) -> Tuple[List[str], List[str], List[str]]:
    """
    Devuelve (ipv4_entries, ipv6_entries, errors).

    Acepta una IP/CIDR por línea. Comentarios con # o ;. Líneas vacías y
    espacios extras se ignoran.
    """
    ipv4: List[str] = []
    ipv6: List[str] = []
    errors: List[str] = []
    total = 0

    for raw in text.splitlines():
        if total >= max_entries:
            errors.append(f"truncado en {max_entries} entradas")
            break

        line = _LINE_CLEAN_RE.sub("", raw).strip()
        if not line:
            continue
        # Algunas listas usan separadores tipo tabuladores con campos extra
        first_token = line.split()[0]

        try:
            net = ipaddress.ip_network(first_token, strict=False)
        except ValueError:
            errors.append(first_token)
            continue

        entry = str(net) if net.prefixlen != net.max_prefixlen else str(net.network_address)
        if net.version == 4:
            ipv4.append(entry)
        else:
            ipv6.append(entry)
        total += 1

    # Deduplicar manteniendo orden
    ipv4 = list(dict.fromkeys(ipv4))
    ipv6 = list(dict.fromkeys(ipv6))
    return ipv4, ipv6, errors


# ─────────────────────────────────────────────────────────────────────────────
# Fetch
# ─────────────────────────────────────────────────────────────────────────────
def fetch_url(url: str) -> Tuple[str, str]:
    """
    Descarga la URL con límite de tamaño y devuelve (texto, sha256).
    Lanza ValueError si falla o se excede el límite.
    """
    ok, msg = url_resolves_safe(url)
    if not ok:
        raise ValueError(f"URL bloqueada por seguridad: {msg}")

    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/plain, */*"})
    try:
        with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = resp.read(MAX_BYTES + 1)
    except (URLError, HTTPError, socket.timeout, TimeoutError) as e:
        raise ValueError(f"Error de red: {e}")

    if len(data) > MAX_BYTES:
        raise ValueError(f"Respuesta supera {MAX_BYTES} bytes")

    sha = hashlib.sha256(data).hexdigest()
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception as e:
        raise ValueError(f"Decode error: {e}")
    return text, sha


# ─────────────────────────────────────────────────────────────────────────────
# Aplicar a nftables
# ─────────────────────────────────────────────────────────────────────────────
def _set_name_for(iplist: IpList, family: str) -> str:
    return f"{'allow' if iplist.action == 'allow' else 'block'}_{family}_{iplist.name}"


def _set_decl(set_name: str, family: str) -> str:
    fam_type = "ipv4_addr" if family == "v4" else "ipv6_addr"
    return f"    set {set_name} {{ type {fam_type}; flags interval; }}"


def regenerate_iplists_nft(active_lists: List[Tuple[IpList, List[str], List[str]]]) -> str:
    """
    Genera el contenido completo de svqpanel-iplists.nft:
      1) Declaración de los sets (en bloque `table inet svqpanel { ... }`,
         nftables hace merge con la tabla declarada en /etc/nftables.conf).
      2) `add element` para poblar los sets.
      3) `add rule inet svqpanel input ...` para que la chain ya existente
         (creada en /etc/nftables.conf) consulte cada set.

    OJO: la chain `input` solo se DECLARA en /etc/nftables.conf — aquí solo
    añadimos reglas a ella con `add rule`. Redeclararla provocaría error
    de nftables ('Hook clash with chain input').
    """
    set_decls       = []
    elements_block  = []
    rules_block     = []

    for iplist, v4, v6 in active_lists:
        if not iplist.enabled:
            continue
        nft_action = "accept" if iplist.action == "allow" else "drop"

        if v4 and iplist.address_family in ("ipv4", "both"):
            s = _set_name_for(iplist, "v4")
            set_decls.append(_set_decl(s, "v4"))
            rules_block.append(
                f"add rule inet svqpanel input ip  saddr @{s} {nft_action} "
                f"comment \"iplist:{iplist.name}\""
            )
            for i in range(0, len(v4), 1024):
                chunk = v4[i:i+1024]
                elements_block.append(
                    f"add element inet svqpanel {s} {{ {', '.join(chunk)} }}"
                )

        if v6 and iplist.address_family in ("ipv6", "both"):
            s = _set_name_for(iplist, "v6")
            set_decls.append(_set_decl(s, "v6"))
            rules_block.append(
                f"add rule inet svqpanel input ip6 saddr @{s} {nft_action} "
                f"comment \"iplist:{iplist.name}\""
            )
            for i in range(0, len(v6), 1024):
                chunk = v6[i:i+1024]
                elements_block.append(
                    f"add element inet svqpanel {s} {{ {', '.join(chunk)} }}"
                )

    lines = [
        "# /etc/nftables/svqpanel-iplists.nft",
        "# Generado por SVQPanel — NO editar a mano.",
        "",
    ]
    if set_decls:
        lines.append("table inet svqpanel {")
        lines.extend(set_decls)
        lines.append("}")
        lines.append("")
    lines.extend(elements_block)
    if rules_block:
        lines.append("")
        lines.extend(rules_block)
    lines.append("")
    return "\n".join(lines)


def write_iplists_nft(content: str) -> None:
    os.makedirs(os.path.dirname(NFT_IPLISTS_FILE), exist_ok=True)
    tmp = NFT_IPLISTS_FILE + ".tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.replace(tmp, NFT_IPLISTS_FILE)


# ─────────────────────────────────────────────────────────────────────────────
# Refresh de una lista (fetch + parse + persist en BD)
# ─────────────────────────────────────────────────────────────────────────────
def refresh_one(iplist: IpList) -> Tuple[List[str], List[str], Optional[str]]:
    """
    Refresca una lista IP: fetch, parse y actualiza campos en el objeto
    (entry_count_v4, entry_count_v6, last_fetched_at, last_success_at, sha256_last,
    last_error). NO hace commit ni toca nftables.

    Devuelve (ipv4_entries, ipv6_entries, error_message_or_None).
    Si hay error, mantiene la cuenta anterior y last_success_at sin cambios.
    """
    iplist.last_fetched_at = datetime.utcnow()
    try:
        text, sha = fetch_url(iplist.url)
    except Exception as e:
        iplist.last_error = str(e)[:8000]
        return [], [], str(e)

    if iplist.sha256_last == sha:
        iplist.last_success_at = datetime.utcnow()
        iplist.last_error = None
        return [], [], "unchanged"   # Caller decide saltar regeneración

    v4, v6, parse_errors = parse_list_content(text, max_entries=iplist.max_entries)

    iplist.sha256_last     = sha
    iplist.last_success_at = datetime.utcnow()
    iplist.entry_count_v4  = len(v4)
    iplist.entry_count_v6  = len(v6)
    iplist.last_error      = None
    if parse_errors:
        sample = ", ".join(parse_errors[:5])
        iplist.last_error = f"Líneas no parseables (muestra): {sample}"

    return v4, v6, None
