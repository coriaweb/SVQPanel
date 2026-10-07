"""
SVQPanel — apt en segundo plano para Sistema → Actualizaciones.

Antes el endpoint ejecutaba apt-get DENTRO de la petición con timeout=300. Con
muchos paquetes (64 en producción: PHP 8.2/8.4/8.5 + PostgreSQL) se pasaba de
los 5 minutos, el panel mataba apt a mitad y dejaba dpkg a medias ("unpacked
but not configured"). Además, la actualización reinicia PostgreSQL (la BD del
propio panel) y la petición acababa en "Error interno del servidor".

Ahora apt corre como unidad transitoria de systemd (systemd-run), fuera del
cgroup del panel y sin límite de tiempo: sobrevive a reinicios del panel y de
PostgreSQL. La UI arranca el trabajo y consulta status() hasta que termina.

Un solo trabajo a la vez (apt tampoco admite dos). Estado en JOB_DIR:
  meta.json  → {kind, package, unit, started}
  output.log → salida combinada de apt/dpkg
  rc         → código de salida (existe solo cuando ha terminado)
"""
import json
import os
import shlex
import shutil
import subprocess
import time
import logging

logger = logging.getLogger(__name__)

JOB_DIR = "/var/lib/svqpanel/apt-job"
META = os.path.join(JOB_DIR, "meta.json")
LOG = os.path.join(JOB_DIR, "output.log")
RC = os.path.join(JOB_DIR, "rc")

_DPKG_OPTS = ["-o", "Dpkg::Options::=--force-confdef",
              "-o", "Dpkg::Options::=--force-confold"]


def _build_cmd(kind: str, package: str | None) -> list:
    apt = shutil.which("apt-get") or "/usr/bin/apt-get"
    dpkg = shutil.which("dpkg") or "/usr/bin/dpkg"
    if kind == "repair":
        return [dpkg, "--force-confdef", "--force-confold", "--configure", "-a"]
    if package:
        # --no-remove: si actualizar este paquete obliga a DESINSTALAR otros, apt
        # aborta (actualizar mysql-common desde un repo viejo quería quitar
        # mariadb-server entero). Sin --allow-downgrades tampoco baja versiones.
        return [apt, "install", "--only-upgrade", "--no-remove", "-y",
                *_DPKG_OPTS, package]
    # `upgrade` (no full-upgrade) nunca desinstala paquetes.
    return [apt, "upgrade", "-y", *_DPKG_OPTS]


def _read_meta() -> dict:
    try:
        with open(META) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _unit_active(unit: str) -> bool:
    if not unit:
        return False
    try:
        r = subprocess.run(["systemctl", "is-active", unit],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() in ("active", "activating", "reloading")
    except Exception:  # noqa: BLE001
        return False


def is_running() -> bool:
    meta = _read_meta()
    if not meta or os.path.exists(RC):
        return False
    if meta.get("unit"):
        return _unit_active(meta["unit"])
    # Fallback sin systemd-run: PID del hijo
    pid = int(meta.get("pid") or 0)
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def start(kind: str = "upgrade", package: str | None = None) -> dict:
    """Lanza el trabajo. Devuelve {started, error?, job}."""
    if is_running():
        return {"started": False, "error": "Ya hay una actualización en curso.",
                "job": _read_meta()}
    os.makedirs(JOB_DIR, exist_ok=True)
    for p in (LOG, RC):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass

    cmd = _build_cmd(kind, package)
    shell = (f"{' '.join(shlex.quote(c) for c in cmd)} </dev/null "
             f">{shlex.quote(LOG)} 2>&1; echo $? >{shlex.quote(RC)}")
    unit = f"svqpanel-apt-{int(time.time())}"
    meta = {"kind": kind, "package": package or None, "unit": unit,
            "started": time.strftime("%Y-%m-%d %H:%M:%S"), "cmd": cmd}

    rc = 1
    try:
        r = subprocess.run(
            ["systemd-run", f"--unit={unit}", "--collect", "--quiet",
             "--setenv=DEBIAN_FRONTEND=noninteractive",
             f"--setenv=PATH={os.environ.get('PATH', '/usr/sbin:/usr/bin:/sbin:/bin')}",
             "bash", "-c", shell], capture_output=True, text=True, timeout=30)
        rc = r.returncode
        if rc != 0:
            logger.warning("apt_runner: systemd-run falló (%s): %s", rc, r.stderr.strip())
    except Exception as e:  # noqa: BLE001
        logger.warning("apt_runner: systemd-run no disponible: %s", e)
    if rc != 0:
        env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
        p = subprocess.Popen(["bash", "-c", shell], env=env,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        meta["unit"] = None
        meta["pid"] = p.pid

    with open(META, "w") as f:
        json.dump(meta, f)
    return {"started": True, "job": meta}


def status(tail_bytes: int = 6000) -> dict:
    """Estado del último trabajo + final de su salida + diagnóstico al terminar."""
    meta = _read_meta()
    if not meta:
        return {"exists": False, "running": False}
    running = is_running()
    out = ""
    try:
        with open(LOG, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - tail_bytes))
            out = f.read().decode("utf-8", "replace")
    except FileNotFoundError:
        pass
    rc = None
    try:
        with open(RC) as f:
            rc = int(f.read().strip() or 1)
    except (FileNotFoundError, ValueError):
        pass
    # Terminó sin dejar rc (la unidad murió): se trata como fallo
    finished = not running
    if finished and rc is None:
        rc = 1
    return {
        "exists": True,
        "running": running,
        "kind": meta.get("kind"),
        "package": meta.get("package"),
        "started": meta.get("started"),
        "returncode": rc,
        "success": finished and rc == 0,
        "output": out,
        "dpkg_interrupted": "dpkg was interrupted" in out or "dpkg --configure -a" in out,
        "blocked_removal": "remove is disabled" in out,
        "blocked_downgrade": "without --allow-downgrades" in out,
    }
