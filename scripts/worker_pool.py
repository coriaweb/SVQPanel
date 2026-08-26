"""Cuántas tareas pesadas puede correr este servidor a la vez.

El número de workers NO puede ser fijo: el panel corre desde VPS de 2 cores
hasta máquinas de 16, y un valor hardcodeado sería malo en los dos extremos.
Tampoco basta con `nproc`:

- En contenedores y VPS con cgroups, `nproc` reporta los cores del HOST aunque
  la máquina solo tenga 2 asignados. Hay que mirar el límite del cgroup.
- La RAM manda tanto como la CPU: un dump de una BD de 400 MB ocupa memoria, y
  en un servidor con 4 GB libres no se pueden lanzar 8 a la vez.
- Si la máquina ya está cargada (webs de clientes sirviendo), el backup debe
  apartarse, no competir.

Todo esto se mide en arranque; el admin puede forzar un valor si lo necesita.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Techo de seguridad. Más allá de esto el cuello de botella deja de ser la CPU
# (pasa a ser el disco o el destino remoto) y solo se gana contención.
MAX_WORKERS = 4

# RAM estimada por worker. Un dump grande (la BD mayor aquí son 1,5 GB) se
# escribe en streaming, pero mariadb-dump + restic + buffers piden su espacio.
RAM_PER_WORKER_MB = 768


def _cpu_count_real() -> int:
    """Cores realmente disponibles, respetando los límites del cgroup.

    `os.cpu_count()` devuelve los del host. En un VPS con cgroups eso puede ser
    16 cuando en realidad hay 2, y lanzaríamos 8 veces más trabajo del que cabe.
    """
    total = os.cpu_count() or 1

    # cgroup v2: "max 100000" (sin límite) o "200000 100000" (= 2 cores)
    try:
        with open("/sys/fs/cgroup/cpu.max") as fh:
            quota_s, period_s = fh.read().split()
        if quota_s != "max":
            cores = int(quota_s) / int(period_s)
            if cores >= 0.5:
                return max(1, min(total, int(cores)))
    except (OSError, ValueError):
        pass

    # cgroup v1
    try:
        with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us") as fh:
            quota = int(fh.read().strip())
        with open("/sys/fs/cgroup/cpu/cpu.cfs_period_us") as fh:
            period = int(fh.read().strip())
        if quota > 0 and period > 0:
            cores = quota / period
            if cores >= 0.5:
                return max(1, min(total, int(cores)))
    except (OSError, ValueError):
        pass

    return total


def _mem_available_mb() -> Optional[int]:
    """RAM disponible de verdad (MemAvailable, no MemFree).

    MemFree engaña: el caché de página cuenta como "usado" pero es reclamable.
    MemAvailable es la estimación del propio kernel de lo que se puede pedir.
    """
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def _loadavg() -> Optional[float]:
    try:
        return os.getloadavg()[0]
    except (OSError, AttributeError):
        return None


def resolve_workers(configured: Optional[int] = None, *, reserve_cpu: bool = True) -> int:
    """Workers a usar. `configured` (del job) manda si viene con valor válido.

    Sin valor configurado se calcula por el mínimo de: cores libres, RAM que da
    de sí, y el techo de seguridad. Siempre >= 1: con 1 worker el
    comportamiento es el de siempre (secuencial).
    """
    if configured and configured > 0:
        return max(1, min(int(configured), 32))

    cores = _cpu_count_real()
    # Dejar un core al sistema: el backup no debe monopolizar la máquina
    # mientras las webs de los clientes están sirviendo.
    limit = cores - 1 if (reserve_cpu and cores > 1) else cores

    mem_mb = _mem_available_mb()
    if mem_mb:
        by_ram = mem_mb // RAM_PER_WORKER_MB
        limit = min(limit, by_ram)

    # Si la máquina ya viene cargada, no echar más leña.
    load = _loadavg()
    if load is not None and cores:
        libres = cores - load
        if libres < 1:
            limit = 1
        else:
            limit = min(limit, int(libres) or 1)

    workers = max(1, min(limit, MAX_WORKERS))
    logger.info(
        "Workers de backup: %d (cores=%d, ram_disp=%sMB, load=%s)",
        workers, cores, mem_mb, f"{load:.2f}" if load is not None else "?",
    )
    return workers


def run_tasks(job_config: dict, tareas: list, workers: int) -> list:
    """Ejecuta las copias de varios dominios, en paralelo si procede.

    Vive aquí —y no en cada llamador— porque el backup programado y el manual
    son dos caminos distintos hacia lo mismo: cuando la agregación estaba
    duplicada, un bug (una copia con BBDD sin volcar marcada "Correcto") hubo
    que arreglarlo en dos sitios. Cada `tarea` es un dict con username,
    domain_name, files_path, mail_path y databases; ya resueltos por el
    llamador, porque tocar la sesión de SQLAlchemy desde varios hilos no es
    seguro.

    Devuelve [(domain_name, resultado), ...] en el mismo orden de entrada, para
    que el log sea comparable entre ejecuciones aunque el paralelo termine
    desordenado.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from scripts import restic_manager

    def _una(t):
        return t["domain_name"], restic_manager.run_backup(
            job_config, t["username"], t["domain_name"],
            files_path=t["files_path"], mail_path=t["mail_path"],
            databases=t["databases"],
        )

    if workers <= 1 or len(tareas) <= 1:
        return [_una(t) for t in tareas]

    resultados = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futuros = {pool.submit(_una, t): t for t in tareas}
        for fut in as_completed(futuros):
            t = futuros[fut]
            try:
                resultados.append(fut.result())
            except Exception as exc:  # noqa: BLE001
                # Un dominio que revienta no debe tumbar la copia de los demás.
                logger.exception("Fallo en backup de %s", t["domain_name"])
                resultados.append((t["domain_name"], {
                    "status": "failed", "error": str(exc), "log": [],
                    "size_bytes": 0, "files_total": 0, "db_count": 0,
                    "failed_dumps": [], "repo": None,
                }))

    orden = {t["domain_name"]: i for i, t in enumerate(tareas)}
    resultados.sort(key=lambda r: orden.get(r[0], 0))
    return resultados


def describe() -> dict:
    """Datos crudos para mostrar en el panel por qué salió ese número."""
    cores = _cpu_count_real()
    return {
        "cpu_total": os.cpu_count() or 1,
        "cpu_usable": cores,
        "mem_available_mb": _mem_available_mb(),
        "loadavg": _loadavg(),
        "auto_workers": resolve_workers(),
        "max_workers": MAX_WORKERS,
    }
