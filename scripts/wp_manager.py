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


# Script PHP que se evalúa DENTRO de un único arranque de WordPress (wp eval)
# para sacar de golpe versión, opciones y conteos. Evita lanzar ~10 procesos
# wp-cli en serie (cada uno hace bootstrap completo de WP = ~1s). Las
# actualizaciones (que consultan wordpress.org por red) NO van aquí: son lo más
# lento y se piden aparte solo cuando se necesitan.
_INFO_EVAL = r"""
$d = array(
  'version'        => get_bloginfo('version'),
  'siteurl'        => get_option('siteurl'),
  'home'           => get_option('home'),
  'title'          => get_option('blogname'),
  'locale'         => get_locale(),
  'plugins_total'  => count(get_plugins()),
  'plugins_active' => count((array) get_option('active_plugins', array())),
  'themes_total'   => count(wp_get_themes()),
);
echo json_encode($d);
"""


def wp_info(docroot: str, owner: str, with_updates: bool = False) -> Dict:
    """Resumen del sitio en UNA sola invocación de wp-cli (wp eval).

    with_updates=False por defecto: el conteo de actualizaciones consulta la red
    (lento) y se obtiene aparte vía wp_updates_summary cuando se pida.
    """
    rc, out, err = _wp(docroot, owner, ["eval", _INFO_EVAL])
    if rc != 0 or not out.strip():
        # Fallback: ¿realmente no hay WP o solo falló el eval?
        if not wp_is_installed(docroot, owner):
            raise WpError("No hay un WordPress operativo en este dominio (core no instalado).")
        raise WpError(f"No pude leer la instalación: {err or out}")
    try:
        info = json.loads(out)
    except (ValueError, TypeError):
        raise WpError("Respuesta de WordPress no válida al leer la información.")

    info["app"] = "wordpress"
    info["maintenance"] = os.path.exists(os.path.join(docroot, ".maintenance"))
    info["updates"] = (wp_updates_summary(docroot, owner) if with_updates
                       else {"core": 0, "plugins": 0, "themes": 0, "checked": False})
    return info


def wp_updates_summary(docroot: str, owner: str) -> Dict:
    """Nº de actualizaciones pendientes de core, plugins y temas (consulta red)."""
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
        "checked": True,
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


def wp_delete_item(docroot: str, owner: str, kind: str, name: str) -> Dict:
    """Elimina (borra los ficheros de) un plugin o tema.

    wp-cli desactiva el plugin antes de borrarlo. Un tema no se puede borrar si
    está activo: en ese caso wp-cli devuelve error y lo propagamos legible.
    """
    if kind not in ("plugin", "theme"):
        raise WpError("Tipo no válido (plugin|theme)")
    name = _safe_slug(name, kind)
    rc, out, err = _wp_full(docroot, owner, [kind, "delete", name])
    if rc != 0:
        msg = (err or out).strip()
        if kind == "theme" and "active" in msg.lower():
            raise WpError("No puedes eliminar el tema activo. Activa otro tema primero.")
        raise WpError(f"No pude eliminar el {kind} {name}: {msg}")
    return {"ok": True, "output": out or f"{kind} {name} eliminado."}


# ─────────────────────────────────────────────────────────────────────────────
# WordPress — seguridad / mantenimiento
# ─────────────────────────────────────────────────────────────────────────────
def wp_flush_permalinks(docroot: str, owner: str) -> Dict:
    rc, out, err = _wp_full(docroot, owner, ["rewrite", "flush", "--hard"])
    if rc != 0:
        raise WpError(f"No pude regenerar los permalinks: {err or out}")
    return {"ok": True, "output": out}


