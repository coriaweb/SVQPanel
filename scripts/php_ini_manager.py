"""
Gestión de php.ini por dominio (Fase 14.3)

Estrategia: cada dominio con overrides tiene un pool PHP-FPM dedicado en
/etc/php/{ver}/fpm/pool.d/svqpanel-{domain}.conf escuchando en un socket
propio /run/php/svqpanel-{domain}.sock. La vhost nginx apunta a ese socket.

Validación: el valor pedido por el cliente NUNCA puede superar el del
php.ini global del servidor (política "el servidor manda"). Se valida en
el panel antes de escribir el pool.
"""

import logging
import os
import re
import subprocess
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_SYS_ENV = {
    **os.environ,
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
}

# Lista curada de directivas que el cliente puede tocar.
#   type:  size | int | bool | tz
#   admin: True → php_admin_value (cap duro, no overridable por ini_set)
#          False → php_value (el cliente puede subir/bajar en runtime)
#   cap:   True → se valida que no supere el límite del servidor
PHP_INI_DIRECTIVES: Dict[str, dict] = {
    "memory_limit":         {"type": "size", "admin": True,  "cap": True,  "label": "Memoria máxima"},
    "upload_max_filesize":  {"type": "size", "admin": True,  "cap": True,  "label": "Tamaño máx. subida"},
    "post_max_size":        {"type": "size", "admin": True,  "cap": True,  "label": "Tamaño máx. POST"},
    "max_execution_time":   {"type": "int",  "admin": True,  "cap": True,  "label": "Tiempo ejecución (s)"},
    "max_input_time":       {"type": "int",  "admin": True,  "cap": True,  "label": "Tiempo input (s)"},
    "max_input_vars":       {"type": "int",  "admin": True,  "cap": True,  "label": "Máx. variables input"},
    "date.timezone":        {"type": "tz",   "admin": False, "cap": False, "label": "Zona horaria"},
    "display_errors":       {"type": "bool", "admin": False, "cap": False, "label": "Mostrar errores"},
    "opcache.enable":       {"type": "bool", "admin": True,  "cap": False, "label": "OPcache activo"},
}

POOL_DIR_TMPL = "/etc/php/{ver}/fpm/pool.d/svqpanel-{domain}.conf"
PHP_INI_TMPL  = "/etc/php/{ver}/fpm/php.ini"
# Fuente única de verdad de las versiones PHP soportadas (evita listas duplicadas
# que se desincronizan: p.ej. al añadir 7.3, has_pool no la encontraba aquí y la
# auditoría daba un falso "sin pool"). Fallback por si el import fallara.
try:
    from scripts.php_manager import ALL_VERSIONS as PHP_VERSIONS
except Exception:
    PHP_VERSIONS = ["7.3", "7.4", "8.0", "8.1", "8.2", "8.3", "8.4", "8.5"]

# ─────────────────────────────────────────────────────────────────────────────
# Tuning de recursos del pool PHP-FPM por dominio (Fase 21).
#
# Estos parámetros controlan cuántos procesos FPM se levantan y, por tanto, el
# consumo de RAM/CPU de la cuenta. Antes estaban hardcodeados (ondemand, 10
# hijos); ahora son editables por dominio con presets + valores manuales.
#
# Política: el cliente NUNCA puede superar el cap del servidor (FPM_MAX_*), para
# que un dominio no pueda agotar la RAM del host.
# ─────────────────────────────────────────────────────────────────────────────

# Caps duros del servidor (un dominio no puede pedir más que esto).
FPM_MAX_CHILDREN_CAP = 50      # máx. procesos FPM por dominio
FPM_MAX_REQUESTS_CAP = 5000    # máx. peticiones antes de reciclar un hijo

