"""
Detalle EN VIVO del sistema para el monitor de recursos (equivalente a lo útil
del volcado de Hestia: free/swap, CPU, particiones de disco, interfaces de red).

Todo se lee de /proc, /sys y comandos estándar (df, ip). Sin dependencias extra.
"""

import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)

_ENV = {**os.environ, "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}


def _run(cmd, timeout=8):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=_ENV)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", str(e)


def _mb(kb: int) -> int:
    return round(kb / 1024)


# ─────────────────────────────────────────────────────────────────────────────
# RAM + Swap (como 'free -m')
# ─────────────────────────────────────────────────────────────────────────────
def memory() -> dict:
    info = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, rest = line.partition(":")
                m = re.search(r"(\d+)", rest)
                if m:
                    info[k.strip()] = int(m.group(1))  # en kB
    except OSError as e:
        return {"available": False, "error": str(e)}

    total = info.get("MemTotal", 0)
    free = info.get("MemFree", 0)
    buffers = info.get("Buffers", 0)
    cached = info.get("Cached", 0) + info.get("SReclaimable", 0)
    shared = info.get("Shmem", 0)
    avail = info.get("MemAvailable", free + buffers + cached)
    used = total - free - buffers - cached
    swap_total = info.get("SwapTotal", 0)
    swap_free = info.get("SwapFree", 0)
    return {
        "available":   True,
        "total_mb":    _mb(total),
        "used_mb":     _mb(used),
        "free_mb":     _mb(free),
        "shared_mb":   _mb(shared),
        "buffcache_mb": _mb(buffers + cached),
        "avail_mb":    _mb(avail),
        "used_pct":    round(used / total * 100, 1) if total else 0,
        "swap_total_mb": _mb(swap_total),
        "swap_used_mb":  _mb(swap_total - swap_free),
        "swap_free_mb":  _mb(swap_free),
        "swap_used_pct": round((swap_total - swap_free) / swap_total * 100, 1) if swap_total else 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CPU (modelo, núcleos, %, load)
# ─────────────────────────────────────────────────────────────────────────────
def cpu() -> dict:
    model = "?"
    cores = 0
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    model = line.split(":", 1)[1].strip()
                    cores += 1
    except OSError:
        pass
    try:
        load1, load5, load15 = os.getloadavg()
    except OSError:
        load1 = load5 = load15 = 0.0
    return {
        "model":  model,
        "cores":  cores or os.cpu_count() or 1,
        "load_1": round(load1, 2),
        "load_5": round(load5, 2),
        "load_15": round(load15, 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Disco (particiones reales, como 'df -h')
# ─────────────────────────────────────────────────────────────────────────────
def disks() -> list:
    rc, so, _ = _run(["df", "-B1", "--output=target,fstype,size,used,avail,pcent",
                      "-x", "tmpfs", "-x", "devtmpfs", "-x", "overlay", "-x", "squashfs"],
                     timeout=8)
    out = []
    if rc != 0:
        return out
    for line in so.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue
        target, fstype, size, used, avail, pcent = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
        # Solo sistemas de ficheros "reales"
        if fstype in ("tmpfs", "devtmpfs", "proc", "sysfs"):
            continue
        try:
            size_i, used_i, avail_i = int(size), int(used), int(avail)
        except ValueError:
            continue
        if size_i == 0:
            continue
        out.append({
            "mount":    target,
            "fstype":   fstype,
            "size_gb":  round(size_i / 1024**3, 1),
            "used_gb":  round(used_i / 1024**3, 1),
            "avail_gb": round(avail_i / 1024**3, 1),
            "used_pct": int(pcent.rstrip("%")) if pcent.rstrip("%").isdigit() else 0,
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Red (interfaces con IP y contadores)
# ─────────────────────────────────────────────────────────────────────────────
def _iface_ips() -> dict:
    """{iface: [ips]} de las interfaces (ip -o addr)."""
    rc, so, _ = _run(["ip", "-o", "-4", "addr", "show"], timeout=6)
    ips = {}
    if rc == 0:
        for line in so.splitlines():
            parts = line.split()
            if len(parts) >= 4:
                iface, addr = parts[1], parts[3].split("/")[0]
                ips.setdefault(iface, []).append(addr)
    return ips


def network() -> list:
    ips = _iface_ips()
    out = []
    try:
        with open("/proc/net/dev") as f:
            for line in f:
                if ":" not in line:
                    continue
                iface, data = line.split(":", 1)
                iface = iface.strip()
                if iface == "lo" or iface.startswith(("veth", "docker", "br-")):
                    continue
                cols = data.split()
                if len(cols) < 9:
                    continue
                out.append({
                    "iface":     iface,
                    "ips":       ips.get(iface, []),
                    "rx_gb":     round(int(cols[0]) / 1024**3, 2),
                    "tx_gb":     round(int(cols[8]) / 1024**3, 2),
                    "rx_errors": int(cols[2]),
                    "tx_errors": int(cols[10]),
                })
    except OSError:
        pass
    return out


def collect() -> dict:
    return {
        "memory":  memory(),
        "cpu":     cpu(),
        "disks":   disks(),
        "network": network(),
    }
