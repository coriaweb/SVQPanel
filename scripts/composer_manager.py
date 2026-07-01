"""
Gestión de Composer por dominio (estilo "WP Toolkit", para dependencias PHP).

Permite a un cliente gestionar las dependencias Composer de SU proyecto
(instalar/quitar/actualizar paquetes como PhpMailer, Guzzle, etc.) sin tocar la
terminal. Se ejecuta SIEMPRE como el usuario del dominio (cada archivo/pool es de
ese usuario; ver svqpanel-php-pool-user), sobre el docroot del dominio.

Aclaración de alcance (dos "composer" distintos):
  - El BINARIO composer (/usr/local/bin/composer) es del sistema; solo el admin
    lo actualiza (composer self-update). AQUÍ NO se expone: eso no es del cliente.
  - Las DEPENDENCIAS del proyecto del cliente (su vendor/) sí: require/remove/
    update/install. `composer update` actualiza las librerías del cliente a
    versiones nuevas, NO el binario composer.

Reutiliza el ejecutor, la ruta de composer y el entorno del instalador (mismo
patrón que wp_manager). No usa shell=True; los argumentos van como listas. El
nombre de paquete se valida como identificador Composer seguro (vendor/name)
antes de pasarlo a composer, para rechazar flags/rutas/metacaracteres.
"""

import json
import os
import re
from typing import Dict, List, Optional, Tuple

# Reutilizamos ejecutor, ruta de composer, entorno del sistema y el instalador.
from scripts.app_installer import _run, COMPOSER_PATH, _SYS_ENV, ensure_composer


class ComposerError(RuntimeError):
    """Error legible de una operación Composer (el endpoint lo da como 4xx)."""


# Nombre de paquete Composer: "vendor/name" opcionalmente con restricción de
# versión (":^6.9", ":1.2.*"). vendor y name: minúsculas, dígitos, - . _
# (https://getcomposer.org/doc/04-schema.md#name). Rechaza espacios, rutas,
# flags (--), y cualquier metacarácter de shell (que igualmente no aplica sin
# shell=True, pero cortamos de raíz).
_PKG_RE = re.compile(
    r"^[a-z0-9]([_.-]?[a-z0-9]+)*/[a-z0-9]([_.-]?[a-z0-9]+)*"
    r"(:[A-Za-z0-9._*^~><=!|\- ]{1,60})?$"
)


def _safe_package(value: str) -> str:
    v = (value or "").strip()
    if not _PKG_RE.match(v):
        raise ComposerError(
            f"Nombre de paquete no válido: {value!r} "
            "(formato esperado: vendor/paquete, p. ej. phpmailer/phpmailer)"
        )
    return v


def _env_for(owner_home: Optional[str]) -> Dict[str, str]:
    """Entorno para composer: no interactivo, sin superusuario y con COMPOSER_HOME
    dentro del home del usuario (cache/config por usuario, aislada)."""
    env = dict(
        _SYS_ENV,
        COMPOSER_NO_INTERACTION="1",
        COMPOSER_ALLOW_SUPERUSER="0",
    )
    if owner_home:
        env["COMPOSER_HOME"] = os.path.join(owner_home, ".composer")
    return env


def _composer(docroot: str, owner: str, args: List[str], timeout: int = 600
              ) -> Tuple[int, str, str]:
    """Ejecuta `composer <args>` en el docroot como el usuario del dominio."""
    env = _env_for(f"/home/{owner}")
    return _run([COMPOSER_PATH] + args, cwd=docroot, as_user=owner,
                timeout=timeout, env=env)


