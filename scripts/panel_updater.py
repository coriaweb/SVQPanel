"""
SVQPanel — Auto-actualización del propio panel.

Comprueba si hay una versión nueva en el repositorio git y la aplica:
  git fetch/pull  →  pip install -r requirements  →  migraciones (las hace
  main.py al arrancar con ALTER TABLE IF NOT EXISTS)  →  build del frontend  →
  systemctl restart svqpanel.

Dos modos (el admin elige):
  • Manual: el panel avisa de versión nueva y el admin pulsa "Actualizar ahora".
  • Automático: un cron (gestionado por el panel) ejecuta la actualización.

La comprobación compara el VERSION local con el del remoto (origin/main) sin
aplicar nada, así que es barata y segura de llamar desde la UI.
"""
import os
import re
import subprocess
import logging
import time

logger = logging.getLogger(__name__)

# Raíz del repo (dos niveles por encima de scripts/)
PANEL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(PANEL_DIR, "VERSION")
AUTOUPDATE_CRON = "/etc/cron.d/svqpanel-autoupdate"


def _run(cmd, cwd=PANEL_DIR, timeout=300):
    """Ejecuta un comando y devuelve (rc, salida combinada)."""
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, f"Timeout ejecutando: {' '.join(cmd)}"
    except Exception as e:
        return 1, str(e)


def local_version() -> str:
    try:
        with open(VERSION_FILE) as f:
            return f.read().strip()
    except Exception:
        return "0.0.0"


def _remote_version() -> str:
    """Versión del VERSION en origin/main, sin tocar el working tree."""
    # Asegura tener las refs remotas frescas
    _run(["git", "fetch", "--quiet", "origin"], timeout=60)
    rc, out = _run(["git", "show", "origin/main:VERSION"], timeout=30)
    if rc == 0 and out:
        return out.strip()
    return ""


def _vt(v: str):
    """Convierte '1.2.3' en tupla comparable (1,2,3); tolera sufijos."""
    parts = []
    for p in (v or "0").split("."):
        num = ""
        for ch in p:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def check() -> dict:
    """Comprueba si hay actualización disponible (sin aplicar nada)."""
    local = local_version()
    remote = _remote_version()
    update = bool(remote) and _vt(remote) > _vt(local)
    # Resumen de commits pendientes (informativo)
    changelog = []
    if update:
        rc, out = _run(
            ["git", "log", "--oneline", "--no-decorate", "-15",
             "HEAD..origin/main"], timeout=30)
        if rc == 0 and out:
            changelog = out.splitlines()
    return {
        "current": local,
        "latest": remote or local,
        "update_available": update,
        "changelog": changelog,
        "auto_update": autoupdate_enabled(),
    }


UPDATE_SCRIPT = os.path.join(PANEL_DIR, "update.sh")
UPDATE_LOG = "/var/log/svqpanel-update.log"
UPDATE_LOCK = "/var/run/svqpanel-update.lock"   # lo crea/borra update.sh

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_RUN_HEADER = "=== SVQPanel Update"


def _update_running() -> bool:
    """True si hay un update.sh vivo (lock con PID existente)."""
    try:
        with open(UPDATE_LOCK) as f:
            pid = int(f.read().strip() or 0)
    except (FileNotFoundError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def status() -> dict:
    """Progreso de la última ejecución de update.sh, para que la UI la siga.

    Barato (sin git): lee el lock y el final del log. `steps` son solo las
    líneas con fecha de la ejecución en curso/última (sin la salida de npm).
    """
    steps, tail = [], []
    try:
        with open(UPDATE_LOG, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 65536))
            text = f.read().decode("utf-8", "replace")
        lines = [_ANSI_RE.sub("", l).rstrip() for l in text.splitlines()]
        start = max((i for i, l in enumerate(lines) if _RUN_HEADER in l), default=None)
        if start is not None:
            steps = [l for l in lines[start:] if l.startswith("[")]
        # Últimas líneas con fecha aunque no sean de una ejecución completa
        # (p.ej. "Otra instancia ya está corriendo", que sale sin cabecera)
        tail = [l for l in lines if l.startswith("[")][-5:]
    except FileNotFoundError:
        pass
    joined = "\n".join(steps)
    return {
        "running": _update_running(),
        "version": local_version(),
        "started": steps[0][1:20] if steps else None,
        "completed": "=== Update completado" in joined,
        "failed": "✗" in joined,
        "steps": steps[-20:],
        "tail": tail,
    }


