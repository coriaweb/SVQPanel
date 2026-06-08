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
import subprocess
import logging

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


def apply_update() -> dict:
    """Aplica la actualización: git pull + deps + build + restart.

    El restart de svqpanel reinicia este propio proceso, así que la respuesta se
    devuelve ANTES del restart si es posible; en la práctica la UI vuelve a
    consultar /system/panel-update tras unos segundos.
    """
    log = []

    def step(name, cmd, **kw):
        rc, out = _run(cmd, **kw)
        log.append(f"$ {' '.join(cmd)}\n{out[-1500:]}")
        return rc

    # 1) git pull (descarta cambios locales de package-lock que ensucian el árbol)
    _run(["git", "checkout", "--", "frontend/package-lock.json"], timeout=30)
    if step("pull", ["git", "pull", "origin", "main"], timeout=120) != 0:
        return {"ok": False, "step": "git pull", "log": "\n".join(log)}

    # 2) dependencias Python (en el venv del panel)
    pip = os.path.join(PANEL_DIR, "venv", "bin", "pip")
    if os.path.exists(pip):
        step("pip", [pip, "install", "-q", "-r", "requirements.txt"], timeout=300)

    # 3) build del frontend (si hay node/npm)
    frontend = os.path.join(PANEL_DIR, "frontend")
    if os.path.isdir(frontend) and os.path.exists(os.path.join(frontend, "package.json")):
        step("build", ["npm", "run", "build"], cwd=frontend, timeout=600)

    # 3b) reinstalar componentes con artefactos FUERA del repo que el git pull no
    #     actualiza solo (p. ej. el launcher del terminal en /usr/local/bin, el
    #     servicio systemd y la jaula chroot). Idempotente y tolerante a fallos.
    try:
        from scripts import terminal_manager
        if terminal_manager.ttyd_installed():
            terminal_manager.install()
            log.append("→ Terminal web reinstalado (launcher + jaula).")
    except Exception as e:
        log.append(f"Aviso: no se pudo reinstalar el terminal web: {e}")

    # 4) reiniciar el servicio (aplica migraciones al arrancar). En background
    #    para poder devolver la respuesta antes de que nos reinicie.
    subprocess.Popen(
        ["bash", "-c", "sleep 1; systemctl restart svqpanel"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    log.append("→ Reiniciando svqpanel…")
    return {"ok": True, "version": local_version(), "log": "\n".join(log)}


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
