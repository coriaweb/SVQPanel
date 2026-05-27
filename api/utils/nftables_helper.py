"""
Helper para generar y aplicar reglas en la tabla nftables 'inet svqpanel'.

Estrategia: regenerar el archivo /etc/nftables/svqpanel-rules.nft entero desde
la BD y recargarlo con 'nft -f'. Más simple y robusto que diff incremental.

NO toca /etc/nftables.conf (lo gestiona install.sh). Solo escribe los includes
generados por el panel.
"""

import os
import subprocess
import ipaddress
from typing import List, Tuple, Optional

NFT_BIN              = "/usr/sbin/nft"
NFT_TABLE            = "inet svqpanel"
NFT_RULES_FILE       = "/etc/nftables/svqpanel-rules.nft"
NFT_IPLISTS_FILE     = "/etc/nftables/svqpanel-iplists.nft"
NFT_MAIN_CONF        = "/etc/nftables.conf"


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
    """Convierte una FirewallRule a sentencias 'add rule inet svqpanel input ...'."""
    out = []
    family_branches: List[Tuple[str, Optional[str]]] = []
    # Decidir si la regla aplica a v4, v6 o ambas según source_ip
    if r.source_ip:
        if _is_ipv6(r.source_ip):
            family_branches.append(("ip6", r.source_ip))
        else:
            family_branches.append(("ip",  r.source_ip))
    else:
        # Sin source → aplicar a ambas familias
        family_branches.append(("ip",  None))
        family_branches.append(("ip6", None))

    # Acción nftables
    nft_action = {"allow": "accept", "deny": "drop", "reject": "reject"}[r.action]

    proto = r.protocol if r.protocol != "any" else None
    port_range = _fmt_port_range(r.port_range)

    for family, src in family_branches:
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
        # Comentario opcional
        if r.description:
            safe = r.description.replace('"', "'")
            parts.append(f'comment "{safe[:64]}"')
        parts.append(nft_action)
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