# ─────────────────────────────────────────────────────────────────────────────
# Estado / lectura
# ─────────────────────────────────────────────────────────────────────────────
def composer_status(docroot: str, owner: str) -> Dict:
    """Estado de Composer en el docroot: si hay composer.json/lock/vendor y la
    versión del binario. No falla si no hay proyecto: devuelve has_json=False."""
    json_path = os.path.join(docroot, "composer.json")
    lock_path = os.path.join(docroot, "composer.lock")
    vendor_path = os.path.join(docroot, "vendor")

    has_json = os.path.isfile(json_path)
    has_lock = os.path.isfile(lock_path)
    has_vendor = os.path.isdir(vendor_path)

    require: Dict[str, str] = {}
    if has_json:
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            require = {**(data.get("require") or {}),
                       **(data.get("require-dev") or {})}
        except (OSError, ValueError, TypeError):
            require = {}

    version = ""
    rc, out, _ = _composer(docroot, owner, ["--version", "--no-ansi"], timeout=60)
    if rc == 0 and out:
        m = re.search(r"Composer version\s+(\S+)", out)
        version = m.group(1) if m else out.splitlines()[0][:80]

    return {
        "has_json": has_json,
        "has_lock": has_lock,
        "has_vendor": has_vendor,
        "declared": require,          # {paquete: restricción} del composer.json
        "declared_count": len(require),
        "composer_version": version,
        "docroot": docroot,
    }


def composer_packages(docroot: str, owner: str) -> List[Dict]:
    """Lista los paquetes instalados (vendor/) con su versión, vía
    `composer show --format=json`. Devuelve [] si no hay nada instalado."""
    if not os.path.isfile(os.path.join(docroot, "composer.json")):
        return []
    rc, out, err = _composer(docroot, owner, ["show", "--format=json"], timeout=120)
    if rc != 0 or not out.strip():
        # Sin vendor/ o sin lock: no es un error, aún no hay instalados.
        return []
    try:
        data = json.loads(out)
    except (ValueError, TypeError):
        return []
    installed = data.get("installed") or []
    result = []
    for p in installed:
        result.append({
            "name": p.get("name", ""),
            "version": p.get("version", ""),
            "description": (p.get("description") or "")[:200],
        })
    result.sort(key=lambda x: x["name"])
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Operaciones (escriben en vendor/ del usuario)
# ─────────────────────────────────────────────────────────────────────────────
def _result(rc: int, out: str, err: str, action: str) -> Dict:
    """Estructura común: éxito + salida completa para mostrar en la UI."""
    output = (out + ("\n" + err if err else "")).strip()
    if rc != 0:
        raise ComposerError(output or f"composer {action} falló (código {rc})")
    return {"ok": True, "action": action, "output": output}


def composer_require(docroot: str, owner: str, package: str, dev: bool = False
                     ) -> Dict:
    """`composer require [--dev] <paquete>` — instala un paquete nuevo."""
    if not ensure_composer():
        raise ComposerError("Composer no está disponible en el servidor")
    pkg = _safe_package(package)
    args = ["require"]
    if dev:
        args.append("--dev")
    args += ["--no-interaction", "--prefer-dist", pkg]
    rc, out, err = _composer(docroot, owner, args, timeout=900)
    return _result(rc, out, err, "require")


def composer_remove(docroot: str, owner: str, package: str) -> Dict:
    """`composer remove <paquete>` — quita un paquete."""
    pkg = _safe_package(package)
    rc, out, err = _composer(docroot, owner,
                             ["remove", "--no-interaction", pkg], timeout=900)
    return _result(rc, out, err, "remove")


def composer_update(docroot: str, owner: str, package: Optional[str] = None
                    ) -> Dict:
    """`composer update [<paquete>]` — actualiza las dependencias del proyecto
    (todo o un paquete). NO actualiza el binario composer (eso es self-update)."""
    args = ["update", "--no-interaction", "--prefer-dist"]
    if package:
        args.append(_safe_package(package))
    rc, out, err = _composer(docroot, owner, args, timeout=1200)
    return _result(rc, out, err, "update")


def composer_install(docroot: str, owner: str) -> Dict:
    """`composer install` — instala lo declarado en composer.json/lock."""
    if not os.path.isfile(os.path.join(docroot, "composer.json")):
        raise ComposerError("No hay composer.json en este dominio; usa 'require' "
                            "para añadir el primer paquete.")
    if not ensure_composer():
        raise ComposerError("Composer no está disponible en el servidor")
    rc, out, err = _composer(docroot, owner,
                             ["install", "--no-interaction", "--prefer-dist"],
                             timeout=1200)
    return _result(rc, out, err, "install")
