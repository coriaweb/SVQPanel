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


def format_directive_value(name: str, raw) -> Optional[str]:
    """
    Formatea el valor de una directiva para MOSTRARLO de forma legible según su
    tipo: 'size' → '96M' (en vez de 100663296); 'int'/'bool' → entero sin
    decimales ('10' en vez de '10.000000'). Devuelve None si raw es None.
    """
    if raw is None:
        return None
    spec = TUNABLE_DIRECTIVES.get(name)
    s = str(raw).strip()
    if not spec:
        return s
    t = spec["type"]
    if t == "size":
        # Formato legible para mostrar (96M, 1.9G). Si el usuario lo edita y
        # guarda un '1.9G', validate_directive lo normaliza a entero para my.cnf.
        b = parse_size(s)
        return human_size(b) if b > 0 else s
    if t in ("int", "bool"):
        # MariaDB devuelve long_query_time como '10.000000' → '10'
        try:
            f = float(s)
            return str(int(f)) if f == int(f) else s
        except ValueError:
            return s
    return s


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

    def get_innodb_dataset_bytes(self) -> int:
        """
        Tamaño real de los datos+índices InnoDB (de information_schema). Sirve
        para no recomendar un buffer pool mayor que el dataset: cachear más de
        lo que hay es desperdiciar RAM.
        Devuelve 0 si no se puede determinar.
        """
        sql = ("SELECT IFNULL(SUM(data_length + index_length),0) "
               "FROM information_schema.tables WHERE engine='InnoDB'")
        binary = self._binary()
        cmd = [binary, f"--host={self.host}", f"--user={self.user}",
               f"--password={self.password}", "--silent", "--skip-column-names",
               "--execute", sql]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=_SYS_ENV)
            if r.returncode == 0:
                return int((r.stdout or "0").strip() or 0)
        except (subprocess.SubprocessError, ValueError):
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


# ─────────────────────────────────────────────────────────────────────────────
# Dimensionado consciente del resto del stack (panel + nginx + PHP-FPM + correo)
# ─────────────────────────────────────────────────────────────────────────────
# RAM media que consume un proceso PHP-FPM bajo carga (estimación conservadora).
_PHP_PROCESS_MB = 40
# Colchón base para SO + nginx + panel (uvicorn) + Postfix/Dovecot/Rspamd.
_BASE_RESERVE_MB = 768
# Suelo y techo de seguridad para el buffer pool recomendado.
_MIN_BUFFER_POOL = 128 * 1024**2     # nunca recomendar menos de 128M
_MAX_BUFFER_POOL_RATIO = 0.70        # ni más del 70% de la RAM total


def estimate_php_fpm_ram_bytes() -> int:
    """
    Estima la RAM que puede llegar a usar PHP-FPM sumando pm.max_children de
    TODOS los pools del panel (cada hijo ~_PHP_PROCESS_MB). El panel gestiona
    estos pools, así que es una cota realista del consumo del stack PHP.
    Devuelve 0 si no hay pools / no se puede leer.
    """
    import glob
    total_children = 0
    found_any = False
    for conf in glob.glob("/etc/php/*/fpm/pool.d/*.conf"):
        try:
            with open(conf) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("pm.max_children"):
                        found_any = True
                        try:
                            total_children += int(line.split("=", 1)[1].strip())
                        except (ValueError, IndexError):
                            pass
        except OSError:
            continue
    if not found_any:
        return 0
    return total_children * _PHP_PROCESS_MB * 1024**2


def recommend_buffer_pool(ram_bytes: int, dataset_bytes: int,
                          reserved_bytes: int) -> int:
    """
    Recomienda un innodb_buffer_pool_size CONSCIENTE del servidor:
      - parte de la RAM libre tras reservar el resto del stack (panel, nginx,
        PHP-FPM, correo, SO);
      - no propone más que el dataset real (+30% de margen de crecimiento):
        cachear más de lo que existe es desperdiciar RAM;
      - respeta un suelo (128M) y un techo (70% de la RAM total).
    Devuelve bytes. 0 si no hay datos de RAM (no recomendar a ciegas).
    """
    if ram_bytes <= 0:
        return 0
    # RAM realmente disponible para la BD tras el resto del stack
    available = ram_bytes - reserved_bytes
    if available < _MIN_BUFFER_POOL:
        # Stack ya muy apretado: recomendar el mínimo razonable, no inflar
        available = _MIN_BUFFER_POOL
    # No cachear más de lo que ocupa el dataset (+30% para crecer)
    target = available
    if dataset_bytes > 0:
        target = min(available, int(dataset_bytes * 1.3))
    # Aplicar techo y suelo
    target = min(target, int(ram_bytes * _MAX_BUFFER_POOL_RATIO))
    target = max(target, _MIN_BUFFER_POOL)
    return target


