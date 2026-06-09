"""
Helper de fail2ban — wrapper sobre fail2ban-client.
Devuelve datos estructurados a partir del output de texto.
"""

import re
import subprocess
from typing import List, Dict, Optional, Tuple
from datetime import datetime

F2B_BIN = "/usr/bin/fail2ban-client"


def _run(args: List[str], timeout: int = 8) -> Tuple[int, str, str]:
    """Ejecuta fail2ban-client y devuelve (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            [F2B_BIN] + args, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", "fail2ban-client no encontrado"
    except subprocess.TimeoutExpired:
        return 124, "", "Timeout esperando a fail2ban-client"


def is_running() -> bool:
    rc, _, _ = _run(["ping"], timeout=4)
    return rc == 0


# ─────────────────────────────────────────────────────────────────────────────
# Listar jails
# ─────────────────────────────────────────────────────────────────────────────
def list_jails() -> List[str]:
    """Devuelve los nombres de jails configuradas (todas, enabled o no)."""
    rc, out, _ = _run(["status"])
    if rc != 0:
        return []
    # fail2ban-client status output:
    #   Status
    #   |- Number of jail: 3
    #   `- Jail list: sshd, recidive, dovecot
    m = re.search(r"Jail list:\s*(.+)", out)
    if not m:
        return []
    raw = m.group(1).strip()
    return [j.strip() for j in raw.split(",") if j.strip()]


# ─────────────────────────────────────────────────────────────────────────────
# Status de una jail específica
# ─────────────────────────────────────────────────────────────────────────────
def jail_status(jail: str) -> Optional[Dict]:
    """Devuelve el status detallado de una jail (incluye banned IPs)."""
    rc, out, _ = _run(["status", jail])
    if rc != 0:
        return None

    result = {
        "name":              jail,
        "currently_failed":  0,
        "total_failed":      0,
        "currently_banned":  0,
        "total_banned":      0,
        "banned_ips":        [],
        "file_list":         [],
    }

    patterns = {
        "currently_failed":  r"Currently failed:\s*(\d+)",
        "total_failed":      r"Total failed:\s*(\d+)",
        "currently_banned":  r"Currently banned:\s*(\d+)",
        "total_banned":      r"Total banned:\s*(\d+)",
    }
    for key, pat in patterns.items():
        m = re.search(pat, out)
        if m:
            result[key] = int(m.group(1))

    m_ips = re.search(r"Banned IP list:\s*(.*)", out)
    if m_ips:
        ip_str = m_ips.group(1).strip()
        result["banned_ips"] = [ip for ip in ip_str.split() if ip]

    m_files = re.search(r"File list:\s*(.*)", out)
    if m_files:
        result["file_list"] = [f for f in m_files.group(1).split() if f]

    return result


def all_banned() -> Dict[str, List[str]]:
    """Devuelve {jail: [ips]} de TODAS las jails en UNA sola llamada
    (`fail2ban-client banned`, fail2ban >= 0.11). ~6x más rápido que consultar
    el status de cada jail por separado. Si el comando no existe o falla, cae
    al método por-jail. La salida cruda es una lista de dicts tipo:
        [{'sshd': ['1.2.3.4']}, {'dovecot': []}, ...]
    """
    rc, out, _ = _run(["banned"])
    if rc == 0 and out.strip():
        try:
            import ast
            data = ast.literal_eval(out.strip())  # es repr de Python, no JSON
            result: Dict[str, List[str]] = {}
            for entry in data:
                for jail, ips in entry.items():
                    result[jail] = list(ips)
            return result
        except Exception:
            pass
    # Fallback: método antiguo (status por jail)
    result = {}
    for jail in list_jails():
        st = jail_status(jail) or {}
        result[jail] = st.get("banned_ips", [])
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Ban / Unban
# ─────────────────────────────────────────────────────────────────────────────
def unban(jail: str, ip: str) -> Tuple[bool, str]:
    rc, out, err = _run(["set", jail, "unbanip", ip])
    if rc != 0:
        msg = (err or out).strip()
        if "is not banned" in msg.lower() or "not in" in msg.lower():
            return True, "not_banned"
        return False, msg
    return True, "unbanned"


def unban_all_jails(ip: str) -> Dict[str, str]:
    """Intenta desbanear la IP en todas las jails. Devuelve dict {jail: resultado}."""
    out = {}
    for jail in list_jails():
        ok, msg = unban(jail, ip)
        out[jail] = msg if ok else f"error: {msg}"
    return out


def ban(jail: str, ip: str) -> Tuple[bool, str]:
    rc, out, err = _run(["set", jail, "banip", ip])
    if rc != 0:
        return False, (err or out).strip()
    return True, "banned"


# ─────────────────────────────────────────────────────────────────────────────
# Whitelist permanente (jail.local DEFAULT.ignoreip)
# ─────────────────────────────────────────────────────────────────────────────
def add_to_ignoreip(ip: str) -> Tuple[bool, str]:
    """
    Añade una IP/CIDR a [DEFAULT].ignoreip en jail.local y recarga fail2ban.
    Devuelve (success, message).
    """
    import os
    jail_local = "/etc/fail2ban/jail.local"
    if not os.path.isfile(jail_local):
        return False, "/etc/fail2ban/jail.local no existe"

    with open(jail_local) as f:
        content = f.read()

    # Buscar la línea ignoreip dentro de [DEFAULT]
    pattern = re.compile(r"^(ignoreip\s*=\s*)(.*)$", re.MULTILINE)
    match = pattern.search(content)
    if not match:
        return False, "No se encontró línea 'ignoreip' en jail.local"

    existing = match.group(2).strip().split()
    if ip in existing:
        return True, "already_present"

    new_line = f"{match.group(1)}{match.group(2).rstrip()} {ip}"
    new_content = pattern.sub(new_line, content, count=1)

    tmp = jail_local + ".tmp"
    with open(tmp, "w") as f:
        f.write(new_content)
    os.replace(tmp, jail_local)

    rc, _, err = _run(["reload"])
    if rc != 0:
        return False, err.strip() or "fail2ban reload falló"
    return True, "added"


def get_ignoreip() -> List[str]:
    """Devuelve la lista actual de IPs en [DEFAULT].ignoreip."""
    import os
    jail_local = "/etc/fail2ban/jail.local"
    if not os.path.isfile(jail_local):
        return []
    with open(jail_local) as f:
        content = f.read()
    m = re.search(r"^ignoreip\s*=\s*(.+)$", content, re.MULTILINE)
    if not m:
        return []
    return [x for x in m.group(1).split() if x]


def remove_from_ignoreip(ip: str) -> Tuple[bool, str]:
    """Elimina una IP de [DEFAULT].ignoreip."""
    import os
    jail_local = "/etc/fail2ban/jail.local"
    if not os.path.isfile(jail_local):
        return False, "no jail.local"

    with open(jail_local) as f:
        content = f.read()

    pattern = re.compile(r"^(ignoreip\s*=\s*)(.*)$", re.MULTILINE)
    m = pattern.search(content)
    if not m:
        return False, "no ignoreip"

    parts = m.group(2).split()
    if ip not in parts:
        return True, "absent"
    parts = [p for p in parts if p != ip]
    new_line = f"{m.group(1)}{' '.join(parts)}"
    new_content = pattern.sub(new_line, content, count=1)

    tmp = jail_local + ".tmp"
    with open(tmp, "w") as f:
        f.write(new_content)
    os.replace(tmp, jail_local)

    rc, _, err = _run(["reload"])
    if rc != 0:
        return False, err.strip() or "reload failed"
    return True, "removed"


# ─────────────────────────────────────────────────────────────────────────────
# Habilitar/deshabilitar jail
# ─────────────────────────────────────────────────────────────────────────────
def jail_set_enabled(jail: str, enabled: bool) -> Tuple[bool, str]:
    """
    Cambia 'enabled = true|false' del jail en /etc/fail2ban/jail.local y
    recarga fail2ban.
    """
    import os
    path = "/etc/fail2ban/jail.local"
    if not os.path.isfile(path):
        return False, "no jail.local"

    with open(path) as f:
        content = f.read()

    # Localizar la sección [jail] y dentro de ella la línea enabled
    section_re = re.compile(
        rf"(^\[{re.escape(jail)}\][^\[]*?)(^enabled\s*=\s*)(\S+)",
        re.MULTILINE | re.DOTALL,
    )
    m = section_re.search(content)
    new_val = "true" if enabled else "false"
    if m:
        new_content = section_re.sub(rf"\1\g<2>{new_val}", content, count=1)
    else:
        # No existe la línea enabled — buscamos al menos la sección y la añadimos
        sec_only = re.compile(rf"(^\[{re.escape(jail)}\]\s*\n)", re.MULTILINE)
        m2 = sec_only.search(content)
        if not m2:
            return False, f"sección [{jail}] no encontrada en jail.local"
        new_content = sec_only.sub(rf"\1enabled = {new_val}\n", content, count=1)

    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(new_content)
    os.replace(tmp, path)

    rc, _, err = _run(["reload"])
    if rc != 0:
        return False, err.strip() or "fail2ban reload falló"
    return True, "ok"
