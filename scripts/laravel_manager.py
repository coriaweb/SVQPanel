"""
Gestión de proyectos Laravel ya instalados (el equivalente al WP Toolkit).

Laravel no tiene backoffice: todo se hace con `php artisan` desde la terminal,
justo lo que un cliente de hosting no sabe (o hace mal). Este módulo ofrece:

  - Diagnóstico: comprobaciones típicas de un Laravel en producción
    (APP_DEBUG, APP_KEY, permisos de storage/, storage:link, PHP del dominio
    frente al que pide composer.json, .env expuesto por no servir /public…),
    cada una con su arreglo de un clic cuando lo hay.
  - Acciones de artisan habituales (optimize, migrate, modo mantenimiento…).
  - Consola artisan libre (igual que la de WP-CLI).
  - Editor del .env con validación (una línea mal escrita tumba la web).
  - Visor de storage/logs.

Reglas de seguridad (las mismas que wp_manager/composer_manager):
  - TODO comando se ejecuta como el USUARIO del dominio y con el PHP del dominio
    (nunca root; nunca el PHP del sistema, ver svqpanel-wpcli-php-sistema).
  - Los ficheros del cliente (.env, logs, composer.json…) se leen y escriben
    también como el usuario: el panel corre como root y un symlink plantado
    (.env -> /etc/shadow) le haría leer/escribir lo que no debe.
  - Sin shell=True; argumentos como lista.

La parte que necesita la BD (crons del planificador, plantilla nginx) vive en
api/routes/laravel.py; aquí solo hay lógica sobre el sistema de ficheros.
"""

import json
import os
import pwd
import re
import secrets
import shlex
from typing import Dict, List, Optional, Tuple

from scripts.app_installer import _run
from scripts.composer_manager import php_bin_for


class LaravelError(RuntimeError):
    """Error legible de una operación Laravel (el endpoint lo da como 4xx)."""


# ─────────────────────────────────────────────────────────────────────────────
# Localizar el proyecto
# ─────────────────────────────────────────────────────────────────────────────
def _inside(path: str, base: str) -> bool:
    return path == base or path.startswith(base.rstrip("/") + "/")


def _is_project(d: str) -> bool:
    return (os.path.isfile(os.path.join(d, "artisan"))
            and os.path.isfile(os.path.join(d, "composer.json")))


def find_root(domain_root: str, docroot: str) -> Optional[str]:
    """Carpeta raíz del proyecto Laravel (la que tiene `artisan`), o None.

    Lo normal es que sea el propio docroot (public_html con la plantilla
    `laravel`, que sirve su /public). Si el docroot personalizado ya apunta al
    /public, la raíz es su carpeta padre. Solo se acepta dentro de public_html/
    o private/ del dominio (lo que cubre el open_basedir del pool PHP)."""
    bases = [os.path.realpath(os.path.join(domain_root, n))
             for n in ("public_html", "private")]
    doc = os.path.realpath(docroot)
    cands = [doc]
    if os.path.basename(doc) == "public":
        cands.append(os.path.dirname(doc))
    for c in cands:
        if any(_inside(c, b) for b in bases) and _is_project(c):
            return c
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Ejecución y ficheros (siempre como el usuario)
# ─────────────────────────────────────────────────────────────────────────────
_MAX_READ = 512 * 1024


def _read(owner: str, path: str, limit: int = _MAX_READ) -> Optional[str]:
    """Lee un fichero del cliente COMO el cliente. None si no existe/no se puede."""
    if not os.path.lexists(path):
        return None
    rc, out, _ = _run(["head", "-c", str(limit), path], as_user=owner, timeout=30)
    return out if rc == 0 else None


def _write(owner: str, path: str, content: str) -> None:
    """Escribe un fichero del cliente COMO el cliente (tee, sin shell)."""
    rc, _, err = _run(["tee", path], as_user=owner, input_text=content, timeout=30)
    if rc != 0:
        raise LaravelError(f"No se pudo escribir {os.path.basename(path)}: {err or rc}")