def wp_maintenance(docroot: str, owner: str, enable: bool) -> Dict:
    """Activa/desactiva el modo mantenimiento.

    Lo hacemos manipulando directamente el fichero `.maintenance` (lo mismo que
    hace WordPress): es instantáneo y no requiere arrancar wp-cli (que tardaría
    ~1s en bootstrapear WP solo para crear/borrar este fichero).

    IMPORTANTE: WordPress IGNORA el `.maintenance` si `$upgrading` tiene más de
    10 minutos (es un flag de "actualización en curso", no de mantenimiento
    permanente). Como aquí es un mantenimiento MANUAL que debe durar hasta que
    el usuario lo quite, escribimos un timestamp en el futuro lejano para que no
    expire solo. Al desactivar, borramos el fichero.
    """
    flag = os.path.join(docroot, ".maintenance")
    try:
        if enable:
            # time() + ~10 años: nunca caduca hasta que se desactive a mano.
            with open(flag, "w") as f:
                f.write("<?php $upgrading = 9999999999; ?>")
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
# WordPress — optimización del wp-cron
#
# Por defecto WordPress dispara su wp-cron EN CADA VISITA. Con plugins que
# programan tareas frecuentes (WP Rocket preload, Action Scheduler, Jetpack sync…
# cada 1-5 min), eso arranca PHP en cada visita y solapa procesos → picos de CPU
# aunque el tráfico sea bajo. La práctica estándar de hosting es:
#   1) define('DISABLE_WP_CRON', true)  → deja de dispararse por visita.
#   2) un cron de sistema cada 5 min que ejecuta las tareas vencidas.
# Reversible: se quita la constante y el cron.
# ─────────────────────────────────────────────────────────────────────────────
def _wpcron_line(docroot: str) -> str:
    """Línea de crontab que ejecuta las tareas vencidas cada 5 min."""
    return (f"*/5 * * * * {WPCLI_PATH} cron event run --due-now "
            f"--path={docroot} >/dev/null 2>&1")


def wp_cron_status(docroot: str, owner: str) -> Dict:
    """Devuelve si el wp-cron está 'optimizado' (constante + cron de sistema)."""
    # ¿DISABLE_WP_CRON = true en wp-config?
    rc, out, _ = _wp(docroot, owner, ["config", "get", "DISABLE_WP_CRON"])
    disabled = (rc == 0 and out.strip().lower() in ("true", "1"))
    # ¿hay línea de cron de sistema para este docroot?
    rcc, outc, _ = _run(["crontab", "-l", "-u", owner])
    has_cron = (rcc == 0 and "cron event run" in outc and docroot in outc)
    return {"optimized": bool(disabled and has_cron),
            "disable_wp_cron": disabled, "system_cron": has_cron}


def wp_optimize_cron(docroot: str, owner: str, enable: bool = True) -> Dict:
    """Activa (enable=True) o revierte (False) la optimización del wp-cron.

    enable=True:  DISABLE_WP_CRON=true + cron de sistema cada 5 min.
    enable=False: quita la constante y la línea de cron (vuelve al modo por visita).
    Idempotente en ambos sentidos.
    """
    if enable:
        # 1) DISABLE_WP_CRON = true (vía wp-cli; --raw para valor booleano PHP).
        rc, out, err = _wp(docroot, owner,
            ["config", "set", "DISABLE_WP_CRON", "true", "--raw", "--type=constant"])
        if rc != 0:
            raise WpError(f"No pude fijar DISABLE_WP_CRON: {err or out}")
        # 2) Añadir el cron de sistema (preservando el resto del crontab del user).
        line = _wpcron_line(docroot)
        rcc, cur, _ = _run(["crontab", "-l", "-u", owner])
        existing = cur if rcc == 0 else ""
        kept = [l for l in existing.splitlines()
                if not ("cron event run" in l and docroot in l)]
        new_cron = "\n".join(kept + [line]) + "\n"
        rcw, _, errw = _run(["crontab", "-u", owner, "-"], input_text=new_cron)
        if rcw != 0:
            raise WpError(f"No pude instalar el cron de sistema: {errw}")
        return {"ok": True, "optimized": True,
                "message": "wp-cron optimizado: ya no se dispara en cada visita "
                           "(cron de sistema cada 5 min)."}
    else:
        # Revertir: quitar la constante y la línea de cron.
        _wp(docroot, owner, ["config", "delete", "DISABLE_WP_CRON"])
        rcc, cur, _ = _run(["crontab", "-l", "-u", owner])
        if rcc == 0:
            kept = [l for l in cur.splitlines()
                    if not ("cron event run" in l and docroot in l)]
            new_cron = ("\n".join(kept) + "\n") if kept else ""
            _run(["crontab", "-u", owner, "-"], input_text=new_cron)
        return {"ok": True, "optimized": False,
                "message": "wp-cron restaurado al modo por defecto (por visita)."}


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