# Presets de consumo. El usuario elige uno y, opcionalmente, ajusta a mano.
#   - low:    sitios pequeños/idle (blogs, landings). Mínima RAM.
#   - medium: por defecto. Equilibrio para la mayoría de WordPress/tiendas.
#   - high:   sitios con tráfico sostenido. Procesos siempre vivos (dynamic).
FPM_PRESETS: Dict[str, dict] = {
    "low": {
        "label": "Bajo consumo",
        "description": "Sitios pequeños o con poco tráfico. Procesos bajo demanda, mínima RAM.",
        "pm": "ondemand",
        "pm.max_children": 5,
        "pm.process_idle_timeout": "10s",
        "pm.max_requests": 500,
    },
    "medium": {
        "label": "Equilibrado",
        "description": "Recomendado para la mayoría (WordPress, tiendas medianas).",
        "pm": "ondemand",
        "pm.max_children": 10,
        "pm.process_idle_timeout": "10s",
        "pm.max_requests": 500,
    },
    "high": {
        "label": "Alto tráfico",
        "description": "Tráfico sostenido. Procesos siempre listos (dynamic), responde más rápido pero consume más RAM en reposo.",
        "pm": "dynamic",
        "pm.max_children": 25,
        "pm.start_servers": 4,
        "pm.min_spare_servers": 2,
        "pm.max_spare_servers": 8,
        "pm.max_requests": 1000,
    },
}

# Valores por defecto cuando un dominio no tiene tuning propio (= preset medium).
FPM_DEFAULT_PRESET = "medium"

# ─────────────────────────────────────────────────────────────────────────────
# Seguridad: hardening PHP aplicado SIEMPRE a cada pool de dominio.
# Lista de disable_functions tomada de Hestia. Dos bloques:
#   - pcntl_*: no aplican en FPM, deshabilitarlas es gratis y cero falsos positivos.
#   - exec/system/...: las que usan las webshells. Se quitan al "relajar" un dominio.
# ─────────────────────────────────────────────────────────────────────────────
_PCNTL_FUNCS = (
    "pcntl_alarm,pcntl_fork,pcntl_waitpid,pcntl_wait,pcntl_wifexited,"
    "pcntl_wifstopped,pcntl_wifsignaled,pcntl_wifcontinued,pcntl_wexitstatus,"
    "pcntl_wtermsig,pcntl_wstopsig,pcntl_signal,pcntl_signal_get_handler,"
    "pcntl_signal_dispatch,pcntl_get_last_error,pcntl_strerror,pcntl_sigprocmask,"
    "pcntl_sigwaitinfo,pcntl_sigtimedwait,pcntl_exec,pcntl_getpriority,"
    "pcntl_setpriority,pcntl_async_signals"
)
_EXEC_FUNCS = "exec,system,passthru,shell_exec,proc_open,popen"

DISABLE_FUNCTIONS_FULL    = f"{_PCNTL_FUNCS},{_EXEC_FUNCS}"
DISABLE_FUNCTIONS_RELAXED = _PCNTL_FUNCS   # mantiene pcntl bloqueado, permite exec/system


def domain_tmp_dir(owner: str, domain: str) -> str:
    """Directorio tmp aislado por dominio (sesiones + uploads)."""
    from scripts.utils import get_domain_root
    return f"{get_domain_root(owner, domain)}/tmp"


def _security_block(owner: str, domain: str, relax_hardening: bool = False) -> List[str]:
    """
    Líneas php_admin_value de seguridad que se inyectan SIEMPRE en el pool.
    El cliente no puede sobrescribirlas (php_admin_value = cap duro).
    """
    from scripts.utils import get_public_html, get_domain_private
    public_html = get_public_html(owner, domain)
    private     = get_domain_private(owner, domain)
    tmp         = domain_tmp_dir(owner, domain)
    # open_basedir SIN /tmp global: cada dominio confinado a su raíz + su tmp
    # propio (/home/{owner}/web/{domain}/tmp). Así un sitio no puede leer los
    # temporales de otro a través de /tmp compartido.
    open_basedir = f"{public_html}:{private}:{tmp}"
    disable_fns = DISABLE_FUNCTIONS_RELAXED if relax_hardening else DISABLE_FUNCTIONS_FULL
    return [
        f"php_admin_value[open_basedir] = {open_basedir}",
        f"php_admin_value[disable_functions] = {disable_fns}",
        f"php_admin_value[upload_tmp_dir] = {tmp}",
        f"php_admin_value[session.save_path] = {tmp}",
        # sys_temp_dir: temporales de PHP (tempnam, tmpfile, ImageMagick…)
        # caen en el tmp aislado del dominio, no en /tmp compartido.
        f"php_admin_value[sys_temp_dir] = {tmp}",
    ]


