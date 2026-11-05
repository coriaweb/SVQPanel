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

# Cadena a la que salta `input` ANTES de aceptar los puertos base. Las reglas
# custom y las listas IP van aquí: si fueran al final de `input` (como antes),
# un drop sobre un puerto abierto no haría nada (el accept ya lo dejó pasar).
NFT_PRE_CHAIN        = "svq_pre"
# Cadena de las listas IP (bloqueo por país, etc.), tras svq_pre y también
# antes de los puertos base. Empieza con `tcp dport 25 return` (en el conf): el
# SMTP entrante queda fuera del geo-bloqueo para no rechazar correo legítimo de
# MTAs de esos países (Gmail/Outlook/SES tienen servidores en Asia).
NFT_LISTS_CHAIN      = "svq_lists"


def _declared_chain(name: str) -> str:
    """`name` si el nftables.conf ya declara esa cadena (install nuevo o update
    0174); si no, `input` (conf antiguo: mantener el comportamiento viejo antes
    que romper el nft -f con una cadena inexistente)."""
    try:
        with open(NFT_MAIN_CONF) as f:
            if re.search(rf"^\s*chain\s+{name}\b", f.read(), re.M):
                return name
    except OSError:
        pass
    return "input"


def pre_chain() -> str:
    """Cadena de las reglas custom (Seguridad → Firewall)."""
    return _declared_chain(NFT_PRE_CHAIN)


def lists_chain() -> str:
    """Cadena de las listas IP / bloqueo por país."""
    return _declared_chain(NFT_LISTS_CHAIN)

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
        {"port": 443, "proto": "udp", "service": "HTTPS (HTTP/3)", "critical": False},
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


def _read_port_set(set_name: str) -> Optional[List[str]]:
    """Elementos (puertos o rangos 'a-b') de un set de puertos base, tal cual
    están en el kernel. None si no se pudo leer (≠ set vacío).

    Listamos SOLO el set, NO toda la tabla: 'nft list table' vuelca también los
    miles de rangos del geo-bloqueo (~20k líneas → ~0.7s); esto es ~0.01s."""
    r = subprocess.run(
        [NFT_BIN, "list", "set", "inet", "svqpanel", set_name],
        capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        return None
    m = re.search(r"elements\s*=\s*\{(.*?)\}", r.stdout, re.DOTALL)
    return re.findall(r"\d+(?:-\d+)?", m.group(1)) if m else []


def _expand_ports(tokens: List[str]) -> set:
    out = set()
    for tok in tokens:
        if "-" in tok:
            a, b = tok.split("-")
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(tok))
    return out


def list_base_ports() -> dict:
    """
    Lee del kernel qué puertos están en los sets base_tcp_ports/base_udp_ports
    y los cruza con el catálogo. Devuelve {available, ports:[{port,proto,service,
    critical,open}]}.
    """
    try:
        tcp_tok = _read_port_set("base_tcp_ports")
        udp_tok = _read_port_set("base_udp_ports")
    except Exception as e:
        return {"available": False, "error": str(e), "ports": []}
    if tcp_tok is None or udp_tok is None:
        return {"available": False, "error": "no se pudieron leer los sets de puertos base", "ports": []}
    open_tcp, open_udp = _expand_ports(tcp_tok), _expand_ports(udp_tok)

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


def render_ports_nft(tcp: List[str], udp: List[str]) -> str:
    """Contenido de svqpanel-ports.nft. nftables.conf lo incluye DESPUÉS de
    declarar la tabla, así que pisa los puertos de fábrica de los sets."""
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
    return "\n".join(lines)


def persist_base_ports() -> bool:
    """
    Vuelca el estado actual de los sets base_* a /etc/nftables/svqpanel-ports.nft
    para que sobreviva a reinicios y recargas. Usa 'flush set' + 'add element'.

    Guarda los elementos TAL CUAL están en el kernel (no solo los del catálogo):
    si el puerto del panel no coincide con PANEL_WEB_PORT del entorno, filtrar
    por catálogo lo perdería y la siguiente recarga cerraría el panel.
    Si no se puede leer algún set NO escribe nada: un archivo con el set vacío
    cerraría todos los puertos (SSH incluido) al reiniciar.
    """
    try:
        tcp = _read_port_set("base_tcp_ports")
        udp = _read_port_set("base_udp_ports")
    except Exception:
        return False
    if tcp is None or udp is None:
        return False
    key = lambda t: int(t.split("-")[0])
    content = render_ports_nft(sorted(set(tcp), key=key), sorted(set(udp), key=key))
    tmp = NFT_PORTS_FILE + ".tmp"
    os.makedirs(os.path.dirname(NFT_PORTS_FILE), exist_ok=True)
    with open(tmp, "w") as f:
        f.write(content)
    os.replace(tmp, NFT_PORTS_FILE)
    return True


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


