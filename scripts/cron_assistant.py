"""
Asistente de creación de crons para usuarios sin conocimientos técnicos.

Tres piezas, todas sin efectos secundarios (no escriben nada):

- Plantillas: el usuario elige «qué quiere hacer» (un script PHP de su web,
  visitar una URL, el planificador de Laravel, el cron de WordPress…) y el panel
  monta el comando. Usa SIEMPRE el PHP del dominio (/usr/bin/php{ver}), no el del
  sistema: un `/usr/bin/php` a pelo corre con otra versión y el script peta.
- Explorador: lista carpetas y scripts dentro de la carpeta del dominio
  (/home/USUARIO/web/DOMINIO, no solo public_html: los scripts de cron suelen ir
  en private/, fuera de la web) sin salir de ella ni por symlinks.
- Próximas ejecuciones de una expresión cron, en la hora del servidor (la del
  panel y la que usa el daemon de cron).
"""

import os
import re
import shlex
from datetime import datetime, timedelta

from api.schemas.cron_schemas import URL_COMMAND_RE, build_url_command

SCRIPT_EXTS = {".php": "php", ".sh": "shell"}
MAX_ENTRIES = 500
# Argumentos de un script: solo caracteres que no significan nada para el shell.
_SAFE_ARG = re.compile(r"^[A-Za-z0-9_./=:,@+%-]+$")


class AssistantError(ValueError):
    """Error con mensaje para el usuario (se devuelve como 400)."""


def domain_base_dir(owner_username: str, domain_name: str) -> str:
    return f"/home/{owner_username}/web/{domain_name}"


def php_binary(php_version: str | None) -> str:
    v = (php_version or "").strip()
    return f"/usr/bin/php{v}" if re.fullmatch(r"\d+\.\d+", v) else "/usr/bin/php"


def _inside(root: str, path: str) -> bool:
    try:
        return os.path.commonpath([root, path]) == root
    except ValueError:
        return False


def resolve_in_base(base_dir: str, rel: str) -> str:
    """Ruta real de `rel` dentro de base_dir. Error si se sale (.., symlink)."""
    root = os.path.realpath(base_dir)
    rel = (rel or "").replace("\\", "/").lstrip("/")
    target = os.path.realpath(os.path.join(root, rel))
    if not _inside(root, target):
        raise AssistantError("Ruta fuera de la carpeta del dominio")
    return target


# ── Explorador ────────────────────────────────────────────────────────────────
def browse(base_dir: str, rel: str = "") -> dict:
    """Carpetas y scripts (.php/.sh) de una carpeta del dominio."""
    root = os.path.realpath(base_dir)
    target = resolve_in_base(root, rel)
    if not os.path.isdir(target):
        raise AssistantError("Carpeta no encontrada")
    entries = []
    try:
        names = sorted(os.listdir(target), key=str.lower)
    except OSError:
        raise AssistantError("No se puede leer la carpeta")
    for name in names:
        if name.startswith("."):
            continue
        full = os.path.join(target, name)
        real = os.path.realpath(full)
        if not _inside(root, real):
            continue  # symlink que apunta fuera del dominio
        relp = os.path.relpath(full, root).replace("\\", "/")
        if os.path.isdir(real):
            entries.append({"name": name, "path": relp, "type": "dir"})
        elif os.path.splitext(name)[1].lower() in SCRIPT_EXTS:
            entries.append({"name": name, "path": relp, "type": "file"})
        if len(entries) >= MAX_ENTRIES:
            break
    entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
    cur = os.path.relpath(target, root).replace("\\", "/")
    cur = "" if cur == "." else cur
    parent = None if not cur else (os.path.dirname(cur) or "")
    return {"path": cur, "parent": parent, "entries": entries,
            "truncated": len(entries) >= MAX_ENTRIES}


# ── Detección de aplicaciones ─────────────────────────────────────────────────
def detect_apps(base_dir: str, docroot: str, php_version: str | None) -> list[dict]:
    """Apps del dominio con tarea programada conocida, con su comando listo."""
    php = php_binary(php_version)
    root = os.path.realpath(base_dir)
    doc = os.path.realpath(docroot) if docroot else root
    apps = []

    def isfile(p):
        return _inside(root, os.path.realpath(p)) and os.path.isfile(p)

    # Laravel: artisan suele estar un nivel por encima del docroot (…/public).
    for d in (doc, os.path.dirname(doc), os.path.join(root, "public_html"), root):
        art = os.path.join(d, "artisan")
        if isfile(art):
            apps.append({"key": "laravel", "label": "Laravel (planificador)",
                         "desc": "Ejecuta las tareas de app/Console/Kernel (schedule:run). "
                                 "Laravel recomienda lanzarlo cada minuto.",
                         "command": f"{php} {shlex.quote(art)} schedule:run",
                         "suggest": "* * * * *"})
            break
    if isfile(os.path.join(doc, "wp-config.php")) or isfile(os.path.join(doc, "wp-load.php")):
        from scripts.wp_manager import wp_cron_command
        apps.append({"key": "wordpress", "label": "WordPress (wp-cron)",
                     "desc": "Ejecuta las tareas pendientes de WordPress con WP-CLI. "
                             "Mejor aún: «Optimizar wp-cron» en la ficha del dominio, "
                             "que además lo desactiva en las visitas.",
                     "command": wp_cron_command(doc, php_version),
                     "suggest": "*/5 * * * *"})
    if isfile(os.path.join(doc, "occ")) and isfile(os.path.join(doc, "cron.php")):
        apps.append({"key": "nextcloud", "label": "Nextcloud (cron.php)",
                     "desc": "Trabajos en segundo plano de Nextcloud. Recomendado cada 5 minutos.",
                     "command": f"{php} -f {shlex.quote(os.path.join(doc, 'cron.php'))}",
                     "suggest": "*/5 * * * *"})
    moodle = os.path.join(doc, "admin", "cli", "cron.php")
    if isfile(moodle):
        apps.append({"key": "moodle", "label": "Moodle (cron)",
                     "desc": "Cron de Moodle. Recomendado cada minuto.",
                     "command": f"{php} {shlex.quote(moodle)}",
                     "suggest": "* * * * *"})
    return apps


