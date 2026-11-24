"""
Workers de cola de Laravel como servicios systemd (uno por worker y dominio).

Sustituye al cron de cada minuto (`queue:work --stop-when-empty`) cuando la web
necesita que los trabajos salgan al momento: un `php artisan queue:work`
permanente, vigilado por systemd.

Cada worker es una unidad propia generada por el panel bajo demanda (igual que
los pools PHP-FPM), así que no hace falta instalar nada en el servidor:

    /etc/systemd/system/svqpanel-laravel-{dominio}-{n}.service

  - User=el usuario del dominio, con el PHP del dominio (nunca root).
  - MemoryMax (memoria del worker + margen) y CPUQuota=100 % (un núcleo como
    mucho), Nice=10: un worker desbocado no se come el servidor.
  - Restart=always: si se cae (o sale por --max-time / queue:restart) vuelve a
    arrancar a los 5 s. Si falla 10 veces en 5 min, systemd lo da por roto
    (estado «failed») y la UI lo muestra en vez de reintentar sin fin.
  - La salida va al journal (no a un fichero del cliente: systemd lo abriría
    como root y un symlink plantado le haría escribir donde no debe).

La configuración vive en Domain.laravel_queue (JSON) y es la fuente de verdad:
reconcile() vuelve a crear/borrar las unidades a partir de ella al arrancar el
panel (servidor migrado o restaurado, dominios borrados…).
"""

import glob
import json
import logging
import os
import pwd
import re
import subprocess
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

UNIT_DIR = "/etc/systemd/system"
UNIT_PREFIX = "svqpanel-laravel-"

# Límites para clientes (el admin tiene los suyos, más altos).
MAX_WORKERS_CLIENT = 2          # por dominio
MAX_WORKERS_USER_CLIENT = 4     # por cliente, sumando todos sus dominios
MAX_WORKERS_ADMIN = 8
MEMORY_OPTIONS = (128, 256, 512, 1024)
MAX_MEMORY_CLIENT = 512
TIMEOUT_OPTIONS = (60, 120, 300, 600)

DEFAULTS = {"workers": 0, "queue": "default", "connection": "",
            "memory": 256, "timeout": 60, "tries": 3}

# \Z y no $: en Python $ admite un "\n" final, y aquí todo acaba dentro de una
# unidad systemd (un salto de línea colaría una directiva nueva).
_QUEUE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,60}(,[A-Za-z0-9_.:-]{1,60}){0,9}\Z")
_CONN_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}\Z")
_PATH_RE = re.compile(r"^/[A-Za-z0-9_./-]+\Z")
_DOMAIN_RE = re.compile(r"^[a-z0-9.-]{1,200}\Z")


class WorkerError(RuntimeError):
    """Error legible (el endpoint lo da como 4xx)."""


def _systemctl(*args, timeout: int = 60):
    try:
        r = subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout tras {timeout}s"
    except Exception as e:  # noqa: BLE001
        return -1, "", str(e)


# ─────────────────────────────────────────────────────────────────────────────
# Configuración
# ─────────────────────────────────────────────────────────────────────────────
def get_config(domain) -> Dict:
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(getattr(domain, "laravel_queue", None) or "{}"))
    except (ValueError, TypeError):
        pass
    return cfg