def ensure_domain_tmp(owner: str, domain: str) -> None:
    """
    Crea {domain_root}/tmp con owner = usuario del dominio (el pool FPM corre
    como ese usuario). Idempotente. Mode 0700: solo el FPM del dominio escribe/
    lee ahí (sesiones, uploads, sys_temp), aislado del resto de dominios.
    """
    tmp = domain_tmp_dir(owner, domain)
    try:
        os.makedirs(tmp, exist_ok=True)
        subprocess.run(["chown", f"{owner}:{owner}", tmp], check=False, env=_SYS_ENV)
        subprocess.run(["chmod", "0700", tmp], check=False, env=_SYS_ENV)
    except (OSError, FileNotFoundError) as e:
        logger.warning(f"ensure_domain_tmp({domain}): {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Parsers / helpers
# ─────────────────────────────────────────────────────────────────────────────
def parse_php_size(value: str) -> int:
    """
    Convierte '256M', '1G', '512K', '-1', '0' o bytes a int bytes.
    -1 (ilimitado) → número enorme para comparaciones.
    """
    if value is None:
        return 0
    s = str(value).strip()
    if s in ("-1", ""):
        return 1 << 62
    m = re.match(r"^(\d+)\s*([KMGkmg]?)$", s)
    if not m:
        try:
            n = int(s)
            return (1 << 62) if n < 0 else n
        except ValueError:
            return 0
    num = int(m.group(1))
    unit = m.group(2).upper()
    mult = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}[unit]
    return num * mult


def get_php_ini_path(version: str) -> str:
    return PHP_INI_TMPL.format(ver=version)


def get_pool_path(version: str, domain: str) -> str:
    return POOL_DIR_TMPL.format(ver=version, domain=domain)


def pool_socket_path(domain: str) -> str:
    """Socket dedicado, sin versión (sobrevive cambios de versión PHP)."""
    return f"/run/php/svqpanel-{domain}.sock"


def read_server_ini_value(version: str, directive: str) -> Optional[str]:
    """Lee el valor de una directiva del php.ini global de FPM."""
    path = get_php_ini_path(version)
    if not os.path.isfile(path):
        return None
    pat = re.compile(rf"^\s*{re.escape(directive)}\s*=\s*(.+?)\s*$")
    found = None
    try:
        with open(path) as f:
            for line in f:
                if line.lstrip().startswith(";"):
                    continue
                m = pat.match(line)
                if m:
                    found = m.group(1).strip().strip('"')
    except OSError:
        return None
    return found