def is_block_everything(r) -> bool:
    """deny/reject sin origen, sin puerto y protocolo any = cortar TODO el
    tráfico entrante (salvo whitelist). La política DROP ya bloquea lo no
    abierto, así que esta regla solo serviría para dejar el servidor inaccesible."""
    return (r.action in ("deny", "reject") and not r.source_ip
            and not _fmt_port_range(r.port_range)
            and (r.protocol or "any") == "any")


def render_rules_nft(rules, chain: Optional[str] = None) -> str:
    """
    Genera el contenido de svqpanel-rules.nft a partir de la lista de
    FirewallRule activas. Cada regla se traduce a un 'add rule' en la cadena
    `svq_pre`, que `input` evalúa ANTES de aceptar los puertos base: así un
    deny/reject sobre un puerto abierto funciona de verdad.

    Las whitelists van como 'add element inet svqpanel whitelist_v[46]'
    en lugar de reglas, así integran con el set que ya tiene la chain.
    """
    chain = chain or pre_chain()
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
            if is_block_everything(r):
                lines.append(f"# regla #{r.id} ignorada: {r.action} de todo el tráfico "
                             "(sin origen ni puerto) dejaría el servidor inaccesible")
                continue
            lines.extend(_render_single_rule(r, chain))
        lines.append("")

    return "\n".join(lines) + "\n"


