"""
Consumo de CPU y RAM por dominio, medido en su pool PHP-FPM dedicado.

Cada dominio tiene su pool (`[svqpanel_<dominio>]`, procesos con el título
"php-fpm: pool svqpanel_<dominio>"), así que sumar sus procesos da lo que
consume la web en PHP (no incluye MariaDB ni nginx/Apache, que son compartidos).

Cómo se mide (hilo de fondo dentro del panel, sin dependencias, leyendo /proc):
- Cada SCAN_SECONDS se recorren los procesos php-fpm y se acumula, por pool,
  el tiempo de CPU (utime+stime) gastado desde la pasada anterior.
  Los pools son pm=ondemand: los hijos mueren tras process_idle_timeout (10s)
  SIN actividad, por lo que con pasadas de 10s casi no se pierde CPU de los que
  mueren (en sus últimos segundos estaban ociosos). Un proceso nuevo cuenta
  toda su CPU desde que nació.
- RAM = PSS (/proc/<pid>/smaps_rollup), NO RSS: la OPcache es memoria compartida
  y con RSS cada proceso la contaría entera (en producción: 240 MB de RSS frente
  a 96 MB de PSS en el mismo proceso).
- Saturaciones: líneas "server reached max_children" de /var/log/php*-fpm.log
  (las peticiones esperan en cola: la web va lenta).
- Cada FLUSH_SECONDS (alineado a la hora de reloj) se guarda una fila por
  dominio con actividad en domain_resource_samples. Retención RETENTION_DAYS.
"""
import glob
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

SCAN_SECONDS = 10
FLUSH_SECONDS = 300
RETENTION_DAYS = 30

_POOL_RE = re.compile(r"^php-fpm: pool (svqpanel_\S+)")
_HITS_RE = re.compile(r"\[pool (svqpanel_\S+)\] server reached (?:pm\.)?max_children")
_FPM_LOG_GLOB = "/var/log/php*-fpm.log"

try:
    _CLK_TCK = os.sysconf("SC_CLK_TCK")
except (AttributeError, ValueError, OSError):
    _CLK_TCK = 100
_NCPU = os.cpu_count() or 1


def pool_name(domain_name: str) -> str:
    """Nombre del pool FPM de un dominio (igual que php_ini_manager._pool_content)."""
    return "svqpanel_" + domain_name.replace(".", "_").replace("-", "_")