# ─────────────────────────────────────────────────────────────────────────────
# Validación
# ─────────────────────────────────────────────────────────────────────────────
def validate_overrides(version: str, overrides: Dict[str, str]) -> Tuple[bool, List[str]]:
    """Valida overrides contra la lista curada + límites del servidor."""
    errors: List[str] = []

    for key, raw in overrides.items():
        spec = PHP_INI_DIRECTIVES.get(key)
        if not spec:
            errors.append(f"'{key}' no es una directiva permitida")
            continue
        val = str(raw).strip()
        if val == "":
            errors.append(f"'{key}' no puede estar vacío")
            continue

        t = spec["type"]
        if t == "size":
            if not re.match(r"^(\d+\s*[KMGkmg]?|-1)$", val):
                errors.append(f"'{key}': formato inválido (ej. 256M, 1G, -1)")
                continue
        elif t == "int":
            if not re.match(r"^-?\d+$", val):
                errors.append(f"'{key}': debe ser un entero")
                continue
        elif t == "bool":
            if val not in ("On", "Off", "0", "1", "on", "off"):
                errors.append(f"'{key}': debe ser On/Off")
                continue
        elif t == "tz":
            if not re.match(r"^[A-Za-z]+(/[A-Za-z0-9_+\-]+)*$", val):
                errors.append(f"'{key}': zona horaria inválida")
                continue

        if spec.get("cap"):
            server_raw = read_server_ini_value(version, key)
            if server_raw is not None:
                if t == "size":
                    if parse_php_size(val) > parse_php_size(server_raw):
                        errors.append(f"'{key}': {val} supera el límite del servidor ({server_raw})")
                elif t == "int":
                    try:
                        sv = int(server_raw); cv = int(val)
                        sv_eff = (1 << 31) if sv == 0 else sv
                        cv_eff = (1 << 31) if cv == 0 else cv
                        if cv_eff > sv_eff:
                            errors.append(f"'{key}': {val} supera el límite del servidor ({server_raw})")
                    except ValueError:
                        pass

    return (len(errors) == 0, errors)


# ─────────────────────────────────────────────────────────────────────────────
# Generación del pool FPM
# ─────────────────────────────────────────────────────────────────────────────
def _pool_content(domain: str, owner: str, overrides: Dict[str, str],
                  relax_hardening: bool = False,
                  fpm_tuning: Optional[dict] = None) -> str:
    backend = domain.replace(".", "_").replace("-", "_")
    socket = pool_socket_path(domain)
    lines = [
        f"; SVQPanel — pool dedicado para {domain} (php.ini por dominio)",
        f"[svqpanel_{backend}]",
        # El pool corre como el USUARIO del dominio (no www-data): así PHP puede
        # escribir en su propio public_html (.htaccess de WordPress, uploads,
        # actualizaciones de plugins…) y cada dominio queda aislado por UID
        # (un sitio no puede tocar los ficheros de otro). open_basedir +
        # disable_functions siguen aplicando como capa extra de hardening.
        f"user = {owner}",
        f"group = {owner}",
        f"listen = {socket}",
        # El socket lo abre/lee el servidor web (nginx/apache = www-data), por eso
        # listen.* sí es www-data; sin esto el front no podría conectar al pool.
        "listen.owner = www-data",
        "listen.group = www-data",
        "listen.mode = 0660",
    ]
    # Tuning del process manager (pm.*): editable por dominio con presets + manual.
    # resolve_fpm_tuning aplica caps del servidor y coherencia de directivas.
    eff = resolve_fpm_tuning(fpm_tuning)
    # Orden estable y legible: pm primero, luego el resto.
    pm_keys_order = [
        "pm", "pm.max_children", "pm.start_servers", "pm.min_spare_servers",
        "pm.max_spare_servers", "pm.process_idle_timeout", "pm.max_requests",
    ]
    for k in pm_keys_order:
        if k in eff:
            lines.append(f"{k} = {eff[k]}")
    lines.extend([
        "",
        "; --- Seguridad (cap duro, no overridable por el cliente) ---",
    ])
    # Bloque de seguridad SIEMPRE (open_basedir, disable_functions, tmp aislado)
    lines.extend(_security_block(owner, domain, relax_hardening))
    lines.append("")
    # Overrides opcionales del cliente (van después; no pueden tocar php_admin_value)
    for key, raw in overrides.items():
        spec = PHP_INI_DIRECTIVES.get(key)
        if not spec:
            continue
        val = str(raw).strip()
        directive = "php_admin_value" if spec["admin"] else "php_value"
        lines.append(f'{directive}[{key}] = {val}')
    lines.append("")
    return "\n".join(lines)


def _fpm_service(version: str) -> str:
    return f"php{version}-fpm"


