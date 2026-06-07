"""
Helper para generar y aplicar reglas en la tabla nftables 'inet svqpanel'.

Estrategia: regenerar el archivo /etc/nftables/svqpanel-rules.nft entero desde
la BD y recargarlo con 'nft -f'. Más simple y robusto que diff incremental.

NO toca /etc/nftables.conf (lo gestiona install.sh). Solo escribe los includes
generados por el panel.
"""

import os
import re
import subprocess
import ipaddress
from typing import List, Tuple, Optional

NFT_BIN              = "/usr/sbin/nft"
NFT_TABLE            = "inet svqpanel"
NFT_RULES_FILE       = "/etc/nftables/svqpanel-rules.nft"
NFT_IPLISTS_FILE     = "/etc/nftables/svqpanel-iplists.nft"
NFT_PORTS_FILE       = "/etc/nftables/svqpanel-ports.nft"
NFT_MAIN_CONF        = "/etc/nftables.conf"

# Puertos abiertos de serie por SVQPanel (servicio amigable + si es crítico).
# 'critical' = cerrarlo deja el servidor/panel inaccesible (SSH, web, panel).
# El puerto del panel se resuelve dinámicamente (PANEL_WEB_PORT del entorno).
def _panel_web_port() -> int:
    try:
        return int(os.environ.get("PANEL_WEB_PORT") or 8083)
    except (ValueError, TypeError):
        return 8083


def base_ports_catalog() -> List[dict]:
    """Catálogo de puertos base con nombre de servicio y si son críticos."""
    pw = _panel_web_port()
    return [
        {"port": 22,  "proto": "tcp", "service": "SSH",          "critical": True},
        {"port": 80,  "proto": "tcp", "service": "HTTP",         "critical": True},
        {"port": 443, "proto": "tcp", "service": "HTTPS",        "critical": True},
        {"port": pw,  "proto": "tcp", "service": "Panel SVQ",    "critical": True},
        {"port": pw,  "proto": "udp", "service": "Panel SVQ (HTTP/3)", "critical": True},
        {"port": 25,  "proto": "tcp", "service": "SMTP",         "critical": False},
        {"port": 587, "proto": "tcp", "service": "Submission",   "critical": False},
        {"port": 465, "proto": "tcp", "service": "SMTPS",        "critical": False},
        {"port": 143, "proto": "tcp", "service": "IMAP",         "critical": False},
        {"port": 993, "proto": "tcp", "service": "IMAPS",        "critical": False},
        {"port": 110, "proto": "tcp", "service": "POP3",         "critical": False},
        {"port": 995, "proto": "tcp", "service": "POP3S",        "critical": False},
        {"port": 53,  "proto": "tcp", "service": "DNS",          "critical": False},
        {"port": 53,  "proto": "udp", "service": "DNS",          "critical": False},
    ]


def _set_for_proto(proto: str) -> str:
    return "base_tcp_ports" if proto == "tcp" else "base_udp_ports"