def apply_update() -> dict:
    """Aplica la actualización delegando en `update.sh`.

    IMPORTANTE: NO duplicamos aquí la lógica de actualización. `update.sh` es el
    único camino de actualización del panel: hace git pull + aplica los
    `updates/NNNN-*.sh` PENDIENTES (con registro en /etc/svqpanel/applied_updates,
    así cada cambio de sistema —jaulas, launchers, nginx…— se aplica una sola vez)
    + actualiza deps/frontend si cambiaron + reinicia. Es el mismo script que
    corre el cron a las 3am, de modo que el botón de la web y el cron hacen
    EXACTAMENTE lo mismo.

    Como update.sh reinicia svqpanel, NO puede ser hijo nuestro: el servicio usa
    KillMode=control-group y el restart mataba también a update.sh a medias (el
    log se cortaba en "Reiniciando servicio svqpanel..."). Lo lanzamos como
    unidad transitoria con systemd-run, en su propio cgroup, y la UI sigue el
    progreso con status().
    """
    if not os.path.exists(UPDATE_SCRIPT):
        # Fallback defensivo (instalaciones antiguas sin update.sh): pull mínimo.
        _run(["git", "checkout", "--", "frontend/package-lock.json"], timeout=30)
        rc, out = _run(["git", "pull", "origin", "main"], timeout=120)
        subprocess.Popen(["bash", "-c", "sleep 1; systemctl restart svqpanel"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": rc == 0, "version": local_version(),
                "log": out[-2000:], "fallback": True}

    # Lanzar update.sh fuera del cgroup del panel, logueando a su fichero habitual.
    shell_cmd = f"bash {UPDATE_SCRIPT} >> {UPDATE_LOG} 2>&1"
    rc, out = _run(
        ["systemd-run", f"--unit=svqpanel-update-{int(time.time())}",
         "--collect", "--quiet",
         f"--setenv=PATH={os.environ.get('PATH', '/usr/sbin:/usr/bin:/sbin:/bin')}",
         "bash", "-c", shell_cmd], timeout=30)
    if rc != 0:
        # Sin systemd-run (no debería pasar en Debian): lanzamiento clásico.
        logger.warning("systemd-run falló (%s): %s — lanzando como hijo", rc, out)
        subprocess.Popen(["bash", "-c", f"sleep 1; {shell_cmd}"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)

    return {"ok": True, "version": local_version(),
            "log": f"Actualización lanzada vía update.sh "
                   f"(aplica migraciones pendientes y reinicia). "
                   f"Log: {UPDATE_LOG}"}


# ─────────────────────────────────────────────────────────────────────────────
# Auto-actualización por cron
# ─────────────────────────────────────────────────────────────────────────────
def autoupdate_enabled() -> bool:
    return os.path.exists(AUTOUPDATE_CRON)


def set_autoupdate(enabled: bool, hour: int = 4) -> bool:
    """Activa/desactiva el cron de auto-actualización (diario a las `hour`)."""
    if not enabled:
        try:
            os.remove(AUTOUPDATE_CRON)
        except FileNotFoundError:
            pass
        return False
    cli = os.path.join(PANEL_DIR, "venv", "bin", "python")
    if not os.path.exists(cli):
        cli = "python3"
    # cron: minuto hora día mes díasemana → diario a las `hour`:00
    content = (
        "# SVQPanel — auto-actualización diaria. Generado automáticamente.\n"
        f"0 {int(hour) % 24} * * * root cd {PANEL_DIR} && "
        f"{cli} -m scripts.panel_updater --auto >> /var/log/svqpanel-update.log 2>&1\n"
    )
    tmp = AUTOUPDATE_CRON + ".tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.chmod(tmp, 0o644)
    os.replace(tmp, AUTOUPDATE_CRON)
    return True


if __name__ == "__main__":
    import sys
    if "--auto" in sys.argv:
        # Ejecutado por el cron: solo actualiza si hay versión nueva.
        info = check()
        if info["update_available"]:
            logger.info("Auto-update: %s → %s", info["current"], info["latest"])
            apply_update()
        else:
            logger.info("Auto-update: ya en la última versión (%s)", info["current"])
    else:
        import json
        print(json.dumps(check(), indent=2))
