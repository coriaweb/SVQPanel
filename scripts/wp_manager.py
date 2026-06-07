"""
Gestión de instalaciones WordPress existentes (estilo "WP Toolkit").

Detecta si en el docroot de un dominio hay un WordPress instalado y expone
operaciones de mantenimiento vía wp-cli, ejecutadas SIEMPRE como el usuario
del dominio (cada pool/archivo es de ese usuario; ver svqpanel-php-pool-user):

  - Información:     versión WP, versión PHP del sitio, URL, nº plugins/temas,
                    actualizaciones pendientes (core/plugins/temas).
  - Actualizaciones: core, plugins (todos o uno), temas (todos o uno).
  - Plugins/temas:   listar, activar/desactivar, actualizar.
  - Seguridad/mant.: regenerar permalinks, modo mantenimiento on/off,
                    regenerar salts (cierra todas las sesiones), flush cache.
  - Acceso/admin:    listar usuarios admin, resetear contraseña, cambiar la URL
                    del sitio (siteurl/home), enlace de acceso al wp-admin.

Todas las operaciones son best-effort y devuelven estructuras serializables.
No usa shell=True; los argumentos van como listas. El nombre de plugin/tema/
usuario se valida como slug seguro antes de pasarlo a wp-cli.
"""

import json
import os
import re
import secrets
import string
from typing import Dict, List, Optional, Tuple

# Reutilizamos el ejecutor y la ruta de wp-cli del instalador (mismo patrón).
from scripts.app_installer import _run, WPCLI_PATH


class WpError(RuntimeError):
    """Error legible de una operación WordPress (el endpoint lo da como 4xx)."""


# Slug seguro: plugins/temas/usuarios. wp-cli ya escapa, pero validamos para
# rechazar de entrada cualquier cosa con espacios, rutas o metacaracteres.
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def _safe_slug(value: str, kind: str = "elemento") -> str:
    v = (value or "").strip()
    if not _SLUG_RE.match(v):
        raise WpError(f"Nombre de {kind} no válido: {value!r}")
    return v


def _wp(docroot: str, owner: str, args: List[str], timeout: int = 300
        ) -> Tuple[int, str, str]:
    """Ejecuta `wp <args> --path=docroot` como el usuario del dominio."""
    cmd = [WPCLI_PATH] + args + ["--path=" + docroot, "--skip-plugins", "--skip-themes"]
    return _run(cmd, as_user=owner, timeout=timeout)


def _wp_full(docroot: str, owner: str, args: List[str], timeout: int = 600
             ) -> Tuple[int, str, str]:
    """Igual que _wp pero cargando plugins/temas (necesario para update, etc.)."""
    cmd = [WPCLI_PATH] + args + ["--path=" + docroot]
    return _run(cmd, as_user=owner, timeout=timeout)


# ─────────────────────────────────────────────────────────────────────────────
# Detección
# ─────────────────────────────────────────────────────────────────────────────
def detect_app(docroot: str, owner: str) -> Dict:
    """
    Detecta qué aplicación hay instalada en el docroot.

    Devuelve {"app": "wordpress"|"laravel"|"nextcloud"|"prestashop"|"unknown"|
    "empty", "managed": bool, ...}. Solo WordPress es "managed" (tiene panel de
    gestión); el resto solo se reportan como "ocupado" para no instalar encima.
    """
    if not docroot or not os.path.isdir(docroot):
        return {"app": "empty", "managed": False}

    has = lambda *p: os.path.exists(os.path.join(docroot, *p))

    # WordPress: wp-config.php (o wp-load.php + wp-includes/version.php)
    if has("wp-config.php") or (has("wp-load.php") and has("wp-includes", "version.php")):
        return {"app": "wordpress", "managed": True}
    # Laravel: artisan + composer.json
    if has("artisan") and has("composer.json"):
        return {"app": "laravel", "managed": False}
    # Nextcloud: occ, o version.php junto a config/config.php
    if has("occ") or (has("version.php") and has("config", "config.php")):
        return {"app": "nextcloud", "managed": False}
    # PrestaShop: autoload propio, o AppKernel + config
    if has("classes", "PrestaShopAutoload.php") or (has("app", "AppKernel.php") and has("config")):
        return {"app": "prestashop", "managed": False}

    # ¿Hay algo de web (index.php / index.html no placeholder)?
    entries = [e for e in os.listdir(docroot) if not e.startswith(".")]
    if not entries:
        return {"app": "empty", "managed": False}
    return {"app": "unknown", "managed": False}


# ─────────────────────────────────────────────────────────────────────────────
# WordPress — información
# ─────────────────────────────────────────────────────────────────────────────
def wp_is_installed(docroot: str, owner: str) -> bool:
    rc, out, _ = _wp(docroot, owner, ["core", "is-installed"])
    return rc == 0