def _render_single_rule(r, chain: str = NFT_PRE_CHAIN) -> List[str]:
    """
    Convierte una FirewallRule en una o varias sentencias
    'add rule inet svqpanel <chain> ...'.

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
        parts = [f"add rule inet svqpanel {chain}"]
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
        _load_missing_includes()
        return True, "reloaded"
    except FileNotFoundError:
        return False, "nft no encontrado en /usr/sbin/nft (¿está instalado nftables?)"
    except subprocess.TimeoutExpired:
        return False, "nft -f superó el timeout"
    except Exception as e:
        return False, f"Error al recargar nftables: {e}"


def _load_missing_includes() -> None:
    """Red de seguridad: si /etc/nftables.conf NO incluye los archivos donde el
    panel persiste los puertos cerrados y el MySQL remoto (conf anterior al
    update 0174, o editado a mano), `nft -f` acaba de devolver los puertos de
    fábrica y borrar la allowlist del 3306. Los cargamos aquí a mano."""
    try:
        with open(NFT_MAIN_CONF) as f:
            conf = f.read()
    except OSError:
        return
    if os.path.basename(NFT_PORTS_FILE) not in conf and os.path.isfile(NFT_PORTS_FILE) \
            and os.path.getsize(NFT_PORTS_FILE) > 0:
        subprocess.run([NFT_BIN, "-f", NFT_PORTS_FILE], capture_output=True, text=True, timeout=10)
    if os.path.basename(NFT_MYSQL_FILE) not in conf and os.path.isfile(NFT_MYSQL_FILE) \
            and os.path.getsize(NFT_MYSQL_FILE) > 0:
        ensure_mysql_remote_setup()   # el set y la regla no los declara un conf viejo
        subprocess.run([NFT_BIN, "-f", NFT_MYSQL_FILE], capture_output=True, text=True, timeout=10)


# ─────────────────────────────────────────────────────────────────────────────
# Migración de un /etc/nftables.conf antiguo (update 0174)
# ─────────────────────────────────────────────────────────────────────────────
_PORTS_INCLUDE = f'include "{NFT_PORTS_FILE}"'
_MYSQL_INCLUDE = 'include "/etc/nftables/svqpanel-mysql-remote.nft"'
_IPLISTS_INCLUDE = f'include "{NFT_IPLISTS_FILE}"'


def patch_main_conf(text: str) -> Tuple[Optional[str], List[str]]:
    """
    Lleva un nftables.conf de SVQPanel anterior a 0.274.0 al formato nuevo:
      - set mysql_remote_allow + chains svq_pre / svq_lists declarados,
      - `jump svq_pre` y `jump svq_lists` tras la whitelist (antes del accept
        de los puertos base),
      - accept del 3306 desde @mysql_remote_allow,
      - includes de svqpanel-ports.nft y svqpanel-mysql-remote.nft.
    Idempotente. Devuelve (texto_nuevo, cambios) o (None, [motivo]) si el conf
    no tiene la forma esperada (editado a mano): entonces NO se toca.
    """
    changes: List[str] = []
    lines = text.split("\n")

    def find(pattern: str) -> int:
        rx = re.compile(pattern)
        return next((i for i, l in enumerate(lines) if rx.search(l)), -1)

    i_input = find(r"^\s*chain\s+input\s*\{")
    i_wl6 = find(r"^\s*ip6\s+saddr\s+@whitelist_v6\s+accept")
    i_udp = find(r"^\s*udp\s+dport\s+@base_udp_ports\s+accept")
    i_inc = find(r'^\s*include\s+"/etc/nftables/svqpanel-iplists\.nft"')
    if min(i_input, i_wl6, i_udp, i_inc) < 0 or not (i_input < i_wl6 < i_udp < i_inc):
        return None, ["nftables.conf sin la estructura de SVQPanel (¿editado a mano?)"]

    # De abajo arriba para no desplazar los índices ya calculados.
    if not any(_PORTS_INCLUDE in l for l in lines):
        lines[i_inc:i_inc] = [_PORTS_INCLUDE]
        changes.append("include svqpanel-ports.nft")
    if not any(_MYSQL_INCLUDE in l for l in lines):
        i = find(r'^\s*include\s+"/etc/nftables/svqpanel-iplists\.nft"')
        lines[i:i] = [_MYSQL_INCLUDE]
        changes.append("include svqpanel-mysql-remote.nft")
    if find(r"@mysql_remote_allow\s+accept") < 0:
        lines[i_udp + 1:i_udp + 1] = [
            "",
            "        # MySQL remoto: solo desde las IPs autorizadas",
            "        tcp dport 3306 ip saddr @mysql_remote_allow accept",
        ]
        changes.append("accept 3306 desde @mysql_remote_allow")
    jumps = []
    if find(rf"^\s*jump\s+{NFT_PRE_CHAIN}\b") < 0:
        jumps += ["", "        # Reglas custom (antes de los puertos base)",
                  f"        jump {NFT_PRE_CHAIN}"]
        changes.append(f"jump {NFT_PRE_CHAIN}")
    if find(rf"^\s*jump\s+{NFT_LISTS_CHAIN}\b") < 0:
        # Tras svq_pre: si ya estaba el jump a svq_pre, insertar detrás de él
        i_pre = find(rf"^\s*jump\s+{NFT_PRE_CHAIN}\b")
        block = ["        # Listas IP / bloqueo por país (antes de los puertos base)",
                 f"        jump {NFT_LISTS_CHAIN}"]
        if i_pre >= 0:
            lines[i_pre + 1:i_pre + 1] = block
        else:
            jumps += block
        changes.append(f"jump {NFT_LISTS_CHAIN}")
    if jumps:
        lines[i_wl6 + 1:i_wl6 + 1] = jumps
    new_decl = []
    if find(r"^\s*set\s+mysql_remote_allow\b") < 0:
        new_decl += [
            "    # IPs autorizadas a MySQL remoto (persistidas en svqpanel-mysql-remote.nft)",
            "    set mysql_remote_allow { type ipv4_addr; flags interval; }",
            "",
        ]
        changes.append("set mysql_remote_allow")
    if find(rf"^\s*chain\s+{NFT_PRE_CHAIN}\b") < 0:
        new_decl += [
            "    # Reglas custom: se evalúan ANTES del accept de los puertos base",
            f"    chain {NFT_PRE_CHAIN} {{",
            "    }",
            "",
        ]
        changes.append(f"chain {NFT_PRE_CHAIN}")
    if find(rf"^\s*chain\s+{NFT_LISTS_CHAIN}\b") < 0:
        new_decl += [
            "    # Listas IP / bloqueo por país. El SMTP entrante (25) queda fuera:",
            "    # rechazaría correo legítimo de servidores de esos países.",
            f"    chain {NFT_LISTS_CHAIN} {{",
            "        tcp dport 25 return",
            "    }",
            "",
        ]
        changes.append(f"chain {NFT_LISTS_CHAIN} (con el 25 exento)")
    if new_decl:
        lines[i_input:i_input] = new_decl
    return "\n".join(lines), changes


def move_rules_to_chain(text: str, chain: str) -> str:
    """`add rule inet svqpanel input …` → `… <chain> …` (archivos de reglas o
    de listas IP generados antes de 0.274.0). Idempotente."""
    return re.sub(r"^(\s*add\s+rule\s+inet\s+svqpanel\s+)input\b",
                  rf"\g<1>{chain}", text, flags=re.M)


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


# ─────────────────────────────────────────────────────────────────────────────
# Acceso remoto a MySQL: set de IPs permitidas al 3306 (allowlist)
# ─────────────────────────────────────────────────────────────────────────────
MYSQL_REMOTE_SET = "mysql_remote_allow"
NFT_MYSQL_FILE = "/etc/nftables/svqpanel-mysql-remote.nft"


def ensure_mysql_remote_setup() -> Tuple[bool, str]:
    """Crea (si faltan) el set `mysql_remote_allow` y la regla que abre el 3306
    SOLO a las IPs de ese set. Idempotente. La regla va en la cadena input."""
    if not table_exists():
        return False, "tabla nftables del panel no cargada"
    try:
        # set (no falla si ya existe)
        subprocess.run([NFT_BIN, "add", "set", "inet", "svqpanel", MYSQL_REMOTE_SET,
                        "{ type ipv4_addr; flags interval; }"],
                       capture_output=True, text=True, timeout=5)
        # regla: aceptar 3306 desde IPs del set. Comprobar si ya está.
        chk = subprocess.run([NFT_BIN, "list", "chain", "inet", "svqpanel", "input"],
                             capture_output=True, text=True, timeout=5)
        if MYSQL_REMOTE_SET not in chk.stdout:
            subprocess.run([NFT_BIN, "add", "rule", "inet", "svqpanel", "input",
                            "tcp", "dport", "3306", "ip", "saddr",
                            f"@{MYSQL_REMOTE_SET}", "accept"],
                           capture_output=True, text=True, timeout=5)
        return True, "ok"
    except Exception as e:
        return False, str(e)


def mysql_remote_add_ip(ip: str) -> Tuple[bool, str]:
    """Autoriza una IP a conectar al 3306 (la añade al set y persiste)."""
    ensure_mysql_remote_setup()
    ok, msg = nft_set_add_element(MYSQL_REMOTE_SET, ip)
    if ok:
        persist_mysql_remote()
    return ok, msg


def mysql_remote_remove_ip(ip: str) -> Tuple[bool, str]:
    """Revoca una IP del acceso al 3306."""
    ok, msg = nft_set_delete_element(MYSQL_REMOTE_SET, ip)
    if ok:
        persist_mysql_remote()
    return ok, msg


def mysql_remote_list_ips() -> list:
    """IPs actualmente autorizadas al 3306 (leídas del set)."""
    try:
        r = subprocess.run([NFT_BIN, "list", "set", "inet", "svqpanel", MYSQL_REMOTE_SET],
                           capture_output=True, text=True, timeout=5)
        m = re.search(r"elements\s*=\s*\{(.*?)\}", r.stdout, re.DOTALL)
        if not m:
            return []
        return [tok for tok in re.findall(r"\d+\.\d+\.\d+\.\d+", m.group(1))]
    except Exception:
        return []


def persist_mysql_remote() -> None:
    """Vuelca el set de IPs remotas a un .nft para que sobreviva a reinicios."""
    ips = mysql_remote_list_ips()
    lines = [
        "# /etc/nftables/svqpanel-mysql-remote.nft",
        "# Generado por SVQPanel — IPs autorizadas a MySQL remoto. NO editar a mano.",
        "",
        f"flush set inet svqpanel {MYSQL_REMOTE_SET}",
    ]
    if ips:
        lines.append(f"add element inet svqpanel {MYSQL_REMOTE_SET} {{ {', '.join(ips)} }}")
    lines.append("")
    try:
        os.makedirs(os.path.dirname(NFT_MYSQL_FILE), exist_ok=True)
        tmp = NFT_MYSQL_FILE + ".tmp"
        with open(tmp, "w") as f:
            f.write("\n".join(lines))
        os.replace(tmp, NFT_MYSQL_FILE)
    except Exception:
        pass