def artisan(root: str, owner: str, php_version: Optional[str], args: List[str],
            timeout: int = 300) -> Tuple[int, str, str]:
    """`php artisan <args>` en la raíz, como el usuario y con el PHP del dominio.
    Siempre no interactivo y sin colores (la salida va a la web)."""
    php = php_bin_for(php_version) or "/usr/bin/php"
    cmd = [php, os.path.join(root, "artisan")] + list(args) + ["--no-interaction", "--no-ansi"]
    return _run(cmd, cwd=root, as_user=owner, timeout=timeout)


def _out(rc: int, out: str, err: str) -> str:
    return ((out or "") + ("\n" + err if err else "")).strip()


# ─────────────────────────────────────────────────────────────────────────────
# .env
# ─────────────────────────────────────────────────────────────────────────────
_KEY_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_.]*)\s*=(.*)$")


def parse_env(text: str) -> Dict[str, str]:
    """Parser mínimo de .env (suficiente para el diagnóstico)."""
    env: Dict[str, str] = {}
    for line in (text or "").splitlines():
        m = _KEY_RE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val[:1] in ('"', "'"):
            q = val[0]
            end = val.find(q, 1)
            val = val[1:end] if end > 0 else val[1:]
        else:
            val = val.split(" #", 1)[0].strip()
        env[key] = val
    return env


def validate_env(text: str) -> None:
    """Rechaza un .env que phpdotenv no podría leer: una sola línea mal escrita
    y TODA la web da error 500. Admite comentarios, líneas vacías, `export` y
    valores entre comillas dobles de varias líneas (claves privadas)."""
    if "\x00" in text:
        raise LaravelError("El .env no puede contener bytes nulos.")
    if len(text.encode("utf-8")) > 64 * 1024:
        raise LaravelError("El .env es demasiado grande (máx. 64 KB).")
    open_quote = False
    for n, line in enumerate(text.splitlines(), 1):
        if open_quote:
            if '"' in line.replace('\\"', ""):
                open_quote = False
            continue
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = _KEY_RE.match(line)
        if not m:
            raise LaravelError(f"Línea {n} no válida: «{s[:60]}». Debe ser CLAVE=valor.")
        val = m.group(2).strip()
        if val.startswith('"') and val[1:].replace('\\"', "").count('"') == 0:
            open_quote = True      # valor multilínea: sigue hasta la comilla de cierre
        elif val.startswith("'") and val.count("'") < 2:
            raise LaravelError(f"Línea {n}: falta cerrar la comilla simple.")
    if open_quote:
        raise LaravelError("Hay un valor entre comillas dobles que no se cierra.")


