"""
Comprobador unificado de bloqueo de una IP — el "¿está bloqueada esta IP?"
de la vista Seguridad.

Motivación (caso real, jul 2026): un cliente llevaba años quedándose
bloqueado y el panel decía que no había ban. El baneo vivía en CrowdSec y en
nftables, pero la vista de fail2ban no lo enseñaba y `cscli decisions list`
truncaba a las últimas 100 alertas. Este módulo consulta TODAS las capas de
una vez:

  1. fail2ban        (jails que la tienen baneada ahora)
  2. CrowdSec        (decisiones activas + allowlist + historial de alertas)
  3. nftables        (la verdad del firewall: sets que contienen la IP,
                      incluida la blocklist comunitaria CAPI)
  4. whitelists      (ignoreip de fail2ban, whitelist del panel)
"""

import ipaddress
import json
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional

from api.utils import crowdsec_helper as cs
from api.utils import fail2ban_helper as f2b
from api.utils.nftables_helper import NFT_BIN


def _nft(args: List[str], timeout: int = 6):
    try:
        return subprocess.run(
            [NFT_BIN] + args, capture_output=True, text=True, timeout=timeout
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _nft_sets_for_family(family_v6: bool) -> List[Dict[str, str]]:
    """Sets de nftables cuyo tipo de elemento casa con la familia de la IP.
    Devuelve [{family, table, name}]. Se listan TODOS los sets del sistema:
    así el buscador ve tanto los de CrowdSec (tabla ip/ip6 crowdsec*) como los
    del panel/fail2ban (inet svqpanel) sin hardcodear nombres."""
    r = _nft(["-j", "list", "sets"])
    if r is None or r.returncode != 0:
        return []
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return []
    want = "ipv6_addr" if family_v6 else "ipv4_addr"
    out = []
    for item in data.get("nftables", []):
        s = item.get("set")
        if not isinstance(s, dict):
            continue
        stype = s.get("type")
        # type puede ser string o lista (sets concatenados: los ignoramos)
        if stype != want:
            continue
        out.append({
            "family": s.get("family", ""),
            "table":  s.get("table", ""),
            "name":   s.get("name", ""),
        })
    return out


def _nft_sets_containing(ip: str) -> List[str]:
    """Sets de nftables que contienen la IP AHORA (lookup en kernel con
    `nft get element`, que resuelve también rangos/intervalos). Esta es la
    verdad última: si la IP está en un set con verdict drop, está bloqueada
    aunque fail2ban/CrowdSec digan lo contrario (p.ej. bouncer desincronizado)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return []
    hits: List[str] = []
    for s in _nft_sets_for_family(addr.version == 6):
        if not (s["family"] and s["table"] and s["name"]):
            continue
        r = _nft(["get", "element", s["family"], s["table"], s["name"], f"{{ {ip} }}"], timeout=4)
        if r is not None and r.returncode == 0:
            hits.append(f"{s['family']} {s['table']} {s['name']}")
    return hits


def check_ip(ip: str) -> Dict[str, Any]:
    """Estado de bloqueo completo de una IP en todas las capas."""
    ip = ip.strip()
    ipaddress.ip_address(ip)  # ValueError si no es una IP válida → 422 arriba

    f2b_jails = f2b.banned_in_jails(ip)
    cs_running = cs.is_installed() and cs.is_running()
    cs_decisions = cs.decisions_for_ip(ip) if cs_running else []
    cs_allowlist = cs.allowlisted(ip) if cs_running else None
    cs_history = cs.list_alerts(limit=20, ip=ip) if cs_running else []
    nft_sets = _nft_sets_containing(ip)

    ignoreip = f2b.get_ignoreip()
    whitelist_hits = {
        "fail2ban_ignoreip":  ip in ignoreip,
        "crowdsec_allowlist": cs_allowlist,
    }

    # Sets del panel llamados whitelist_* cuentan como lista blanca, no bloqueo.
    nft_whitelist = [s for s in nft_sets if "whitelist" in s.lower()]
    nft_block = [s for s in nft_sets if "whitelist" not in s.lower()]

    blocked = bool(f2b_jails or cs_decisions or nft_block)
    return {
        "ip":          ip,
        "checked_at":  datetime.utcnow().isoformat() + "Z",
        "blocked":     blocked,
        "fail2ban":    {"running": f2b.is_running(), "jails": f2b_jails},
        "crowdsec":    {
            "running":     cs_running,
            "decisions":   cs_decisions,
            "allowlisted": cs_allowlist,
        },
        "nftables":    {"blocking_sets": nft_block, "whitelist_sets": nft_whitelist},
        "whitelists":  whitelist_hits,
        "history":     cs_history,
    }