def _reload_fpm(version: str) -> Tuple[bool, str]:
    binp = f"/usr/sbin/php-fpm{version}"
    if os.path.exists(binp):
        test = subprocess.run([binp, "-t"], capture_output=True, text=True, env=_SYS_ENV)
        if test.returncode != 0:
            return False, f"php-fpm{version} -t: {test.stderr.strip()}"
    r = subprocess.run(["systemctl", "reload", _fpm_service(version)],
                       capture_output=True, text=True, env=_SYS_ENV)
    if r.returncode != 0:
        r = subprocess.run(["systemctl", "restart", _fpm_service(version)],
                           capture_output=True, text=True, env=_SYS_ENV)
    return (r.returncode == 0), (r.stderr.strip() or "ok")


def write_pool(domain: str, version: str, owner: str, overrides: Dict[str, str],
               relax_hardening: bool = False,
               fpm_tuning: Optional[dict] = None) -> Tuple[bool, str]:
    """Escribe el pool del dominio para la versión dada y recarga FPM.

    fpm_tuning: dict {"preset": ..., "manual": {...}} para los pm.* del pool.
                Si None, se usa el preset por defecto (medium).
    """
    remove_pool(domain, except_version=version, reload_fpm=True)

    # Asegurar el tmp aislado del dominio (sesiones/uploads, owner www-data)
    ensure_domain_tmp(owner, domain)

    path = get_pool_path(version, domain)
    if not os.path.isdir(os.path.dirname(path)):
        return False, f"PHP {version} no está instalado ({os.path.dirname(path)} no existe)"
    try:
        with open(path, "w") as f:
            f.write(_pool_content(domain, owner, overrides, relax_hardening, fpm_tuning))
    except OSError as e:
        return False, f"no pude escribir el pool: {e}"

    ok, msg = _reload_fpm(version)
    if not ok:
        try:
            os.remove(path)
            _reload_fpm(version)
        except OSError:
            pass
        return False, msg
    return True, "ok"


def remove_pool(domain: str, except_version: Optional[str] = None, reload_fpm: bool = True) -> None:
    """Elimina el pool del dominio de TODAS las versiones (salvo except_version)."""
    for ver in PHP_VERSIONS:
        if ver == except_version:
            continue
        path = get_pool_path(ver, domain)
        if os.path.isfile(path):
            try:
                os.remove(path)
                if reload_fpm:
                    _reload_fpm(ver)
            except OSError:
                pass


def has_pool(domain: str) -> Optional[str]:
    """Devuelve la versión cuyo pool existe para el dominio, o None."""
    for ver in PHP_VERSIONS:
        if os.path.isfile(get_pool_path(ver, domain)):
            return ver
    return None


def server_defaults(version: str) -> Dict[str, Optional[str]]:
    """Valores actuales del servidor para las directivas curadas."""
    return {k: read_server_ini_value(version, k) for k in PHP_INI_DIRECTIVES}