def _quote(value: str) -> str:
    if value == "" or re.fullmatch(r"[A-Za-z0-9_.:/@+\-]*", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def set_env_value(text: str, key: str, value: str) -> str:
    """Pone CLAVE=valor en el texto del .env (sustituye o añade al final)."""
    line = f"{key}={_quote(value)}"
    pat = re.compile(rf"^\s*(?:export\s+)?{re.escape(key)}\s*=.*$", re.M)
    if pat.search(text):
        return pat.sub(lambda _m: line, text, count=1)
    return (text.rstrip("\n") + "\n" if text.strip() else "") + line + "\n"


def env_path(root: str) -> str:
    return os.path.join(root, ".env")


def read_env(root: str, owner: str) -> Optional[str]:
    return _read(owner, env_path(root), 64 * 1024)


def config_cached(root: str) -> bool:
    return os.path.isfile(os.path.join(root, "bootstrap", "cache", "config.php"))


def write_env(root: str, owner: str, php_version: Optional[str], text: str) -> Dict:
    """Guarda el .env (validado, con copia .env.svqpanel.bak). Si la config
    estaba cacheada, la vuelve a cachear: si no, el cambio no se aplicaría."""
    if not text.endswith("\n"):
        text += "\n"
    validate_env(text)
    path = env_path(root)
    if os.path.lexists(path):
        _run(["cp", "-p", path, path + ".svqpanel.bak"], as_user=owner, timeout=30)
    _write(owner, path, text)
    out = ""
    if config_cached(root):
        rc, o, e = artisan(root, owner, php_version, ["config:cache"], timeout=120)
        out = _out(rc, o, e)
        if rc != 0:
            raise LaravelError(".env guardado, pero `config:cache` falló (la web "
                               "puede seguir con la config anterior):\n" + out)
    return {"ok": True, "output": out or ".env guardado.",
            "backup": os.path.basename(path) + ".svqpanel.bak"}


def update_env_keys(root: str, owner: str, php_version: Optional[str],
                    values: Dict[str, str]) -> Dict:
    text = read_env(root, owner)
    if text is None:
        raise LaravelError("No hay archivo .env en el proyecto.")
    for k, v in values.items():
        text = set_env_value(text, k, v)
    return write_env(root, owner, php_version, text)


# ─────────────────────────────────────────────────────────────────────────────
# Diagnóstico
# ─────────────────────────────────────────────────────────────────────────────
_VER_RE = re.compile(r"(\d+)\.(\d+)")


def php_min_from_constraint(constraint: str) -> Optional[Tuple[int, int]]:
    """Versión mínima de PHP que admite una restricción de composer
    ("^8.2", ">=8.1", "^7.3|^8.0", "~8.1.0 || ^8.2"…). None si no se entiende."""
    mins = []
    for alt in re.split(r"\|\|?", constraint or ""):
        m = _VER_RE.search(alt)
        if m:
            mins.append((int(m.group(1)), int(m.group(2))))
    return min(mins) if mins else None


def _ver_tuple(v: Optional[str]) -> Optional[Tuple[int, int]]:
    m = _VER_RE.match(str(v or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def _non_writable(root: str, owner: str) -> Optional[str]:
    """Primera ruta de storage/ o bootstrap/cache que el usuario NO puede
    escribir (relativa a la raíz), o None si todo está bien."""
    dirs = [d for d in (os.path.join(root, "storage"), os.path.join(root, "bootstrap", "cache"))
            if os.path.isdir(d)]
    if not dirs:
        return None
    rc, out, _ = _run(["find"] + dirs + ["-maxdepth", "4", "!", "-writable", "-print", "-quit"],
                      as_user=owner, timeout=60)
    line = (out or "").strip().splitlines()
    return os.path.relpath(line[0], root) if line else None


def _uses_scheduler(root: str, owner: str) -> bool:
    """¿El proyecto define tareas programadas? (Kernel.php en Laravel ≤10,
    routes/console.php o bootstrap/app.php con withSchedule en 11+)."""
    for rel in ("app/Console/Kernel.php", "routes/console.php", "bootstrap/app.php"):
        txt = _read(owner, os.path.join(root, rel), 200 * 1024) or ""
        if re.search(r"\$schedule->|Schedule::|withSchedule", txt):
            return True
    return False


def _log_files(root: str) -> List[Dict]:
    d = os.path.join(root, "storage", "logs")
    out = []
    try:
        names = os.listdir(d)
    except OSError:
        return out
    for n in names:
        if not _LOG_NAME_RE.match(n):
            continue
        p = os.path.join(d, n)
        try:
            st = os.lstat(p)
        except OSError:
            continue
        if not os.path.isfile(p) or os.path.islink(p):
            continue
        out.append({"name": n, "size": st.st_size, "mtime": int(st.st_mtime)})
    out.sort(key=lambda f: f["mtime"], reverse=True)
    return out


LOG_WARN_BYTES = 200 * 1024 * 1024


def info(root: str, owner: str, php_version: Optional[str], domain_name: str,
         served_dir: str, ssl_enabled: bool) -> Dict:
    """Resumen + lista de comprobaciones. served_dir = carpeta que sirve la web
    (docroot + subcarpeta de la plantilla)."""
    checks: List[Dict] = []

    def add(id_, level, title, detail, fix=None, fix_label=None):
        checks.append({"id": id_, "level": level, "title": title, "detail": detail,
                       "fix": fix, "fix_label": fix_label})

    # ¿Arranca artisan? (también da la versión)
    rc, out, err = artisan(root, owner, php_version, ["--version"], timeout=60)
    version = ""
    if rc == 0:
        m = re.search(r"Laravel Framework\s+(\S+)", out or "")
        version = m.group(1) if m else (out or "").strip()[:40]
    has_vendor = os.path.isdir(os.path.join(root, "vendor"))

    # composer.json → PHP requerido
    php_req = None
    cj = _read(owner, os.path.join(root, "composer.json"), 256 * 1024)
    try:
        php_req = ((json.loads(cj) if cj else {}).get("require") or {}).get("php")
    except (ValueError, AttributeError):
        php_req = None

    env_text = read_env(root, owner)
    env = parse_env(env_text or "")

    # 1) Exposición: la web debe servir /public, no la raíz del proyecto.
    served = os.path.realpath(served_dir)
    if served == root:
        add("template", "critical", "La web sirve la raíz del proyecto, no /public",
            "Cualquiera podría descargar tu .env (contraseñas de la BD, APP_KEY…), "
            "vendor/ y storage/. Aplica la plantilla Laravel para servir solo /public.",
            "template", "Servir desde /public")
    elif served != os.path.join(root, "public"):
        add("template", "warning", "La web no sirve la carpeta /public del proyecto",
            f"Se sirve {served}. Si no es intencionado, aplica la plantilla Laravel.")

    # 2) Dependencias
    if not has_vendor:
        add("vendor", "critical", "Faltan las dependencias (vendor/)",
            "Sin vendor/ la aplicación no arranca. Se instalan con composer install.",
            "vendor", "composer install")
    elif rc != 0:
        add("artisan", "critical", "artisan no arranca",
            "Error al ejecutar php artisan: " + (_out(rc, out, err)[-600:] or f"código {rc}"))

    # 3) PHP del dominio frente al que pide composer.json
    need = php_min_from_constraint(php_req) if php_req else None
    have = _ver_tuple(php_version)
    if need and have and have < need:
        add("php", "critical", f"PHP {php_version} es demasiado antiguo",
            f"composer.json pide PHP {php_req}. Cambia la versión en la pestaña PHP.")

    # 4) .env
    if env_text is None:
        if os.path.isfile(os.path.join(root, ".env.example")):
            add("env", "critical", "No hay archivo .env",
                "Laravel lee su configuración del .env. Se puede crear a partir de "
                ".env.example (luego revisa la BD y el correo en el editor).",
                "env", "Crear desde .env.example")
        else:
            add("env", "critical", "No hay archivo .env",
                "Créalo en el editor de abajo con al menos APP_KEY, APP_URL y la BD.")
    else:
        if not env.get("APP_KEY"):
            add("app_key", "critical", "APP_KEY vacía",
                "Sin clave las sesiones y el cifrado no funcionan (error 500).",
                "app_key", "Generar clave")
        if env.get("APP_DEBUG", "").lower() in ("true", "1", "(true)"):
            add("app_debug", "critical", "APP_DEBUG está activado",
                "Ante cualquier error, la página muestra el código y las variables "
                "del .env (contraseñas incluidas) a quien la visite.",
                "app_debug", "Desactivar")
        if env.get("APP_ENV", "") != "production":
            add("app_env", "warning", f"APP_ENV={env.get('APP_ENV') or '(vacío)'}",
                "En un sitio público debería ser production (cambia el manejo de "
                "errores y protege comandos destructivos).",
                "app_env", "Poner production")
        want = f"{'https' if ssl_enabled else 'http'}://{domain_name}"
        url = env.get("APP_URL", "").rstrip("/")
        url_host = re.sub(r"^https?://", "", url).split("/")[0].lower()
        if url_host not in (domain_name, "www." + domain_name) or \
                (ssl_enabled and url.startswith("http://")):
            add("app_url", "warning", f"APP_URL no coincide ({url or 'vacía'})",
                f"Los enlaces, correos y archivos subidos usarán una URL equivocada. "
                f"Debería ser {want}.", "app_url", f"Poner {want}")
        q = env.get("QUEUE_CONNECTION", "")
        if q and q not in ("sync", "null"):
            add("queue", "info", f"Colas con QUEUE_CONNECTION={q}",
                "Los trabajos en cola necesitan un proceso que los ejecute; si no, se "
                "quedan pendientes. Actívalo en «Tareas programadas» (cron cada minuto).")

    # 5) Permisos
    if has_vendor or os.path.isdir(os.path.join(root, "storage")):
        bad = _non_writable(root, owner)
        if bad:
            add("permissions", "critical", "storage/ o bootstrap/cache sin permiso de escritura",
                f"Tu usuario no puede escribir en {bad}: logs, caché y sesiones fallan.",
                "permissions", "Reparar permisos")

    # 6) storage:link
    pub_storage = os.path.join(root, "public", "storage")
    if os.path.isdir(os.path.join(root, "storage", "app", "public")) and \
            not os.path.lexists(pub_storage):
        add("storage_link", "info", "Falta el enlace public/storage",
            "Los archivos subidos a storage/app/public no se ven en la web.",
            "storage_link", "Crear enlace")

    # 7) Logs enormes
    logs = _log_files(root)
    big = [f for f in logs if f["size"] >= LOG_WARN_BYTES]
    if big:
        add("log_size", "warning", f"{big[0]['name']} ocupa {big[0]['size'] // (1024 * 1024)} MB",
            "El log crece sin límite y gasta tu cuota de disco. Considera "
            "LOG_STACK=daily en el .env.", "log_size", "Vaciar log")

    order = {"critical": 0, "warning": 1, "info": 2}
    checks.sort(key=lambda c: order.get(c["level"], 9))
    return {
        "root": root,
        "version": version,
        "php": php_bin_for(php_version) or "php (sistema)",
        "php_required": php_req,
        "env": {k: env.get(k, "") for k in ("APP_NAME", "APP_ENV", "APP_DEBUG", "APP_URL",
                                             "DB_CONNECTION", "CACHE_STORE", "CACHE_DRIVER",
                                             "SESSION_DRIVER", "QUEUE_CONNECTION")},
        "has_env": env_text is not None,
        "has_vendor": has_vendor,
        "down": os.path.exists(os.path.join(root, "storage", "framework", "down")),
        "config_cached": config_cached(root),
        "routes_cached": any(n.startswith("routes") and n.endswith(".php") for n in
                             (os.listdir(os.path.join(root, "bootstrap", "cache"))
                              if os.path.isdir(os.path.join(root, "bootstrap", "cache")) else [])),
        "uses_scheduler": _uses_scheduler(root, owner),
        "checks": checks,
        "logs": logs,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Arreglos que no necesitan BD
# ─────────────────────────────────────────────────────────────────────────────
def fix_permissions(root: str, owner: str) -> Dict:
    """Devuelve storage/ y bootstrap/cache al usuario y le da escritura.

    chown como root con -h (--no-dereference): con -R no entra en symlinks y
    cambia el propio enlace, no su destino (un storage/x -> /etc/shadow no
    regala nada). Las carpetas no pueden ser symlinks que salgan del proyecto."""
    try:
        pw = pwd.getpwnam(owner)
    except KeyError:
        raise LaravelError(f"El usuario {owner} no existe en el sistema")
    done = []
    for rel in ("storage", os.path.join("bootstrap", "cache")):
        p = os.path.join(root, rel)
        if not os.path.isdir(p) or os.path.islink(p) or not _inside(os.path.realpath(p), root):
            continue
        rc, _, err = _run(["chown", "-R", "-h", f"{pw.pw_uid}:{pw.pw_gid}", p], timeout=300)
        if rc != 0:
            raise LaravelError(f"chown de {rel} falló: {err}")
        _run(["chmod", "-R", "u+rwX", p], as_user=owner, timeout=300)
        done.append(rel)
    return {"ok": True, "output": "Permisos reparados en: " + (", ".join(done) or "nada")}


def create_env_from_example(root: str, owner: str, php_version: Optional[str]) -> Dict:
    if os.path.lexists(env_path(root)):
        raise LaravelError("Ya existe un .env; edítalo en el editor.")
    rc, _, err = _run(["cp", os.path.join(root, ".env.example"), env_path(root)],
                      as_user=owner, timeout=30)
    if rc != 0:
        raise LaravelError(f"No se pudo copiar .env.example: {err}")
    rc, o, e = artisan(root, owner, php_version, ["key:generate", "--force"], timeout=120)
    return {"ok": True, "output": ".env creado desde .env.example.\n" + _out(rc, o, e)}


# ─────────────────────────────────────────────────────────────────────────────
# Acciones rápidas
# ─────────────────────────────────────────────────────────────────────────────
QUICK_ACTIONS: Dict[str, List[str]] = {
    "optimize":       ["optimize"],
    "optimize-clear": ["optimize:clear"],
    "cache-clear":    ["cache:clear"],
    "migrate":        ["migrate", "--force"],
    "migrate-status": ["migrate:status"],
    "storage-link":   ["storage:link"],
    "up":             ["up"],
    "queue-restart":  ["queue:restart"],
    "key-generate":   ["key:generate", "--force"],   # solo vía arreglo (APP_KEY vacía)
}


def run_action(root: str, owner: str, php_version: Optional[str], action: str,
               base_url: str = "") -> Dict:
    if action == "down":
        # Mantenimiento con «secreto»: visitando {url}/{secreto} el dueño sigue
        # viendo la web (cookie) mientras los demás ven el 503. Laravel ≥ 8.
        secret = secrets.token_urlsafe(12).replace("-", "").replace("_", "")
        rc, o, e = artisan(root, owner, php_version, ["down", f"--secret={secret}"], timeout=120)
        if rc != 0 and "secret" in (o + e).lower():
            secret = None
            rc, o, e = artisan(root, owner, php_version, ["down"], timeout=120)
        if rc != 0:
            raise LaravelError(_out(rc, o, e) or f"artisan down falló ({rc})")
        res = {"ok": True, "action": action, "output": _out(rc, o, e)}
        if secret and base_url:
            res["bypass_url"] = f"{base_url.rstrip('/')}/{secret}"
        return res
    args = QUICK_ACTIONS.get(action)
    if not args:
        raise LaravelError(f"Acción no soportada: {action}")
    timeout = 900 if action == "migrate" else 300
    rc, o, e = artisan(root, owner, php_version, args, timeout=timeout)
    output = _out(rc, o, e)
    if rc != 0:
        raise LaravelError(output or f"artisan {' '.join(args)} falló ({rc})")
    return {"ok": True, "action": action, "output": output or "Hecho."}


# ─────────────────────────────────────────────────────────────────────────────
# Consola artisan
# ─────────────────────────────────────────────────────────────────────────────
# Comandos que no terminan nunca (servidores, workers, REPL) o esperan stdin:
# colgarían la petición y el hilo del panel. Los workers de colas irán aparte.
_BLOCKED = {"tinker", "serve", "queue:work", "queue:listen", "schedule:work",
            "horizon", "octane:start", "octane:reload", "reverb:start", "pail", "db",
            "sail:install", "sail:add", "sail:publish"}
_CLI_MAX_LEN = 2000
_CLI_MAX_OUTPUT = 200_000
_CLI_TIMEOUT = 180


def validate_artisan_command(command: str) -> List[str]:
    raw = (command or "").strip()
    if not raw:
        raise LaravelError("Escribe un comando (p. ej.: route:list)")
    if len(raw) > _CLI_MAX_LEN:
        raise LaravelError(f"Comando demasiado largo (máx. {_CLI_MAX_LEN} caracteres)")
    if any(ch in raw for ch in ("\n", "\r", "\0")):
        raise LaravelError("El comando debe ser una sola línea")
    try:
        args = shlex.split(raw)
    except ValueError as e:
        raise LaravelError(f"Sintaxis inválida (¿comillas sin cerrar?): {e}")
    if args[:1] == ["php"]:
        args = args[1:]
    if args[:1] and args[0] in ("artisan", "./artisan"):
        args = args[1:]
    if not args:
        raise LaravelError("Escribe un comando (p. ej.: route:list)")
    first = next((a for a in args if not a.startswith("-")), "")
    if first.lower() in _BLOCKED:
        raise LaravelError(f"«{first}» se queda ejecutándose o es interactivo y no "
                           "funciona en la consola web (usa la terminal).")
    return args


def artisan_console(root: str, owner: str, php_version: Optional[str], command: str) -> Dict:
    args = validate_artisan_command(command)
    rc, out, err = artisan(root, owner, php_version, args, timeout=_CLI_TIMEOUT)
    out, err = out or "", err or ""
    return {
        "command": "php artisan " + " ".join(shlex.quote(a) for a in args),
        "rc": rc,
        "stdout": out[:_CLI_MAX_OUTPUT],
        "stderr": err[:_CLI_MAX_OUTPUT],
        "truncated": len(out) > _CLI_MAX_OUTPUT or len(err) > _CLI_MAX_OUTPUT,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Logs
# ─────────────────────────────────────────────────────────────────────────────
_LOG_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}\.log$")


def _log_path(root: str, name: str) -> str:
    if not _LOG_NAME_RE.match(name or "") or ".." in name:
        raise LaravelError("Nombre de log no válido")
    return os.path.join(root, "storage", "logs", name)


def read_log(root: str, owner: str, name: str, lines: int = 300) -> Dict:
    path = _log_path(root, name)
    if not os.path.isfile(path):
        raise LaravelError("Ese log no existe")
    lines = max(20, min(int(lines or 300), 3000))
    rc, out, err = _run(["tail", "-n", str(lines), path], as_user=owner, timeout=30)
    if rc != 0:
        raise LaravelError(f"No se pudo leer el log: {err}")
    text = out[-_CLI_MAX_OUTPUT:]
    errors = len(re.findall(r"^\[\d{4}-\d\d-\d\d[^\]]*\]\s+\w+\.(?:ERROR|CRITICAL|ALERT|EMERGENCY):",
                            text, re.M))
    return {"name": name, "lines": lines, "content": text, "errors": errors}


def clear_log(root: str, owner: str, name: str) -> Dict:
    path = _log_path(root, name)
    rc, _, err = _run(["truncate", "-s", "0", path], as_user=owner, timeout=30)
    if rc != 0:
        raise LaravelError(f"No se pudo vaciar el log: {err}")
    return {"ok": True, "output": f"{name} vaciado."}


# ─────────────────────────────────────────────────────────────────────────────
# Crons gestionados (planificador y cola) — el endpoint guarda el CronJob
# ─────────────────────────────────────────────────────────────────────────────
CRON_KINDS = {
    "scheduler": {"label": "laravel-scheduler", "args": "schedule:run"},
    # Sin worker permanente (fase 2): procesa lo pendiente cada minuto y sale.
    "queue":     {"label": "laravel-queue",
                  "args": "queue:work --stop-when-empty --max-time=55 --tries=3"},
}


def cron_comment(kind: str, domain_name: str) -> str:
    return f"{CRON_KINDS[kind]['label']}: {domain_name}"


def cron_command(kind: str, root: str, php_version: Optional[str]) -> str:
    php = php_bin_for(php_version) or (f"/usr/bin/php{php_version}" if _ver_tuple(php_version)
                                       else "/usr/bin/php")
    return f"{php} {shlex.quote(os.path.join(root, 'artisan'))} {CRON_KINDS[kind]['args']}"


def sync_cron_php(domain, db, owner_username: Optional[str] = None) -> int:
    """Al cambiar el PHP del dominio, actualiza el comando de sus crons de
    Laravel (mismo problema que el wp-cron: se quedaban con el PHP viejo y
    fallaban en silencio). Devuelve cuántos cambió. Nunca lanza."""
    changed = 0
    try:
        from api.models.models_cron import CronJob
        from api.models.models_user import User
        from scripts.cron_manager import CronManager
        if not owner_username:
            u = db.query(User).filter(User.id == domain.user_id).first()
            owner_username = u.username if u else None
        if not owner_username:
            return 0
        for kind in CRON_KINDS:
            job = (db.query(CronJob)
                     .filter(CronJob.domain_id == domain.id,
                             CronJob.comment == cron_comment(kind, domain.domain_name))
                     .first())
            if job is None:
                continue
            m = re.search(r"\s('?)(/\S+?)/artisan\1\s", (job.command or "") + " ")
            if not m:
                continue
            nuevo = cron_command(kind, m.group(2), domain.php_version)
            if nuevo == job.command:
                continue
            job.command = nuevo
            db.commit()
            cm = CronManager()
            try:
                cm.remove_cron(owner_username, job.id)
            except Exception:
                pass
            cm.add_cron(username=owner_username, cron_id=job.id, minute=job.minute,
                        hour=job.hour, day=job.day, month=job.month, weekday=job.weekday,
                        command=job.command, comment=job.comment or "")
            changed += 1
    except Exception:
        pass
    return changed
