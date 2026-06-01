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
PHP_VERSIONS  = ["7.4", "8.0", "8.1", "8.2", "8.3", "8.4", "8.5"]

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
    Crea {domain_root}/tmp con owner www-data (PHP-FPM corre como www-data).
    Idempotente. Mode 0700: solo FPM escribe/lee ahí (sesiones, uploads).
    """
    tmp = domain_tmp_dir(owner, domain)
    try:
        os.makedirs(tmp, exist_ok=True)
        subprocess.run(["chown", "www-data:www-data", tmp], check=False, env=_SYS_ENV)
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
                  relax_hardening: bool = False) -> str:
    backend = domain.replace(".", "_").replace("-", "_")
    socket = pool_socket_path(domain)
    lines = [
        f"; SVQPanel — pool dedicado para {domain} (php.ini por dominio)",
        f"[svqpanel_{backend}]",
        "user = www-data",
        "group = www-data",
        f"listen = {socket}",
        "listen.owner = www-data",
        "listen.group = www-data",
        "listen.mode = 0660",
        "pm = ondemand",
        "pm.max_children = 10",
        "pm.process_idle_timeout = 10s",
        "pm.max_requests = 500",
        "",
        "; --- Seguridad (cap duro, no overridable por el cliente) ---",
    ]
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
               relax_hardening: bool = False) -> Tuple[bool, str]:
    """Escribe el pool del dominio para la versión dada y recarga FPM."""
    remove_pool(domain, except_version=version, reload_fpm=True)

    # Asegurar el tmp aislado del dominio (sesiones/uploads, owner www-data)
    ensure_domain_tmp(owner, domain)

    path = get_pool_path(version, domain)
    if not os.path.isdir(os.path.dirname(path)):
        return False, f"PHP {version} no está instalado ({os.path.dirname(path)} no existe)"
    try:
        with open(path, "w") as f:
            f.write(_pool_content(domain, owner, overrides, relax_hardening))
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