# ─────────────────────────────────────────────────────────────────────────────
# Tuning del pool FPM (pm.*) — validación, normalización y resolución a directivas
# ─────────────────────────────────────────────────────────────────────────────
def resolve_fpm_tuning(fpm: Optional[dict]) -> Dict[str, object]:
    """
    A partir de la config de tuning de un dominio (puede ser None, un preset, o
    un preset + ajustes manuales), devuelve el dict de directivas pm.* efectivas
    listas para escribir en el pool.

    Estructura de entrada esperada (fpm):
        {"preset": "low|medium|high", "manual": {"pm.max_children": 12, ...}}
    - Si fpm es None o vacío → preset por defecto (medium).
    - "manual" sobreescribe claves concretas del preset (sin pasar de los caps).
    - Si manual fija pm=static/ondemand, las claves dynamic-only se omiten.
    """
    fpm = fpm or {}
    preset_name = fpm.get("preset") or FPM_DEFAULT_PRESET
    if preset_name not in FPM_PRESETS:
        preset_name = FPM_DEFAULT_PRESET

    # Base = copia del preset
    eff: Dict[str, object] = {k: v for k, v in FPM_PRESETS[preset_name].items()
                              if k not in ("label", "description")}

    # Aplicar ajustes manuales encima
    manual = fpm.get("manual") or {}
    for key, val in manual.items():
        if key in _FPM_TUNABLE:
            eff[key] = val

    # Caps duros (el cliente no puede superar el servidor)
    if "pm.max_children" in eff:
        eff["pm.max_children"] = min(int(eff["pm.max_children"]), FPM_MAX_CHILDREN_CAP)
    if "pm.max_requests" in eff:
        eff["pm.max_requests"] = min(int(eff["pm.max_requests"]), FPM_MAX_REQUESTS_CAP)

    pm_mode = eff.get("pm", "ondemand")

    # Coherencia de directivas según el modo pm:
    #   - dynamic: requiere start/min/max spare; max_children debe ser >= max_spare
    #   - ondemand/static: las directivas *_servers no aplican (FPM avisaría)
    if pm_mode == "dynamic":
        mc = int(eff.get("pm.max_children", 10))
        mx_spare = min(int(eff.get("pm.max_spare_servers", 8)), mc)
        mn_spare = min(int(eff.get("pm.min_spare_servers", 2)), mx_spare)
        start = int(eff.get("pm.start_servers", mn_spare))
        start = max(mn_spare, min(start, mx_spare))
        eff["pm.max_spare_servers"] = mx_spare
        eff["pm.min_spare_servers"] = mn_spare
        eff["pm.start_servers"]     = start
        eff.pop("pm.process_idle_timeout", None)  # solo aplica a ondemand
    else:
        # ondemand / static: quitar directivas dynamic-only
        for k in ("pm.start_servers", "pm.min_spare_servers", "pm.max_spare_servers"):
            eff.pop(k, None)
        if pm_mode == "static":
            eff.pop("pm.process_idle_timeout", None)
        elif pm_mode == "ondemand":
            eff.setdefault("pm.process_idle_timeout", "10s")
    return eff


# Claves que el cliente puede ajustar manualmente (resto se derivan/protegen).
_FPM_TUNABLE = {
    "pm", "pm.max_children", "pm.max_requests", "pm.process_idle_timeout",
    "pm.start_servers", "pm.min_spare_servers", "pm.max_spare_servers",
}


def validate_fpm_tuning(fpm: Optional[dict]) -> Tuple[bool, List[str]]:
    """Valida la config de tuning FPM de un dominio antes de escribirla."""
    errors: List[str] = []
    fpm = fpm or {}

    preset = fpm.get("preset")
    if preset is not None and preset not in FPM_PRESETS:
        errors.append(f"preset '{preset}' no válido (low/medium/high)")

    manual = fpm.get("manual") or {}
    if not isinstance(manual, dict):
        return False, ["'manual' debe ser un objeto"]

    pm_mode = manual.get("pm")
    if pm_mode is not None and pm_mode not in ("ondemand", "dynamic", "static"):
        errors.append("pm debe ser ondemand, dynamic o static")

    for key in ("pm.max_children", "pm.max_requests", "pm.start_servers",
                "pm.min_spare_servers", "pm.max_spare_servers"):
        if key in manual:
            try:
                n = int(manual[key])
            except (ValueError, TypeError):
                errors.append(f"{key}: debe ser un entero")
                continue
            if n < 1:
                errors.append(f"{key}: debe ser >= 1")
            if key == "pm.max_children" and n > FPM_MAX_CHILDREN_CAP:
                errors.append(f"pm.max_children: {n} supera el máximo del servidor ({FPM_MAX_CHILDREN_CAP})")
            if key == "pm.max_requests" and n > FPM_MAX_REQUESTS_CAP:
                errors.append(f"pm.max_requests: {n} supera el máximo del servidor ({FPM_MAX_REQUESTS_CAP})")

    if "pm.process_idle_timeout" in manual:
        if not re.match(r"^\d+\s*[smhd]?$", str(manual["pm.process_idle_timeout"]).strip()):
            errors.append("pm.process_idle_timeout: formato inválido (ej. 10s, 1m)")

    return (len(errors) == 0, errors)