def wp_info(docroot: str, owner: str) -> Dict:
    """Resumen del sitio: versión, URL, conteos y actualizaciones pendientes."""
    if not wp_is_installed(docroot, owner):
        raise WpError("No hay un WordPress operativo en este dominio (core no instalado).")

    info: Dict = {"app": "wordpress"}

    rc, out, _ = _wp(docroot, owner, ["core", "version"])
    info["version"] = out.strip() if rc == 0 else None

    rc, out, _ = _wp(docroot, owner, ["option", "get", "siteurl"])
    info["siteurl"] = out.strip() if rc == 0 else None
    rc, out, _ = _wp(docroot, owner, ["option", "get", "home"])
    info["home"] = out.strip() if rc == 0 else None

    rc, out, _ = _wp(docroot, owner, ["option", "get", "blogname"])
    info["title"] = out.strip() if rc == 0 else None

    rc, out, _ = _wp(docroot, owner, ["language", "core", "list",
                                      "--status=active", "--field=language"])
    info["locale"] = out.strip().splitlines()[0] if rc == 0 and out.strip() else None

    # Conteos
    info["plugins_total"] = _count(_wp(docroot, owner,
        ["plugin", "list", "--field=name"]))
    info["plugins_active"] = _count(_wp(docroot, owner,
        ["plugin", "list", "--status=active", "--field=name"]))
    info["themes_total"] = _count(_wp(docroot, owner,
        ["theme", "list", "--field=name"]))

    # Actualizaciones pendientes
    info["updates"] = wp_updates_summary(docroot, owner)
    info["maintenance"] = os.path.exists(os.path.join(docroot, ".maintenance"))
    return info


def _count(result: Tuple[int, str, str]) -> int:
    rc, out, _ = result
    if rc != 0 or not out.strip():
        return 0
    return len([l for l in out.splitlines() if l.strip()])


def wp_updates_summary(docroot: str, owner: str) -> Dict:
    """Nº de actualizaciones pendientes de core, plugins y temas."""
    core = 0
    rc, out, _ = _wp(docroot, owner, ["core", "check-update", "--format=json"])
    if rc == 0 and out.strip() and out.strip() != "[]":
        try:
            core = len(json.loads(out))
        except (ValueError, TypeError):
            core = 0
    return {
        "core": core,
        "plugins": _count_updatable(docroot, owner, "plugin"),
        "themes": _count_updatable(docroot, owner, "theme"),
    }


def _count_updatable(docroot: str, owner: str, kind: str) -> int:
    rc, out, _ = _wp(docroot, owner,
                     [kind, "list", "--update=available", "--field=name"])
    if rc != 0 or not out.strip():
        return 0
    return len([l for l in out.splitlines() if l.strip()])


def wp_list(docroot: str, owner: str, kind: str) -> List[Dict]:
    """Lista plugins o temas con estado y disponibilidad de update."""
    if kind not in ("plugin", "theme"):
        raise WpError("Tipo no válido (plugin|theme)")
    fields = "name,status,version,update,update_version,title"
    rc, out, err = _wp(docroot, owner,
                       [kind, "list", "--fields=" + fields, "--format=json"])
    if rc != 0:
        raise WpError(f"No pude listar {kind}s: {err or out}")
    try:
        return json.loads(out) if out.strip() else []
    except (ValueError, TypeError):
        return []


# ─────────────────────────────────────────────────────────────────────────────
# WordPress — actualizaciones
# ─────────────────────────────────────────────────────────────────────────────
def wp_update_core(docroot: str, owner: str) -> Dict:
    rc, out, err = _wp_full(docroot, owner, ["core", "update"])
    if rc != 0:
        raise WpError(f"Error actualizando el core: {err or out}")
    # Tras actualizar el core conviene actualizar la BD.
    _wp_full(docroot, owner, ["core", "update-db"])
    return {"ok": True, "output": out}


def wp_update_items(docroot: str, owner: str, kind: str,
                    name: Optional[str] = None) -> Dict:
    """Actualiza todos los plugins/temas, o solo `name` si se indica."""
    if kind not in ("plugin", "theme"):
        raise WpError("Tipo no válido (plugin|theme)")
    target = ["--all"] if not name else [_safe_slug(name, kind)]
    rc, out, err = _wp_full(docroot, owner, [kind, "update"] + target)
    if rc != 0:
        raise WpError(f"Error actualizando {kind}: {err or out}")
    return {"ok": True, "output": out}


def wp_toggle_item(docroot: str, owner: str, kind: str, name: str,
                   activate: bool) -> Dict:
    """Activa o desactiva un plugin/tema."""
    if kind not in ("plugin", "theme"):
        raise WpError("Tipo no válido (plugin|theme)")
    name = _safe_slug(name, kind)
    action = "activate" if activate else "deactivate"
    rc, out, err = _wp_full(docroot, owner, [kind, action, name])
    if rc != 0:
        raise WpError(f"No pude {action} {kind} {name}: {err or out}")
    return {"ok": True, "output": out}


