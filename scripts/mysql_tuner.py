"""
MySQL/MariaDB tuner (Fase 21)

Lee el estado real del servidor de BD (SHOW GLOBAL STATUS / VARIABLES), calcula
métricas clave (buffer pool hit ratio, uso de conexiones, temp tables en disco,
etc.) y genera recomendaciones tipo mysqltuner. Permite además escribir un
conjunto curado de directivas a un drop-in propio de SVQPanel en el my.cnf, sin
tocar la configuración base de la distro.

Diseño:
  - SIN dependencias Python extra: usa el cliente CLI (mariadb/mysql) igual que
    api/routes/databases.py. Las credenciales se leen de .env (MARIADB_*).
  - La config se escribe SOLO en /etc/mysql/mariadb.conf.d/99-svqpanel-tuner.cnf
    (o el equivalente). Nunca tocamos los .cnf de la distro → reversible borrando
    ese único archivo.
  - El tuner NO aplica nada solo: el admin revisa las recomendaciones y decide.
    Aplicar = escribir el drop-in + (opcional) reiniciar el servicio.

Política de seguridad: solo admin (lo cablea la ruta API). Las directivas
editables están en una allowlist curada (TUNABLE_DIRECTIVES); cualquier otra se
rechaza para no permitir inyectar opciones arbitrarias en el my.cnf.
"""

import logging
import os
import re
import subprocess
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Posibles ubicaciones del drop-in según la distro/empaquetado.
_DROPIN_CANDIDATE_DIRS = [
    "/etc/mysql/mariadb.conf.d",   # Debian/MariaDB
    "/etc/mysql/conf.d",           # Debian/MySQL genérico
    "/etc/my.cnf.d",               # RHEL-style (por si acaso)
]
_DROPIN_FILENAME = "99-svqpanel-tuner.cnf"


# ─────────────────────────────────────────────────────────────────────────────
# Allowlist de directivas que el panel puede tocar. Cada una con:
#   section: bloque del my.cnf ([mysqld] casi siempre)
#   type:    size | int | bool
#   label/help: para la UI
#   cap:     tope superior razonable (None = sin tope fijo, se valida >0)
# ─────────────────────────────────────────────────────────────────────────────
TUNABLE_DIRECTIVES: Dict[str, dict] = {
    "innodb_buffer_pool_size": {
        "section": "mysqld", "type": "size", "label": "InnoDB Buffer Pool",
        "help": "Memoria para cachear datos/índices InnoDB. Lo más importante para el rendimiento. Típico: 50-70% de la RAM en un servidor dedicado a BD.",
    },
    "innodb_log_file_size": {
        "section": "mysqld", "type": "size", "label": "InnoDB Log File",
        "help": "Tamaño del redo log. Mayor = menos flushes pero recuperación más lenta. Típico: 128M-512M.",
    },
    "max_connections": {
        "section": "mysqld", "type": "int", "label": "Máx. conexiones",
        "help": "Conexiones simultáneas. Subirlo consume RAM por conexión; no lo infles sin necesidad.",
    },
    "innodb_flush_log_at_trx_commit": {
        "section": "mysqld", "type": "int", "label": "Flush log en commit",
        "help": "1 = máxima durabilidad (default). 2 = más rápido, puede perder ~1s de transacciones si cae el SO. Solo bájalo si sabes lo que haces.",
    },
    "query_cache_type": {
        "section": "mysqld", "type": "int", "label": "Query cache (tipo)",
        "help": "0 = desactivado (recomendado en MySQL 5.7+/MariaDB con alta concurrencia: el query cache suele ser contraproducente).",
    },
    "query_cache_size": {
        "section": "mysqld", "type": "size", "label": "Query cache (tamaño)",
        "help": "Tamaño del query cache. Si query_cache_type=0, ponlo a 0.",
    },
    "tmp_table_size": {
        "section": "mysqld", "type": "size", "label": "Tmp table size",
        "help": "Tamaño máx. de tablas temporales en memoria antes de pasar a disco. Debe ir junto con max_heap_table_size.",
    },
    "max_heap_table_size": {
        "section": "mysqld", "type": "size", "label": "Max heap table",
        "help": "Tamaño máx. de tablas MEMORY. Mantenlo igual a tmp_table_size.",
    },
    "table_open_cache": {
        "section": "mysqld", "type": "int", "label": "Table open cache",
        "help": "Número de tablas abiertas que se cachean. Súbelo si Opened_tables crece rápido.",
    },
    "innodb_buffer_pool_instances": {
        "section": "mysqld", "type": "int", "label": "Buffer pool instances",
        "help": "Divide el buffer pool en N instancias (reduce contención). 1 por cada GB de buffer pool, hasta 8.",
    },
    "slow_query_log": {
        "section": "mysqld", "type": "bool", "label": "Slow query log",
        "help": "Registra consultas lentas para diagnóstico. Útil temporalmente.",
    },
    "long_query_time": {
        "section": "mysqld", "type": "int", "label": "Umbral consulta lenta (s)",
        "help": "Segundos a partir de los cuales una consulta se considera lenta.",
    },
}