# ─────────────────────────────────────────────────────────────────────────────
# Consola WP-CLI (estilo Plesk): comando libre, SIEMPRE como el usuario del
# dominio. No añade privilegios (el cliente ya puede ejecutar PHP arbitrario
# en su sitio); las restricciones evitan salirse del dominio o colgar la consola.
# ─────────────────────────────────────────────────────────────────────────────

# Flags globales de wp-cli que permitirían operar FUERA del dominio (otra ruta,
# otro servidor) o cargar código con privilegios de la invocación.
_CLI_BLOCKED_FLAGS = ("--path", "--ssh", "--http", "--require", "--exec", "--prompt")

# Subcomandos interactivos (REPL/cliente mysql): esperarían stdin para siempre.
_CLI_BLOCKED_CMDS = (("shell",), ("db", "cli"))

_CLI_MAX_LEN = 2000        # longitud máx. del comando
_CLI_MAX_OUTPUT = 200_000  # bytes máx. de salida devuelta (por canal)
_CLI_TIMEOUT = 120         # segundos


def validate_cli_command(command: str) -> List[str]:
    """
    Valida el comando de la consola y lo trocea en argumentos (sin el 'wp'
    inicial si el usuario lo escribió). Lanza WpError si no es admisible.
    """
    import shlex

    raw = (command or "").strip()
    if not raw:
        raise WpError("Escribe un comando (p. ej.: plugin list)")
    if len(raw) > _CLI_MAX_LEN:
        raise WpError(f"Comando demasiado largo (máx. {_CLI_MAX_LEN} caracteres)")
    if any(ch in raw for ch in ("\n", "\r", "\0")):
        raise WpError("El comando debe ser una sola línea")
    try:
        args = shlex.split(raw)
    except ValueError as e:
        raise WpError(f"Sintaxis inválida (comillas sin cerrar?): {e}")
    if args and args[0] == "wp":
        args = args[1:]
    if not args:
        raise WpError("Escribe un comando (p. ej.: plugin list)")

    for a in args:
        low = a.lower()
        for flag in _CLI_BLOCKED_FLAGS:
            if low == flag or low.startswith(flag + "="):
                raise WpError(f"El flag {flag} no está permitido en la consola "
                              f"(el panel ya fija la ruta del sitio)")

    positional = tuple(a for a in args if not a.startswith("-"))
    for blocked in _CLI_BLOCKED_CMDS:
        if positional[:len(blocked)] == blocked:
            raise WpError(f"'wp {' '.join(blocked)}' es interactivo y no funciona "
                          f"en la consola web")
    return args


def wp_cli_run(docroot: str, owner: str, command: str) -> Dict:
    """Ejecuta un comando de la consola WP-CLI y devuelve rc/stdout/stderr."""
    args = validate_cli_command(command)
    rc, out, err = _wp_full(docroot, owner, args, timeout=_CLI_TIMEOUT)
    out, err = out or "", err or ""
    truncated = len(out) > _CLI_MAX_OUTPUT or len(err) > _CLI_MAX_OUTPUT
    return {
        "command":   "wp " + " ".join(args),
        "rc":        rc,
        "stdout":    out[:_CLI_MAX_OUTPUT],
        "stderr":    err[:_CLI_MAX_OUTPUT],
        "truncated": truncated,
    }