# ─────────────────────────────────────────────────────────────────────────────
# WordPress — seguridad / mantenimiento
# ─────────────────────────────────────────────────────────────────────────────
def wp_flush_permalinks(docroot: str, owner: str) -> Dict:
    rc, out, err = _wp_full(docroot, owner, ["rewrite", "flush", "--hard"])
    if rc != 0:
        raise WpError(f"No pude regenerar los permalinks: {err or out}")
    return {"ok": True, "output": out}


def wp_maintenance(docroot: str, owner: str, enable: bool) -> Dict:
    """Activa/desactiva el modo mantenimiento (wp-cli maintenance-mode)."""
    rc, out, err = _wp_full(docroot, owner,
                            ["maintenance-mode", "activate" if enable else "deactivate"])
    if rc != 0:
        # Algunas versiones no traen el subcomando: fallback al fichero .maintenance.
        flag = os.path.join(docroot, ".maintenance")
        try:
            if enable:
                with open(flag, "w") as f:
                    f.write("<?php $upgrading = time(); ?>")
                _run(["chown", f"{owner}:{owner}", flag])
            elif os.path.exists(flag):
                os.remove(flag)
        except OSError as e:
            raise WpError(f"No pude cambiar el modo mantenimiento: {e}")
    return {"ok": True, "maintenance": enable}


def wp_regenerate_salts(docroot: str, owner: str) -> Dict:
    """Regenera las claves/salts de wp-config (cierra todas las sesiones)."""
    rc, out, err = _wp(docroot, owner, ["config", "shuffle-salts"])
    if rc != 0:
        raise WpError(f"No pude regenerar las claves: {err or out}")
    return {"ok": True, "output": "Claves regeneradas; se han cerrado todas las sesiones."}


def wp_flush_cache(docroot: str, owner: str) -> Dict:
    rc, out, err = _wp_full(docroot, owner, ["cache", "flush"])
    # cache flush devuelve != 0 si no hay backend de cache persistente; no es error.
    return {"ok": True, "output": out or "Cache vaciada."}


# ─────────────────────────────────────────────────────────────────────────────
# WordPress — acceso / admin
# ─────────────────────────────────────────────────────────────────────────────
def wp_admin_users(docroot: str, owner: str) -> List[Dict]:
    """Lista los usuarios con rol administrator."""
    rc, out, err = _wp(docroot, owner,
        ["user", "list", "--role=administrator",
         "--fields=ID,user_login,user_email,display_name", "--format=json"])
    if rc != 0:
        raise WpError(f"No pude listar administradores: {err or out}")
    try:
        return json.loads(out) if out.strip() else []
    except (ValueError, TypeError):
        return []


def wp_reset_password(docroot: str, owner: str, user_login: str,
                      new_password: Optional[str] = None) -> Dict:
    """Resetea la contraseña de un usuario. Si no se pasa, genera una aleatoria."""
    user_login = _safe_slug(user_login, "usuario")
    if not new_password:
        alphabet = string.ascii_letters + string.digits
        new_password = "".join(secrets.choice(alphabet) for _ in range(18))
    elif len(new_password) < 8:
        raise WpError("La contraseña debe tener al menos 8 caracteres.")
    rc, out, err = _wp(docroot, owner,
        ["user", "update", user_login, "--user_pass=" + new_password])
    if rc != 0:
        raise WpError(f"No pude cambiar la contraseña: {err or out}")
    return {"ok": True, "user_login": user_login, "new_password": new_password}


def wp_set_url(docroot: str, owner: str, new_url: str) -> Dict:
    """Cambia siteurl y home a new_url (debe ser http(s)://...)."""
    new_url = (new_url or "").strip().rstrip("/")
    if not re.match(r"^https?://[A-Za-z0-9.\-]+(:\d+)?(/.*)?$", new_url):
        raise WpError("URL no válida (debe empezar por http:// o https://).")
    for opt in ("siteurl", "home"):
        rc, out, err = _wp(docroot, owner, ["option", "update", opt, new_url])
        if rc != 0:
            raise WpError(f"No pude actualizar {opt}: {err or out}")
    return {"ok": True, "siteurl": new_url}


def wp_login_link(docroot: str, owner: str, user_login: str) -> Dict:
    """Genera un enlace de acceso temporal al wp-admin (requiere wp-cli login).

    El paquete `wp login` no viene de serie; si no está, devolvemos solo la URL
    del wp-admin para entrar manualmente.
    """
    user_login = _safe_slug(user_login, "usuario")
    rc, out, err = _wp_full(docroot, owner,
        ["login", "create", user_login, "--url-only"])
    if rc == 0 and out.strip().startswith("http"):
        return {"ok": True, "magic_link": out.strip()}
    # Fallback: solo la URL del admin.
    rc, home, _ = _wp(docroot, owner, ["option", "get", "siteurl"])
    base = home.strip() if rc == 0 else ""
    return {"ok": True, "admin_url": (base.rstrip("/") + "/wp-admin") if base else None,
            "note": "El acceso mágico no está disponible; usa el wp-admin con tu usuario."}