# ── Construcción de comandos ──────────────────────────────────────────────────
def build_script_command(base_dir: str, rel_path: str, php_version: str | None,
                         args: str = "") -> str:
    target = resolve_in_base(base_dir, rel_path)
    if not os.path.isfile(target):
        raise AssistantError("El archivo no existe")
    kind = SCRIPT_EXTS.get(os.path.splitext(target)[1].lower())
    if not kind:
        raise AssistantError("Solo se pueden programar scripts .php o .sh")
    if not re.fullmatch(r"[A-Za-z0-9_./@+-]+", target):
        raise AssistantError("La ruta del script tiene caracteres no permitidos "
                             "(espacios, &, ; …). Renombra el archivo o la carpeta.")
    tokens = (args or "").split()
    for t in tokens:
        if not _SAFE_ARG.match(t):
            raise AssistantError(f"Argumento no permitido: {t}")
    runner = php_binary(php_version) if kind == "php" else "/bin/bash"
    return " ".join([runner, target, *tokens])


def build_url_cmd(url: str) -> str:
    url = (url or "").strip()
    cmd = build_url_command(url)
    if not URL_COMMAND_RE.fullmatch(cmd):
        raise AssistantError("URL no válida: debe empezar por http:// o https:// "
                             "y no llevar espacios ni comillas")
    return cmd


# ── Próximas ejecuciones ──────────────────────────────────────────────────────
_RANGES = {"minute": (0, 59), "hour": (0, 23), "day": (1, 31),
           "month": (1, 12), "weekday": (0, 7)}


def _parse_field(expr: str, lo: int, hi: int) -> set[int]:
    vals = set()
    for part in expr.split(","):
        base, _, step = part.partition("/")
        step_n = int(step) if step else 1
        if step_n < 1:
            raise AssistantError(f"Paso inválido: {part}")
        if base == "*":
            a, b = lo, hi
        elif "-" in base:
            a, b = (int(x) for x in base.split("-", 1))
        else:
            a = int(base)
            b = hi if step else a
        if a < lo or b > hi or a > b:
            raise AssistantError(f"Valor fuera de rango: {part} ({lo}-{hi})")
        vals.update(range(a, b + 1, step_n))
    return vals


def next_runs(minute, hour, day, month, weekday, count: int = 5,
              now: datetime | None = None) -> list[datetime]:
    """Siguientes `count` ejecuciones (hora local del servidor, naive), con la
    semántica de cron: si día del mes Y día de la semana están acotados, basta
    con que coincida UNO de los dos."""
    try:
        mins = _parse_field(minute, *_RANGES["minute"])
        hours = _parse_field(hour, *_RANGES["hour"])
        days = _parse_field(day, *_RANGES["day"])
        months = _parse_field(month, *_RANGES["month"])
        wdays = {0 if w == 7 else w for w in _parse_field(weekday, *_RANGES["weekday"])}
    except ValueError as e:
        raise AssistantError(str(e) or "Expresión inválida")
    dom_any, dow_any = day.startswith("*"), weekday.startswith("*")

    def day_ok(t):
        dom = t.day in days
        dow = ((t.weekday() + 1) % 7) in wdays  # cron: 0 = domingo
        if dom_any or dow_any:
            return dom and dow
        return dom or dow

    t = (now or datetime.now()).replace(second=0, microsecond=0) + timedelta(minutes=1)
    limit = t + timedelta(days=366 * 5)
    out = []
    while len(out) < count and t < limit:
        if t.month not in months:
            t = (t.replace(day=1, hour=0, minute=0) + timedelta(days=32)).replace(day=1)
            continue
        if not day_ok(t):
            t = t.replace(hour=0, minute=0) + timedelta(days=1)
            continue
        if t.hour not in hours:
            t = t.replace(minute=0) + timedelta(hours=1)
            continue
        if t.minute not in mins:
            t += timedelta(minutes=1)
            continue
        out.append(t)
        t += timedelta(minutes=1)
    return out