def analyze(status: Dict[str, str], variables: Dict[str, str], ram_bytes: int,
            dataset_bytes: int = 0, reserved_bytes: int = 0) -> Dict:
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
        if dataset_bytes:
            metrics["innodb_dataset_size"] = human_size(dataset_bytes)
        if reserved_bytes:
            metrics["ram_reservada_stack"] = human_size(reserved_bytes)

        # Recomendación CONSCIENTE del servidor: cruza RAM total, RAM ya
        # comprometida por el resto del stack (panel/nginx/PHP-FPM/correo) y el
        # tamaño real del dataset. No es un 50% a ciegas.
        suggested = recommend_buffer_pool(ram_bytes, dataset_bytes, reserved_bytes)

        # ¿El dataset ya cabe en el buffer pool actual? Entonces aunque el hit
        # sea bajo (BD recién arrancada) no hay nada que subir.
        dataset_cabe = dataset_bytes and bp_size >= dataset_bytes

        # ¿Está SOBREDIMENSIONADO? El buffer pool es mucho mayor que lo necesario
        # y ese exceso es RAM que se le quita al resto del stack. Lo marcamos si
        # el actual supera al recomendado en un margen claro y el desperdicio es
        # significativo (≥ 256M), para no molestar por diferencias pequeñas.
        desperdicio = bp_size - suggested
        sobredimensionado = (
            suggested > 0 and bp_size > suggested * 1.5 and desperdicio >= 256 * 1024**2
        )

        if hit < 99 and uptime > 3600 and suggested > bp_size * 1.1 and not dataset_cabe:
            # Demasiado pequeño: provoca lecturas a disco
            partes = []
            if dataset_bytes:
                partes.append(f"el dataset InnoDB ocupa {human_size(dataset_bytes)}")
            if reserved_bytes:
                partes.append(f"se reservan ~{human_size(reserved_bytes)} para el panel, web, PHP y correo")
            razon = ("; ".join(partes) + ". ") if partes else ""
            recs.append({
                "level": "warn",
                "title": "Buffer pool InnoDB pequeño",
                "detail": (f"Hit ratio {hit:.1f}% (objetivo ≥ 99%): el buffer pool actual "
                           f"({human_size(bp_size)}) provoca lecturas a disco. {razon}"
                           f"Valor calculado para este servidor sin quedarte sin RAM."),
                "directive": "innodb_buffer_pool_size",
                "suggested": human_size_mycnf(suggested),
            })
        elif sobredimensionado:
            # Demasiado grande para los datos que hay: RAM desperdiciada
            recs.append({
                "level": "info",
                "title": "Buffer pool InnoDB sobredimensionado",
                "detail": (f"El buffer pool ({human_size(bp_size)}) es mucho mayor que los datos "
                           f"InnoDB ({human_size(dataset_bytes)}). Sobran ~{human_size(desperdicio)} "
                           f"de RAM reservada que no se usan y le hacen falta al panel, PHP y correo. "
                           f"Puedes bajarlo y liberar esa memoria."),
                "directive": "innodb_buffer_pool_size",
                "suggested": human_size_mycnf(suggested),
            })
        else:
            motivo = f"Hit ratio {hit:.1f}%"
            if dataset_cabe:
                motivo += f" — el dataset ({human_size(dataset_bytes)}) cabe entero en el buffer pool"
            recs.append({
                "level": "ok",
                "title": "Buffer pool InnoDB",
                "detail": f"{motivo}. Bien.",
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
            # Subir, pero acotado por la RAM: cada conexión cuesta ~per-thread
            # buffers (sort/read/join/net ≈ 4-8 MB). No proponer un número que
            # multiplicado por ese coste se coma la RAM libre.
            per_conn_mb = 6
            propuesto = int(max_conn * 1.5)
            if ram_bytes:
                libre = max(ram_bytes - reserved_bytes - parse_size(variables.get("innodb_buffer_pool_size")), 0)
                techo = int(libre / (per_conn_mb * 1024**2)) if libre else propuesto
                propuesto = max(int(max_conn) + 10, min(propuesto, techo))
            recs.append({
                "level": "warn",
                "title": "Conexiones cerca del límite",
                "detail": (f"Se llegó al {used_pct:.0f}% de max_connections "
                           f"({int(max_used)}/{int(max_conn)}). Sugerido teniendo en cuenta "
                           f"la RAM libre (~{per_conn_mb} MB por conexión)."),
                "directive": "max_connections",
                "suggested": str(propuesto),
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