_SYS_ENV = {
    **os.environ,
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
}


# ─────────────────────────────────────────────────────────────────────────────
# Parsers / helpers de tamaño
# ─────────────────────────────────────────────────────────────────────────────
def parse_size(value) -> int:
    """'256M','1G','512K','1.9G','1073741824' → bytes int. -1/None → 0."""
    if value is None:
        return 0
    s = str(value).strip()
    if s in ("", "-1"):
        return 0
    # Acepta decimales (1.9G) además de enteros (512M)
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([KMGTkmgt]?)B?$", s)
    if not m:
        try:
            return int(float(s))
        except ValueError:
            return 0
    num = float(m.group(1))
    unit = m.group(2).upper()
    mult = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}[unit]
    return int(num * mult)


def human_size(num_bytes: int) -> str:
    """bytes → '1.5G' legible (para mostrar). Puede llevar 1 decimal."""
    n = float(num_bytes)
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            if unit == "B":
                return f"{int(n)}B"
            return f"{n:.1f}{unit}".replace(".0", "")
        n /= 1024
    return f"{n:.1f}T"


def human_size_mycnf(num_bytes: int) -> str:
    """
    bytes → tamaño ENTERO + unidad válido para my.cnf (sin decimales).
    Usa la mayor unidad que dé un entero exacto; si ninguna es exacta, redondea
    en MB (precisión más que suficiente para estas directivas).
    Ej.: 2147483648 → '2G'; 2040109465 (~1.9G) → '1946M'.
    MySQL/MariaDB NO acepta decimales (1.9G es inválido), por eso este helper.
    """
    if num_bytes <= 0:
        return "0"
    for unit, mult in (("G", 1024**3), ("M", 1024**2), ("K", 1024)):
        if num_bytes >= mult and num_bytes % mult == 0:
            return f"{num_bytes // mult}{unit}"
    # Sin unidad exacta: redondear a MB (o KB si es < 1 MB)
    if num_bytes >= 1024**2:
        return f"{round(num_bytes / 1024**2)}M"
    if num_bytes >= 1024:
        return f"{round(num_bytes / 1024)}K"
    return f"{num_bytes}"