def validate_config(data: Dict, is_admin: bool, other_workers: int) -> Dict:
    """Normaliza y valida lo que manda la UI. other_workers = workers que el
    cliente ya tiene en sus OTROS dominios (para el límite por cliente)."""
    cfg = dict(DEFAULTS)
    try:
        cfg["workers"] = int(data.get("workers", 0))
        cfg["memory"] = int(data.get("memory", 256))
        cfg["timeout"] = int(data.get("timeout", 60))
        cfg["tries"] = int(data.get("tries", 3))
    except (TypeError, ValueError):
        raise WorkerError("Valores numéricos no válidos")
    cfg["queue"] = (data.get("queue") or "default").strip().replace(" ", "")
    cfg["connection"] = (data.get("connection") or "").strip()

    max_w = MAX_WORKERS_ADMIN if is_admin else MAX_WORKERS_CLIENT
    if not 0 <= cfg["workers"] <= max_w:
        raise WorkerError(f"Número de workers entre 0 y {max_w}")
    if not is_admin and cfg["workers"] and other_workers + cfg["workers"] > MAX_WORKERS_USER_CLIENT:
        raise WorkerError(f"Máximo {MAX_WORKERS_USER_CLIENT} workers por cliente entre todos "
                          f"sus dominios (ya tienes {other_workers} en otros).")
    if cfg["memory"] not in MEMORY_OPTIONS or (not is_admin and cfg["memory"] > MAX_MEMORY_CLIENT):
        raise WorkerError("Memoria por worker no permitida")
    if cfg["timeout"] not in TIMEOUT_OPTIONS:
        raise WorkerError("Tiempo máximo por trabajo no permitido")
    if not 1 <= cfg["tries"] <= 10:
        raise WorkerError("Reintentos entre 1 y 10")
    if not _QUEUE_RE.match(cfg["queue"]):
        raise WorkerError("Nombre de cola no válido (p. ej. «default» o «high,default»)")
    if cfg["connection"] and not _CONN_RE.match(cfg["connection"]):
        raise WorkerError("Nombre de conexión no válido")
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# Unidades
# ─────────────────────────────────────────────────────────────────────────────
def unit_name(domain_name: str, n: int) -> str:
    return f"{UNIT_PREFIX}{domain_name}-{n}.service"


def existing_units(domain_name: str) -> List[str]:
    """Unidades instaladas de un dominio (por el fichero, ordenadas por nº)."""
    pat = os.path.join(UNIT_DIR, f"{UNIT_PREFIX}{glob.escape(domain_name)}-*.service")
    rx = re.compile(rf"^{re.escape(UNIT_PREFIX + domain_name)}-(\d+)\.service$")
    out = []
    for p in glob.glob(pat):
        m = rx.match(os.path.basename(p))
        if m:
            out.append((int(m.group(1)), os.path.basename(p)))
    return [u for _, u in sorted(out)]