def _read_pss_kb(pid: str, proc_dir: str = "/proc") -> int:
    try:
        with open(f"{proc_dir}/{pid}/smaps_rollup") as f:
            for line in f:
                if line.startswith("Pss:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    try:  # kernel sin smaps_rollup: RSS (sobrestima la memoria compartida)
        with open(f"{proc_dir}/{pid}/statm") as f:
            return int(f.read().split()[1]) * (os.sysconf("SC_PAGE_SIZE") // 1024)
    except (OSError, ValueError, IndexError):
        return 0


def _new_acc() -> dict:
    return {"ticks": 0, "mem_sum_kb": 0, "mem_max_kb": 0, "procs_max": 0, "hits": 0}


class ResourceSampler:
    def __init__(self, proc_dir: str = "/proc", log_glob: str = _FPM_LOG_GLOB):
        self.proc_dir = proc_dir
        self.log_glob = log_glob
        self.lock = threading.Lock()
        self._prev = {}          # pid -> (starttime, ticks)
        self._first = True
        self._last_scan = None   # monotonic de la pasada anterior
        self.acc = {}            # pool -> acumulado del bucket en curso
        self.scans = 0           # pasadas en el bucket en curso
        self.live = {}           # pool -> {"cpu_percent", "mem_mb", "procs"} (última pasada)
        self._log_pos = {}       # ruta -> (inode, offset)

    # ── /proc ──────────────────────────────────────────────────────────────
    def _iter_pool_procs(self):
        """(pid, pool, starttime, ticks) de cada hijo de un pool svqpanel_*."""
        try:
            pids = [p for p in os.listdir(self.proc_dir) if p.isdigit()]
        except OSError:
            return
        for pid in pids:
            try:
                with open(f"{self.proc_dir}/{pid}/stat") as f:
                    stat = f.read()
                lp, rp = stat.find("("), stat.rfind(")")
                if not stat[lp + 1:rp].startswith("php-fpm"):
                    continue
                with open(f"{self.proc_dir}/{pid}/cmdline", "rb") as f:
                    cmd = f.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
                m = _POOL_RE.match(cmd)
                if not m:
                    continue          # el master o un pool que no es del panel
                fields = stat[rp + 2:].split()
                ticks = int(fields[11]) + int(fields[12])   # utime + stime
                starttime = int(fields[19])
            except (OSError, ValueError, IndexError):
                continue              # el proceso murió entre medias
            yield pid, m.group(1), starttime, ticks

    def scan(self):
        now = time.monotonic()
        elapsed = (now - self._last_scan) if self._last_scan else None
        cur, per_pool = {}, {}
        for pid, pool, starttime, ticks in self._iter_pool_procs():
            prev = self._prev.get(pid)
            if prev and prev[0] == starttime:
                delta = max(0, ticks - prev[1])
            else:
                # Proceso nuevo: toda su CPU es de este intervalo. En la primera
                # pasada no: la CPU histórica de procesos viejos no es de ahora.
                delta = 0 if self._first else ticks
            cur[pid] = (starttime, ticks)
            p = per_pool.setdefault(pool, {"ticks": 0, "mem_kb": 0, "procs": 0})
            p["ticks"] += delta
            p["mem_kb"] += _read_pss_kb(pid, self.proc_dir)
            p["procs"] += 1
        self._prev = cur
        self._first = False
        self._last_scan = now

        with self.lock:
            self.scans += 1
            for pool, p in per_pool.items():
                a = self.acc.setdefault(pool, _new_acc())
                a["ticks"] += p["ticks"]
                a["mem_sum_kb"] += p["mem_kb"]
                a["mem_max_kb"] = max(a["mem_max_kb"], p["mem_kb"])
                a["procs_max"] = max(a["procs_max"], p["procs"])
            live = {}
            for pool, p in per_pool.items():
                cpu = 0.0
                if elapsed:
                    cpu = p["ticks"] / _CLK_TCK / elapsed / _NCPU * 100
                live[pool] = {"cpu_percent": round(cpu, 1),
                              "mem_mb": round(p["mem_kb"] / 1024, 1),
                              "procs": p["procs"]}
            self.live = live

    # ── log de FPM (saturaciones) ──────────────────────────────────────────
    def scan_logs(self):
        hits = {}
        for path in glob.glob(self.log_glob):
            try:
                st = os.stat(path)
            except OSError:
                continue
            inode, offset = self._log_pos.get(path, (None, None))
            if offset is None:
                # Primera vez: desde el final (lo de antes de arrancar no es de este bucket)
                self._log_pos[path] = (st.st_ino, st.st_size)
                continue
            if inode != st.st_ino or st.st_size < offset:
                offset = 0            # rotado o truncado
            if st.st_size == offset:
                self._log_pos[path] = (st.st_ino, offset)
                continue
            try:
                with open(path, "rb") as f:
                    f.seek(offset)
                    data = f.read(8 * 1024 * 1024)   # tope por si el log se disparó
                    offset = f.tell()
            except OSError:
                continue
            self._log_pos[path] = (st.st_ino, offset)
            for m in _HITS_RE.finditer(data.decode("utf-8", "replace")):
                hits[m.group(1)] = hits.get(m.group(1), 0) + 1
        if hits:
            with self.lock:
                for pool, n in hits.items():
                    self.acc.setdefault(pool, _new_acc())["hits"] += n

    # ── volcado a BD ───────────────────────────────────────────────────────
    def take_bucket(self):
        """Devuelve (acumulado, nº de pasadas) del bucket y empieza uno nuevo."""
        with self.lock:
            acc, scans = self.acc, self.scans
            self.acc, self.scans = {}, 0
        return acc, scans

    def flush(self, db, bucket_start: datetime) -> int:
        from api.models.models_domain import Domain
        from api.models.models_domain_resources import DomainResourceSample

        self.scan_logs()
        acc, scans = self.take_bucket()
        if not acc:
            return 0
        by_pool = {}
        for did, name in db.query(Domain.id, Domain.domain_name).all():
            by_pool.setdefault(pool_name(name), did)
        n = 0
        for pool, a in acc.items():
            did = by_pool.get(pool)
            if not did:
                continue
            if not (a["ticks"] or a["procs_max"] or a["hits"]):
                continue
            db.add(DomainResourceSample(
                domain_id=did, ts=bucket_start,
                cpu_seconds=round(a["ticks"] / _CLK_TCK, 2),
                mem_avg_mb=round(a["mem_sum_kb"] / max(1, scans) / 1024, 1),
                mem_max_mb=round(a["mem_max_kb"] / 1024, 1),
                procs_max=a["procs_max"], maxchildren_hits=a["hits"]))
            n += 1
        db.commit()
        return n

    def live_for(self, domain_name: str) -> dict:
        with self.lock:
            return dict(self.live.get(pool_name(domain_name))
                        or {"cpu_percent": 0.0, "mem_mb": 0.0, "procs": 0})


sampler = ResourceSampler()
_started = False
_start_lock = threading.Lock()


def purge_old(db) -> int:
    from api.models.models_domain_resources import DomainResourceSample
    cutoff = datetime.utcnow() - timedelta(days=RETENTION_DAYS)
    deleted = db.query(DomainResourceSample).filter(DomainResourceSample.ts < cutoff).delete()
    db.commit()
    return deleted


def _loop():
    from api.models.database import SessionLocal

    logger.info("Consumo por dominio: muestreador iniciado")
    bucket = int(time.time() // FLUSH_SECONDS)
    last_purge = 0.0
    sampler.scan_logs()       # fija el final de los logs como punto de partida
    while True:
        try:
            sampler.scan()
        except Exception:
            logger.exception("domain-resources: error en la pasada")
        now_bucket = int(time.time() // FLUSH_SECONDS)
        if now_bucket != bucket:
            start = datetime.utcfromtimestamp(bucket * FLUSH_SECONDS)
            bucket = now_bucket
            db = SessionLocal()
            try:
                sampler.flush(db, start)
                if time.monotonic() - last_purge >= 3600:
                    last_purge = time.monotonic()
                    purge_old(db)
            except Exception:
                db.rollback()
                logger.exception("domain-resources: error al guardar")
            finally:
                db.close()
        time.sleep(SCAN_SECONDS)


def start_domain_resources_sampler():
    """Arranca el hilo (idempotente). Solo en Linux (necesita /proc)."""
    global _started
    if not os.path.isdir("/proc/self"):
        return
    with _start_lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, daemon=True, name="domain-resources").start()
