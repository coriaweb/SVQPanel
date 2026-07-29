"""
SVQPanel — Registro de componentes gestionados por el panel.

EL PROBLEMA QUE RESUELVE: no todo lo que corre en el servidor viene de apt.
Algunas piezas las instalamos nosotros a mano (tarball de GitHub, binario
suelto), y por tanto NADIE las actualiza: ni `apt upgrade`, ni
unattended-upgrades, ni el update.sh del panel (que solo trae código nuevo del
repo). Se quedan clavadas en la versión del día de la instalación, acumulando
CVEs en silencio y sin aparecer en ninguna pantalla.

Caso real: Roundcube. Instalado desde GitHub en /var/www/roundcube, invisible
para apt, sin ninguna forma de actualizarlo desde el panel — mientras 1.7.2
arreglaba un XSS *zero-click* (CVE-2026-54433) que se dispara solo con abrir un
correo.

DÓNDE ESTÁ LA FRONTERA (importante para que esto siga siendo mantenible):

  • Van AQUÍ los componentes que instalamos fuera de apt y de los que somos los
    únicos responsables: Roundcube, ttyd. Poco más.

  • NO van aquí nginx, MariaDB, PHP, Postfix, Dovecot… Esos vienen de apt/Sury
    y YA se actualizan por Sistema → Actualizaciones (apt) y por
    unattended-upgrades. Reimplementar su actualización sería rehacer apt
    (dependencias, configtest, reinicio ordenado, rollback) y es justo donde un
    fallo tumbaría sitios de clientes. Para esos, la vista de Versiones da
    visibilidad; el actualizador se queda fuera.

Añadir un componente nuevo = añadir una entrada a COMPONENTS con cuatro
funciones (check / upgrade). Toda la UI, el badge y el log ya están escritos.
"""

import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Adaptadores por componente
# ─────────────────────────────────────────────────────────────────────────────
def _roundcube_check() -> dict:
    from scripts import roundcube_updater
    return roundcube_updater.check()


def _roundcube_upgrade() -> dict:
    from scripts import roundcube_updater
    return roundcube_updater.update()


def _ttyd_check() -> dict:
    """ttyd: binario suelto en /usr/local/bin, versión fijada en el código.

    La versión instalada la da el propio binario; la "última" es la que el
    panel tiene fijada en terminal_manager.TTYD_VERSION (subirla es un cambio
    de código, no una descarga automática de la última de GitHub: preferimos
    una versión probada por nosotros a la que haya salido esta mañana).
    """
    import subprocess
    from scripts import terminal_manager

    if not terminal_manager.ttyd_installed():
        return {"installed": False, "current": "", "latest": "",
                "update_available": False}
    current = ""
    try:
        r = subprocess.run([terminal_manager.TTYD_BIN, "--version"],
                           capture_output=True, text=True, timeout=10)
        out = (r.stdout + r.stderr).strip()
        import re
        m = re.search(r"(\d+\.\d+\.\d+)", out)
        if m:
            current = m.group(1)
    except Exception as e:  # noqa: BLE001
        logger.debug("No se pudo leer la versión de ttyd: %s", e)

    latest = terminal_manager.TTYD_VERSION
    return {
        "installed": True,
        "current": current,
        "latest": latest,
        "update_available": bool(current and latest
                                 and _vt(latest) > _vt(current)),
    }


def _ttyd_upgrade() -> dict:
    """Actualiza ttyd al binario de la versión fijada por el panel.

    OJO: terminal_manager.install() solo descarga `if not ttyd_installed()`,
    así que por sí solo NO actualizaría nada si el binario ya está. Apartamos
    el binario viejo para forzar la descarga, y lo restauramos si falla (así no
    dejamos la terminal web rota por un fallo de red).
    """
    import os
    import shutil

    from scripts import terminal_manager

    before = _ttyd_check().get("current", "")
    binp = terminal_manager.TTYD_BIN
    stash = binp + ".old"
    moved = False
    try:
        if os.path.exists(binp):
            shutil.move(binp, stash)
            moved = True
        terminal_manager.install()
        st = _ttyd_check()
        if not st.get("installed"):
            raise RuntimeError("ttyd no quedó instalado tras la descarga")
        if moved:
            os.remove(stash)
        return {"ok": True, "current": st.get("current", ""),
                "log": [f"ttyd actualizado {before or '?'} → "
                        f"{st.get('current') or '?'}"]}
    except Exception as e:  # noqa: BLE001
        if moved and not os.path.exists(binp):
            try:
                shutil.move(stash, binp)
                terminal_manager.install()  # rearranca el servicio con el viejo
            except Exception:  # noqa: BLE001
                logger.exception("No se pudo restaurar el ttyd anterior")
        return {"ok": False,
                "log": [f"Error actualizando ttyd: {e}",
                        "Se restauró el binario anterior."]}


def _vt(v: str):
    """'1.7.10' → (1,7,10) para comparar. Tolera sufijos."""
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


# ─────────────────────────────────────────────────────────────────────────────
# Registro
# ─────────────────────────────────────────────────────────────────────────────
COMPONENTS = [
    {
        "key": "roundcube",
        "name": "Roundcube (webmail)",
        "docs": "https://roundcube.net/news/",
        "description": "Webmail de los clientes. Se instala desde GitHub, "
                       "fuera de apt: solo se actualiza desde aquí.",
        "check": _roundcube_check,
        "upgrade": _roundcube_upgrade,
    },
    {
        "key": "ttyd",
        "name": "ttyd (terminal web)",
        "docs": "https://github.com/tsl0922/ttyd/releases",
        "description": "Servidor de la terminal web del panel. Binario "
                       "instalado a mano, fuera de apt.",
        "check": _ttyd_check,
        "upgrade": _ttyd_upgrade,
    },
]


def _by_key(key: str):
    for c in COMPONENTS:
        if c["key"] == key:
            return c
    return None


def check_all() -> dict:
    """Estado de todos los componentes gestionados (sin tocar nada).

    Un componente que falle al comprobarse no rompe la lista: se devuelve con
    su error para que la UI lo muestre.
    """
    items = []
    for c in COMPONENTS:
        try:
            st = c["check"]()
        except Exception as e:  # noqa: BLE001
            logger.warning("Fallo comprobando %s: %s", c["key"], e)
            st = {"installed": False, "current": "", "latest": "",
                  "update_available": False, "error": str(e)}
        items.append({
            "key": c["key"],
            "name": c["name"],
            "docs": c["docs"],
            "description": c["description"],
            **st,
        })
    return {
        "components": items,
        "updates_available": sum(1 for i in items if i.get("update_available")),
    }


def upgrade(key: str) -> dict:
    """Actualiza un componente concreto. Devuelve {ok, log, ...}."""
    comp = _by_key(key)
    if not comp:
        return {"ok": False, "log": [f"Componente desconocido: {key}"]}
    try:
        res = comp["upgrade"]()
    except Exception as e:  # noqa: BLE001
        logger.exception("Error actualizando %s", key)
        return {"ok": False, "log": [f"Error actualizando {comp['name']}: {e}"]}
    res.setdefault("ok", False)
    res.setdefault("log", [])
    res["key"] = key
    res["name"] = comp["name"]
    return res


if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) > 1 and sys.argv[1] == "upgrade" and len(sys.argv) > 2:
        r = upgrade(sys.argv[2])
        for line in r.get("log", []):
            print(line)
        sys.exit(0 if r.get("ok") else 1)
    print(json.dumps(check_all(), indent=2))