def render_unit(domain_name: str, n: int, owner: str, root: str, php: str, cfg: Dict) -> str:
    if not _DOMAIN_RE.match(domain_name):
        raise WorkerError("Nombre de dominio no válido para una unidad")
    if not _PATH_RE.match(root) or ".." in root or not _PATH_RE.match(php):
        raise WorkerError("La ruta del proyecto tiene caracteres no admitidos (espacios…)")
    try:
        pw = pwd.getpwnam(owner)
    except KeyError:
        raise WorkerError(f"El usuario {owner} no existe en el sistema")
    args = ["queue:work"]
    if cfg.get("connection"):
        args.append(cfg["connection"])
    args += [f"--queue={cfg['queue']}", "--sleep=3", f"--tries={cfg['tries']}",
             f"--timeout={cfg['timeout']}", f"--memory={cfg['memory']}",
             "--max-time=3600", "--no-interaction"]
    # Margen sobre --memory: Laravel sale limpio al pasarlo (entre trabajos);
    # MemoryMax es la red de seguridad para un trabajo que se dispara.
    mem_max = cfg["memory"] + max(64, cfg["memory"] // 2)
    return f"""# Generado por SVQPanel — no editar (se regenera). Ver scripts/laravel_workers.py
[Unit]
Description=SVQPanel: cola Laravel de {domain_name} (worker {n})
After=network-online.target mariadb.service redis-server.service
StartLimitIntervalSec=300
StartLimitBurst=10

[Service]
Type=simple
User={owner}
Group={pw.pw_gid}
WorkingDirectory={root}
Environment=HOME={pw.pw_dir}
ExecStart={php} {root}/artisan {' '.join(args)}
Restart=always
RestartSec=5
TimeoutStopSec={cfg['timeout'] + 15}
MemoryMax={mem_max}M
CPUQuota=100%
Nice=10
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
SyslogIdentifier=laravel-queue-{domain_name}

[Install]
WantedBy=multi-user.target
"""


def _php_for(php_version: Optional[str]) -> str:
    from scripts.composer_manager import php_bin_for
    return php_bin_for(php_version) or "/usr/bin/php"


def remove_units(domain_name: str, keep: int = 0) -> List[str]:
    """Para y borra las unidades del dominio con nº > keep. Devuelve las quitadas."""
    removed = []
    for u in existing_units(domain_name):
        n = int(u[len(UNIT_PREFIX + domain_name) + 1:-len(".service")])
        if n <= keep:
            continue
        _systemctl("disable", "--now", u, timeout=120)
        try:
            os.remove(os.path.join(UNIT_DIR, u))
        except OSError:
            pass
        _systemctl("reset-failed", u)
        removed.append(u)
    if removed:
        _systemctl("daemon-reload")
    return removed


def apply(domain_name: str, owner: str, root: Optional[str], php_version: Optional[str],
          cfg: Dict, start: bool = True) -> Dict:
    """Deja instaladas exactamente cfg['workers'] unidades (y arrancadas si start).
    Reescribe solo las que cambian; las que sobran se paran y borran."""
    n_workers = int(cfg.get("workers") or 0)
    if n_workers <= 0 or not root:
        removed = remove_units(domain_name, keep=0)
        return {"changed": bool(removed), "units": []}
    php = _php_for(php_version)
    changed_units = []
    units = []
    for n in range(1, n_workers + 1):
        name = unit_name(domain_name, n)
        path = os.path.join(UNIT_DIR, name)
        content = render_unit(domain_name, n, owner, root, php, cfg)
        try:
            with open(path, encoding="utf-8") as f:
                same = f.read() == content
        except OSError:
            same = False
        if not same:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            changed_units.append(name)
        units.append(name)
    removed = remove_units(domain_name, keep=n_workers)
    if changed_units:
        _systemctl("daemon-reload")
    if start:
        for u in units:
            _systemctl("enable", u)
            if u in changed_units:
                _systemctl("reset-failed", u)
                _systemctl("restart", u, timeout=120)
            else:
                _systemctl("start", u, timeout=120)
    return {"changed": bool(changed_units or removed), "units": units}


def control(domain_name: str, op: str) -> Dict:
    if op not in ("start", "stop", "restart"):
        raise WorkerError("Operación no soportada")
    units = existing_units(domain_name)
    if not units:
        raise WorkerError("Este dominio no tiene workers configurados")
    errors = []
    for u in units:
        if op != "stop":
            _systemctl("reset-failed", u)
        rc, _, err = _systemctl(op, u, timeout=120)
        if rc != 0:
            errors.append(f"{u}: {err}")
    if errors:
        raise WorkerError("\n".join(errors))
    return {"ok": True, "output": {"start": "Workers arrancados.", "stop": "Workers parados.",
                                   "restart": "Workers reiniciados."}[op]}


def status(domain_name: str) -> List[Dict]:
    out = []
    for u in existing_units(domain_name):
        rc, txt, _ = _systemctl("show", u, "-p", "ActiveState", "-p", "SubState", "-p", "NRestarts",
                                "-p", "MemoryCurrent", "-p", "ActiveEnterTimestamp",
                                "-p", "MainPID", "-p", "UnitFileState", "-p", "Result")
        props = dict(line.split("=", 1) for line in txt.splitlines() if "=" in line)
        mem = props.get("MemoryCurrent", "")
        out.append({
            "unit": u,
            "active": props.get("ActiveState", "unknown"),
            "sub": props.get("SubState", ""),
            "result": props.get("Result", ""),
            "enabled": props.get("UnitFileState", "") == "enabled",
            "restarts": int(props.get("NRestarts") or 0) if (props.get("NRestarts") or "").isdigit() else 0,
            "memory_mb": round(int(mem) / 1048576, 1) if mem.isdigit() else None,
            "since": props.get("ActiveEnterTimestamp", ""),
            "pid": int(props.get("MainPID") or 0) if (props.get("MainPID") or "").isdigit() else 0,
        })
    return out


def logs(domain_name: str, lines: int = 200) -> str:
    units = existing_units(domain_name)
    if not units:
        return ""
    lines = max(20, min(int(lines or 200), 2000))
    cmd = ["journalctl", "--no-pager", "-o", "short-iso", "-n", str(lines)]
    for u in units:
        cmd += ["-u", u]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return (r.stdout or "")[-200_000:]
    except Exception as e:  # noqa: BLE001
        return f"No se pudo leer el journal: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# Ciclo de vida (suspender / borrar / cambiar PHP / arranque del panel)
# ─────────────────────────────────────────────────────────────────────────────
def stop_domain(domain_name: str) -> None:
    """Suspensión: para los workers sin borrarlos (ni deshabilitarlos del todo:
    se deshabilitan para que un reinicio del servidor no los levante)."""
    for u in existing_units(domain_name):
        _systemctl("disable", "--now", u, timeout=120)


def start_domain(domain_name: str) -> None:
    for u in existing_units(domain_name):
        _systemctl("reset-failed", u)
        _systemctl("enable", "--now", u, timeout=120)


def domain_root_for(domain, owner: str) -> Optional[str]:
    from scripts.utils import get_domain_root
    from scripts.laravel_manager import find_root
    droot = get_domain_root(owner, domain.domain_name)
    docroot = domain.custom_docroot or droot + "/public_html"
    return find_root(droot, docroot)


def sync_domain(domain, db, owner: Optional[str] = None) -> bool:
    """Reescribe las unidades del dominio desde su config (p. ej. tras cambiar
    el PHP). No lanza."""
    try:
        cfg = get_config(domain)
        if not cfg.get("workers") and not existing_units(domain.domain_name):
            return False
        if not owner:
            from api.models.models_user import User
            u = db.query(User).filter(User.id == domain.user_id).first()
            owner = u.username if u else None
        if not owner:
            return False
        root = domain_root_for(domain, owner)
        suspended = bool(getattr(domain, "is_suspended", False))
        res = apply(domain.domain_name, owner, root, domain.php_version, cfg, start=not suspended)
        if suspended:
            stop_domain(domain.domain_name)
        return res["changed"]
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Workers Laravel de {getattr(domain, 'domain_name', '?')}: {e}")
        return False


def reconcile(db) -> Dict:
    """Al arrancar el panel: crea las unidades que faltan según la BD y borra
    las de dominios que ya no existen o no tienen workers."""
    from api.models.models_domain import Domain
    report = {"synced": 0, "orphans": 0}
    wanted = set()
    for d in db.query(Domain).filter(Domain.laravel_queue.isnot(None)).all():
        if get_config(d).get("workers"):
            wanted.add(d.domain_name)
            if sync_domain(d, db):
                report["synced"] += 1
    for p in glob.glob(os.path.join(UNIT_DIR, f"{UNIT_PREFIX}*.service")):
        m = re.match(rf"^{re.escape(UNIT_PREFIX)}(.+)-\d+\.service$", os.path.basename(p))
        if m and m.group(1) not in wanted:
            remove_units(m.group(1), keep=0)
            report["orphans"] += 1
    return report


def start_reconcile_thread() -> None:
    """reconcile() en un hilo aparte: el arranque del panel no espera a systemd."""
    import threading

    def _run():
        try:
            from api.models.database import SessionLocal
            db = SessionLocal()
            try:
                r = reconcile(db)
                if r["synced"] or r["orphans"]:
                    logger.info(f"Workers Laravel reconciliados: {r}")
            finally:
                db.close()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Reconciliación de workers Laravel: {e}")

    threading.Thread(target=_run, name="laravel-workers-reconcile", daemon=True).start()
