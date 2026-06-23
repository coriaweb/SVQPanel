"""
Gestor de procesos del sistema (solo admin).

Lista los procesos (CPU/RAM/usuario) y permite matarlos, con una PROTECCIÓN de
procesos críticos: no se puede matar el propio panel, la base de datos, el
webserver, sshd, systemd, etc. — para que un admin no tumbe el servidor por
error. Los procesos de clientes (PHP-FPM de un dominio, procesos del usuario)
sí se pueden terminar.
"""

import os
import re
import signal
import subprocess
from typing import List, Dict, Tuple

_SYSTEM_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# Procesos críticos que NUNCA se deben matar desde el panel (por nombre de
# comando, coincidencia por prefijo/substring sobre comm). Proteger el SO, la
# BD, el webserver, el acceso remoto y el propio panel.
_PROTECTED_NAMES = {
    "systemd", "init", "kthreadd", "sshd", "nginx", "apache2",
    "postgres", "mariadbd", "mysqld", "named", "dovecot", "master",  # master = postfix
    "uvicorn", "gunicorn", "python3",   # el panel corre con uvicorn/python
    "fail2ban-server", "crowdsec", "rspamd", "snapd", "cron", "rsyslogd",
    "dbus-daemon", "agetty", "containerd", "dockerd",
}

# PIDs siempre protegidos: 1 (init) y el propio proceso del panel + su árbol.
def _self_pids() -> set:
    pids = {1}
    try:
        pids.add(os.getpid())
        pids.add(os.getppid())
    except Exception:
        pass
    return pids


def _run(cmd: List[str], timeout: int = 15) -> Tuple[int, str, str]:
    env = os.environ.copy()
    env["PATH"] = _SYSTEM_PATH
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    return p.returncode, p.stdout, p.stderr


def is_protected(name: str, pid: int) -> bool:
    """¿Es un proceso crítico que no se debe matar?"""
    if pid in _self_pids():
        return True
    if pid < 300:  # procesos de sistema de PID bajo
        return True
    base = (name or "").strip().lower()
    # Quitar ruta si viniera completa
    base = base.split("/")[-1]
    for prot in _PROTECTED_NAMES:
        if base == prot or base.startswith(prot):
            return True
    return False


def list_processes(limit: int = 200, sort_by: str = "cpu") -> Dict:
    """
    Lista procesos con PID, usuario, %CPU, %MEM, RSS, comando. Ordenado por CPU
    (o 'mem'). Marca cada uno con 'protected' para que la UI deshabilite el matar.
    """
    # ps con formato fijo; --sort para ordenar en el propio ps.
    sort_key = "-%mem" if sort_by == "mem" else "-%cpu"
    rc, out, err = _run([
        "ps", "-eo", "pid,user,pcpu,pmem,rss,comm,args",
        "--sort", sort_key, "--no-headers",
    ])
    if rc != 0:
        return {"processes": [], "count": 0, "error": (err or "").strip()}

    procs = []
    for line in out.splitlines():
        line = line.rstrip()
        if not line:
            continue
        # pid user pcpu pmem rss comm args...
        parts = line.split(None, 6)
        if len(parts) < 7:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        user, pcpu, pmem, rss, comm, args = parts[1], parts[2], parts[3], parts[4], parts[5], parts[6]
        try:
            rss_kb = int(rss)
        except ValueError:
            rss_kb = 0
        procs.append({
            "pid":       pid,
            "user":      user,
            "cpu":       float(pcpu) if _isnum(pcpu) else 0.0,
            "mem":       float(pmem) if _isnum(pmem) else 0.0,
            "rss_mb":    round(rss_kb / 1024, 1),
            "name":      comm,
            "command":   args[:200],
            "protected": is_protected(comm, pid),
        })
        if len(procs) >= limit:
            break
    return {"processes": procs, "count": len(procs)}


def _isnum(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def kill_process(pid: int, force: bool = False) -> Tuple[bool, str]:
    """
    Mata un proceso por PID. SIGTERM por defecto, SIGKILL si force=True.
    Rechaza procesos protegidos (críticos del sistema / el propio panel).
    """
    if pid <= 0:
        return False, "PID no válido"

    # Obtener el nombre del proceso para la comprobación de protección.
    rc, out, err = _run(["ps", "-o", "comm=", "-p", str(pid)])
    name = (out or "").strip()
    if rc != 0 or not name:
        return False, f"El proceso {pid} no existe"

    if is_protected(name, pid):
        return False, (f"'{name}' (PID {pid}) es un proceso crítico protegido y "
                       f"no puede terminarse desde el panel.")

    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        return False, f"El proceso {pid} ya no existe"
    except PermissionError:
        return False, f"Sin permisos para terminar el proceso {pid}"
    except Exception as e:
        return False, f"No se pudo terminar el proceso {pid}: {e}"

    return True, (f"Proceso {pid} ({name}) terminado con "
                  f"{'SIGKILL' if force else 'SIGTERM'}")