def validate_directive(name: str, value: str) -> Tuple[bool, str]:
    """Valida una directiva contra la allowlist. Devuelve (ok, error|valor_limpio)."""
    spec = TUNABLE_DIRECTIVES.get(name)
    if not spec:
        return False, f"'{name}' no es una directiva editable"
    v = str(value).strip()
    if v == "":
        return False, f"'{name}' no puede estar vacío"
    t = spec["type"]
    if t == "size":
        # Acepta enteros (512M) y, por robustez, decimales (1.9G) que normalizamos
        # a un entero válido para my.cnf (MySQL no acepta decimales).
        if not re.match(r"^\d+(?:\.\d+)?\s*[KMGkmg]?$", v):
            return False, f"'{name}': formato inválido (ej. 512M, 2G)"
        if "." in v:
            v = human_size_mycnf(parse_size(v))
    elif t == "int":
        if not re.match(r"^\d+$", v):
            return False, f"'{name}': debe ser un entero positivo"
    elif t == "bool":
        if v not in ("0", "1", "ON", "OFF", "on", "off"):
            return False, f"'{name}': debe ser 0/1/ON/OFF"
        v = "1" if v in ("1", "ON", "on") else "0"
    return True, v


# ─────────────────────────────────────────────────────────────────────────────
# Lectura del estado real del servidor
# ─────────────────────────────────────────────────────────────────────────────
class MySQLTuner:
    def __init__(self, host: str, user: str, password: str):
        self.host = host
        self.user = user
        self.password = password

    def _binary(self) -> str:
        import shutil
        for path in ("/usr/bin/mariadb", "/usr/bin/mysql",
                     "/usr/local/bin/mariadb", "/usr/local/bin/mysql"):
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
        for b in ("mariadb", "mysql"):
            found = shutil.which(b)
            if found:
                return found
        raise Exception("Cliente MariaDB/MySQL no encontrado (apt install mariadb-client)")

    def _query_pairs(self, sql: str) -> Dict[str, str]:
        """Ejecuta un SHOW … y devuelve {nombre: valor} (formato tabular de 2 cols)."""
        binary = self._binary()
        cmd = [binary, f"--host={self.host}", f"--user={self.user}",
               f"--password={self.password}", "--silent", "--skip-column-names",
               "--execute", sql]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=_SYS_ENV)
        if result.returncode != 0:
            err = "\n".join(l for l in result.stderr.splitlines()
                            if "Using a password" not in l and "Deprecated" not in l)
            raise Exception(err or "Error consultando MariaDB")
        out: Dict[str, str] = {}
        for line in result.stdout.splitlines():
            if "\t" in line:
                k, v = line.split("\t", 1)
                out[k.strip()] = v.strip()
        return out

    def get_status(self) -> Dict[str, str]:
        return self._query_pairs("SHOW GLOBAL STATUS")

    def get_variables(self) -> Dict[str, str]:
        return self._query_pairs("SHOW GLOBAL VARIABLES")

    def get_system_ram_bytes(self) -> int:
        """RAM total del host (para dimensionar el buffer pool)."""
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return kb * 1024
        except (OSError, ValueError):
            pass
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# Diagnóstico + recomendaciones (estilo mysqltuner, simplificado y seguro)
# ─────────────────────────────────────────────────────────────────────────────
def _f(d: Dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(d.get(key, default))
    except (ValueError, TypeError):
        return default


def analyze(status: Dict[str, str], variables: Dict[str, str], ram_bytes: int) -> Dict:
    """
    Devuelve un dict con métricas y una lista de recomendaciones. Cada
    recomendación: {level, title, detail, directive?, suggested?}.
    level: 'ok' | 'info' | 'warn' | 'crit'.
    """
    recs: List[Dict] = []
    metrics: Dict[str, object] = {}

    uptime = _f(status, "Uptime", 1)

    # ── InnoDB buffer pool hit ratio ──────────────────────────────────────────
    reads = _f(status, "Innodb_buffer_pool_reads")           # desde disco
    req = _f(status, "Innodb_buffer_pool_read_requests")     # totales
    if req > 0:
        hit = (1 - reads / req) * 100
        metrics["innodb_buffer_hit_pct"] = round(hit, 2)
        bp_size = parse_size(variables.get("innodb_buffer_pool_size"))
        metrics["innodb_buffer_pool_size"] = human_size(bp_size)
        if hit < 99 and uptime > 3600:
            suggested = bp_size
            if ram_bytes:
                suggested = int(ram_bytes * 0.5)  # 50% de la RAM como objetivo
            recs.append({
                "level": "warn",
                "title": "Buffer pool InnoDB pequeño",
                "detail": f"Hit ratio {hit:.1f}% (objetivo ≥ 99%). El buffer pool actual ({human_size(bp_size)}) no cabe el dataset; hay lecturas a disco.",
                "directive": "innodb_buffer_pool_size",
                "suggested": human_size_mycnf(suggested),
            })
        else:
            recs.append({
                "level": "ok",
                "title": "Buffer pool InnoDB",
                "detail": f"Hit ratio {hit:.1f}% — bien.",
            })

    # ── Conexiones ────────────────────────────────────────────────────────────
    max_conn = _f(variables, "max_connections", 1)
    max_used = _f(status, "Max_used_connections")
    if max_conn > 0:
        used_pct = max_used / max_conn * 100
        metrics["max_connections"] = int(max_conn)
        metrics["max_used_connections"] = int(max_used)
        metrics["connections_used_pct"] = round(used_pct, 1)
        if used_pct > 85:
            recs.append({
                "level": "warn",
                "title": "Conexiones cerca del límite",
                "detail": f"Se llegó al {used_pct:.0f}% de max_connections ({int(max_used)}/{int(max_conn)}). Considera subirlo si tienes RAM.",
                "directive": "max_connections",
                "suggested": str(int(max_conn * 1.5)),
            })
        # Connection aborts
        aborted = _f(status, "Aborted_connects")
        if aborted > 100 and uptime > 3600:
            recs.append({
                "level": "info",
                "title": "Conexiones abortadas",
                "detail": f"{int(aborted)} conexiones abortadas. Suele ser timeouts o credenciales; revisa apps que no cierran conexiones.",
            })

    # ── Tablas temporales en disco ────────────────────────────────────────────
    tmp_disk = _f(status, "Created_tmp_disk_tables")
    tmp_total = _f(status, "Created_tmp_tables")
    if tmp_total > 0:
        disk_pct = tmp_disk / tmp_total * 100
        metrics["tmp_tables_on_disk_pct"] = round(disk_pct, 1)
        if disk_pct > 25 and tmp_total > 1000:
            recs.append({
                "level": "warn",
                "title": "Muchas tablas temporales en disco",
                "detail": f"{disk_pct:.0f}% de las tablas temporales van a disco (lento). Sube tmp_table_size y max_heap_table_size por igual.",
                "directive": "tmp_table_size",
                "suggested": human_size_mycnf(max(parse_size(variables.get("tmp_table_size")), 64 * 1024**2)),
            })

    # ── Query cache (anti-patrón en concurrencia alta) ────────────────────────
    qc_type = variables.get("query_cache_type", "OFF")
    qc_size = parse_size(variables.get("query_cache_size"))
    if qc_type not in ("OFF", "0") and qc_size > 0:
        recs.append({
            "level": "info",
            "title": "Query cache activado",
            "detail": "El query cache suele degradar el rendimiento con escrituras frecuentes/concurrencia. Recomendado desactivarlo (query_cache_type=0, query_cache_size=0).",
            "directive": "query_cache_type",
            "suggested": "0",
        })

    # ── Table open cache ──────────────────────────────────────────────────────
    opened = _f(status, "Opened_tables")
    toc = _f(variables, "table_open_cache", 1)
    if uptime > 3600 and opened > toc * 2 and opened > 5000:
        recs.append({
            "level": "info",
            "title": "table_open_cache pequeño",
            "detail": f"{int(opened)} tablas abiertas vs cache de {int(toc)}. Subir table_open_cache reduce reaperturas.",
            "directive": "table_open_cache",
            "suggested": str(int(toc * 2)),
        })

    # ── Slow queries ──────────────────────────────────────────────────────────
    slow = _f(status, "Slow_queries")
    questions = _f(status, "Questions", 1)
    if questions > 0:
        slow_pct = slow / questions * 100
        metrics["slow_query_pct"] = round(slow_pct, 3)
        if slow_pct > 0.5 and slow > 50:
            recs.append({
                "level": "info",
                "title": "Consultas lentas detectadas",
                "detail": f"{int(slow)} consultas lentas ({slow_pct:.2f}% del total). Activa slow_query_log para identificarlas y añade índices.",
                "directive": "slow_query_log",
                "suggested": "1",
            })

    metrics["uptime_hours"] = round(uptime / 3600, 1)
    metrics["ram_total"] = human_size(ram_bytes) if ram_bytes else "desconocida"

    # Resumen del nivel global
    levels = [r["level"] for r in recs]
    if "crit" in levels:
        overall = "crit"
    elif "warn" in levels:
        overall = "warn"
    elif "info" in levels:
        overall = "info"
    else:
        overall = "ok"

    return {"overall": overall, "metrics": metrics, "recommendations": recs}


# ─────────────────────────────────────────────────────────────────────────────
# Escritura del drop-in my.cnf (solo directivas de la allowlist)
# ─────────────────────────────────────────────────────────────────────────────
def find_dropin_dir() -> Optional[str]:
    for d in _DROPIN_CANDIDATE_DIRS:
        if os.path.isdir(d):
            return d
    return None


def dropin_path() -> Optional[str]:
    d = find_dropin_dir()
    return os.path.join(d, _DROPIN_FILENAME) if d else None


def read_current_dropin() -> Dict[str, str]:
    """Lee las directivas actualmente escritas por el panel en su drop-in."""
    path = dropin_path()
    out: Dict[str, str] = {}
    if not path or not os.path.isfile(path):
        return out
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("["):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def write_dropin(directives: Dict[str, str]) -> Tuple[bool, str]:
    """
    Escribe el drop-in del panel con las directivas dadas (allowlist validada).
    Agrupa por sección. Devuelve (ok, mensaje). No reinicia el servicio.
    """
    # Validar todas antes de escribir nada
    clean: Dict[str, str] = {}
    for name, val in directives.items():
        ok, res = validate_directive(name, val)
        if not ok:
            return False, res
        clean[name] = res

    d = find_dropin_dir()
    if not d:
        return False, "No encontré el directorio conf.d de MariaDB/MySQL en este servidor"
    path = os.path.join(d, _DROPIN_FILENAME)

    # Agrupar por sección
    sections: Dict[str, List[str]] = {}
    for name, val in clean.items():
        sec = TUNABLE_DIRECTIVES[name]["section"]
        sections.setdefault(sec, []).append(f"{name} = {val}")

    lines = [
        "# SVQPanel — tuning de MariaDB/MySQL (gestionado por el panel)",
        "# NO editar a mano: el panel reescribe este archivo. Borra el fichero",
        "# para revertir a la configuración por defecto de la distro.",
        "",
    ]
    for sec, entries in sections.items():
        lines.append(f"[{sec}]")
        lines.extend(sorted(entries))
        lines.append("")

    try:
        with open(path, "w") as f:
            f.write("\n".join(lines))
        os.chmod(path, 0o644)
    except OSError as e:
        return False, f"No pude escribir {path}: {e}"
    return True, path


def restart_service() -> Tuple[bool, str]:
    """Reinicia mariadb (o mysql). Devuelve (ok, mensaje)."""
    for svc in ("mariadb", "mysql", "mysqld"):
        check = subprocess.run(["systemctl", "list-unit-files", f"{svc}.service"],
                               capture_output=True, text=True, env=_SYS_ENV)
        if svc in check.stdout:
            r = subprocess.run(["systemctl", "restart", svc],
                               capture_output=True, text=True, env=_SYS_ENV, timeout=60)
            if r.returncode == 0:
                return True, f"{svc} reiniciado"
            return False, r.stderr.strip() or f"fallo al reiniciar {svc}"
    return False, "No encontré el servicio mariadb/mysql"