def list_base_ports() -> dict:
    """
    Lee del kernel qué puertos están en los sets base_tcp_ports/base_udp_ports
    y los cruza con el catálogo. Devuelve {available, ports:[{port,proto,service,
    critical,open}]}.
    """
    open_tcp, open_udp = set(), set()
    try:
        r = subprocess.run([NFT_BIN, "list", "table", "inet", "svqpanel"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            txt = r.stdout
            for set_name, dest in (("base_tcp_ports", open_tcp), ("base_udp_ports", open_udp)):
                m = re.search(rf"set {set_name} \{{(.*?)\}}", txt, re.DOTALL)
                if m:
                    for tok in re.findall(r"\d+(?:-\d+)?", m.group(1)):
                        if "-" in tok:
                            a, b = tok.split("-")
                            dest.update(range(int(a), int(b) + 1))
                        else:
                            dest.add(int(tok))
    except Exception as e:
        return {"available": False, "error": str(e), "ports": []}

    ports = []
    for c in base_ports_catalog():
        is_open = c["port"] in (open_tcp if c["proto"] == "tcp" else open_udp)
        ports.append({**c, "open": is_open})
    return {"available": True, "ports": ports}


def set_base_port(port: int, proto: str, open_: bool) -> Tuple[bool, str]:
    """Abre o cierra un puerto base (en vivo + persistente). proto: tcp|udp."""
    if proto not in ("tcp", "udp"):
        return False, "protocolo inválido"
    set_name = _set_for_proto(proto)
    if open_:
        ok, msg = nft_set_add_element(set_name, str(port))
    else:
        ok, msg = nft_set_delete_element(set_name, str(port))
    if not ok:
        return False, msg
    # Persistir el estado actual de ambos sets en un include propio
    persist_base_ports()
    return True, "ok"


def persist_base_ports() -> None:
    """
    Vuelca el estado actual de los sets base_* a /etc/nftables/svqpanel-ports.nft
    para que sobreviva a reinicios. Usa 'flush set' + 'add element' (idempotente).
    """
    state = list_base_ports()
    if not state.get("available"):
        return
    tcp = sorted({p["port"] for p in state["ports"] if p["proto"] == "tcp" and p["open"]})
    udp = sorted({p["port"] for p in state["ports"] if p["proto"] == "udp" and p["open"]})
    lines = [
        "# /etc/nftables/svqpanel-ports.nft",
        "# Generado por SVQPanel — puertos del sistema abiertos. NO editar a mano.",
        "",
        "flush set inet svqpanel base_tcp_ports",
        "flush set inet svqpanel base_udp_ports",
    ]
    if tcp:
        lines.append(f"add element inet svqpanel base_tcp_ports {{ {', '.join(map(str, tcp))} }}")
    if udp:
        lines.append(f"add element inet svqpanel base_udp_ports {{ {', '.join(map(str, udp))} }}")
    lines.append("")
    tmp = NFT_PORTS_FILE + ".tmp"
    os.makedirs(os.path.dirname(NFT_PORTS_FILE), exist_ok=True)
    with open(tmp, "w") as f:
        f.write("\n".join(lines))
    os.replace(tmp, NFT_PORTS_FILE)


def _is_ipv6(addr: str) -> bool:
    """True si addr (IP o CIDR) es IPv6."""
    if not addr:
        return False
    try:
        net = ipaddress.ip_network(addr.split("/")[0] + "/" + addr.split("/")[1] if "/" in addr else addr, strict=False)
        return net.version == 6
    except Exception:
        return ":" in addr


def _fmt_port_range(port_range: Optional[str]) -> Optional[str]:
    """'8000-9000' → '8000-9000', '80' → '80'."""
    if not port_range:
        return None
    return port_range.replace(" ", "")


def render_rules_nft(rules) -> str:
    """
    Genera el contenido de svqpanel-rules.nft a partir de la lista de
    FirewallRule activas. Cada regla se traduce a un 'add rule' que
    nftables aplica encima del esqueleto creado por install.sh.

    Las whitelists van como 'add element inet svqpanel whitelist_v[46]'
    en lugar de reglas, así integran con el set que ya tiene la chain.
    """
    lines = [
        "# /etc/nftables/svqpanel-rules.nft",
        "# Generado por SVQPanel — NO editar a mano.",
        "# Se regenera al aplicar cambios desde el panel.",
        "",
    ]

    # 1) Whitelists → elementos de los sets whitelist_v4 / whitelist_v6
    whitelist_elements_v4 = []
    whitelist_elements_v6 = []
    custom_rules          = []

    for r in rules:
        if not r.is_active:
            continue
        if r.is_whitelist and r.source_ip:
            if _is_ipv6(r.source_ip):
                whitelist_elements_v6.append(r.source_ip)
            else:
                whitelist_elements_v4.append(r.source_ip)
            continue
        # Otras reglas → traducir a 'add rule'
        custom_rules.append(r)

    if whitelist_elements_v4:
        lines.append("# ── Whitelist IPv4 ─────────────────────────────────────")
        lines.append(f"add element inet svqpanel whitelist_v4 {{ {', '.join(whitelist_elements_v4)} }}")
        lines.append("")
    if whitelist_elements_v6:
        lines.append("# ── Whitelist IPv6 ─────────────────────────────────────")
        lines.append(f"add element inet svqpanel whitelist_v6 {{ {', '.join(whitelist_elements_v6)} }}")
        lines.append("")

    if custom_rules:
        # Ordenar por priority asc (más bajo = se evalúa primero)
        custom_rules.sort(key=lambda x: (x.priority or 100, x.id))

        lines.append("# ── Reglas custom ──────────────────────────────────────")
        for r in custom_rules:
            lines.extend(_render_single_rule(r))
        lines.append("")

    return "\n".join(lines) + "\n"


def _render_single_rule(r) -> List[str]:
    """
    Convierte una FirewallRule en una o varias sentencias
    'add rule inet svqpanel input ...'.

    Reglas:
      - Sin source_ip: una sola regla (la tabla 'inet' cubre v4+v6 sin
        necesidad de duplicar). Para protocolo 'icmp' generamos UNA regla
        por familia porque el match difiere (icmp vs icmpv6).
      - Con source_ip: usamos el match 'ip saddr' o 'ip6 saddr' según
        la familia detectada en el CIDR.
    """
    out = []
    nft_action = {"allow": "accept", "deny": "drop", "reject": "reject"}[r.action]
    proto      = r.protocol if r.protocol != "any" else None
    port_range = _fmt_port_range(r.port_range)

    # Decidir qué (familia, source) emitimos
    branches: List[Tuple[Optional[str], Optional[str]]] = []
    if r.source_ip:
        family = "ip6" if _is_ipv6(r.source_ip) else "ip"
        branches.append((family, r.source_ip))
    elif proto == "icmp":
        # ICMP requiere doble regla porque el match cambia entre v4 y v6
        branches.append(("ip",  None))
        branches.append(("ip6", None))
    else:
        # tcp/udp/any sin source → una sola regla en family 'inet'
        branches.append((None, None))

    for family, src in branches:
        parts = ["add rule inet svqpanel input"]
        if src:
            parts.append(f"{family} saddr {src}")
        if proto in ("tcp", "udp"):
            if port_range:
                parts.append(f"{proto} dport {port_range}")
            else:
                parts.append(proto)
        elif proto == "icmp":
            parts.append("ip protocol icmp" if family == "ip" else "ip6 nexthdr icmpv6")
        parts.append(nft_action)
        if r.description:
            safe = r.description.replace('"', "'")
            parts.append(f'comment "{safe[:64]}"')
        out.append(" ".join(parts))
    return out


def write_rules_file(content: str) -> None:
    """Escribe svqpanel-rules.nft de forma atómica."""
    tmp = NFT_RULES_FILE + ".tmp"
    os.makedirs(os.path.dirname(NFT_RULES_FILE), exist_ok=True)
    with open(tmp, "w") as f:
        f.write(content)
    os.replace(tmp, NFT_RULES_FILE)


def reload_nftables() -> Tuple[bool, str]:
    """Recarga toda la config nftables. Devuelve (success, stderr_or_message)."""
    try:
        result = subprocess.run(
            [NFT_BIN, "-f", NFT_MAIN_CONF],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return False, result.stderr.strip() or "nft -f falló sin stderr"
        return True, "reloaded"
    except FileNotFoundError:
        return False, "nft no encontrado en /usr/sbin/nft (¿está instalado nftables?)"
    except subprocess.TimeoutExpired:
        return False, "nft -f superó el timeout"
    except Exception as e:
        return False, f"Error al recargar nftables: {e}"


def list_table_sets() -> List[str]:
    """Devuelve los sets presentes en la tabla 'inet svqpanel'."""
    try:
        result = subprocess.run(
            [NFT_BIN, "list", "table", "inet", "svqpanel"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return []
        sets = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("set ") and "{" in line:
                # 'set whitelist_v4 {'
                sets.append(line.split()[1])
        return sets
    except Exception:
        return []


def nft_set_add_element(set_name: str, element: str) -> Tuple[bool, str]:
    """Añade un elemento a un set en runtime (sin recargar)."""
    try:
        result = subprocess.run(
            [NFT_BIN, "add", "element", "inet", "svqpanel", set_name, f"{{ {element} }}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            err = result.stderr.strip()
            if "File exists" in err or "already exists" in err:
                return True, "exists"
            return False, err
        return True, "added"
    except Exception as e:
        return False, str(e)


def nft_set_delete_element(set_name: str, element: str) -> Tuple[bool, str]:
    """Elimina un elemento de un set en runtime."""
    try:
        result = subprocess.run(
            [NFT_BIN, "delete", "element", "inet", "svqpanel", set_name, f"{{ {element} }}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            err = result.stderr.strip()
            if "No such file" in err or "does not exist" in err:
                return True, "absent"
            return False, err
        return True, "deleted"
    except Exception as e:
        return False, str(e)


def table_exists() -> bool:
    """True si la tabla 'inet svqpanel' está cargada."""
    try:
        result = subprocess.run(
            [NFT_BIN, "list", "table", "inet", "svqpanel"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False
