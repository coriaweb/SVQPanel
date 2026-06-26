"""
Ejecutor de cronjobs con registro de historial — diseño SEGURO (cola en disco).

El wrapper (svq-cron-run) corre como el USUARIO DEL CLIENTE. Por seguridad NO
toca la BD, ni la red, ni sudo: solo ejecuta el comando y deja un .json con el
resultado en la cola /var/lib/svqpanel/cron-runs/ (carpeta 1733: los clientes
pueden CREAR ficheros pero no listar/leer/borrar los de otros — cero escalada).

El panel (root, con acceso a BD) ingiere esos .json desde un hilo interno:
valida que el cron pertenece al dueño del fichero, guarda en cron_runs, poda a
las últimas KEEP_RUNS y borra el .json. "Ejecutar ahora" (endpoint, ya como root)
escribe directo en BD sin pasar por la cola.
"""

import json
import logging
import os
import subprocess
import time
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

QUEUE_DIR = "/var/lib/svqpanel/cron-runs"
KEEP_RUNS = 5          # ejecuciones que se conservan por cron
OUTPUT_CAP = 8000      # bytes de salida guardados
DEFAULT_TIMEOUT = 3600  # 1h para crons automáticos


# ── Lado WRAPPER (corre como el cliente): solo ejecuta y encola ──────────────
def run_and_queue(cron_id: int, command: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Ejecuta el comando, mide, y deja el resultado en la cola en disco.
    Devuelve {exit_code, duration_ms, output}. No escribe en BD."""
    env = {**os.environ,
           "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}
    started = datetime.utcnow()
    t0 = time.monotonic()
    try:
        proc = subprocess.run(["/bin/bash", "-lc", command],
                              capture_output=True, text=True,
                              timeout=timeout, env=env)
        exit_code = proc.returncode
        output = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    except subprocess.TimeoutExpired:
        exit_code = 124
        output = f"[svq-cron] La tarea superó el límite de {timeout}s y se canceló."
    except Exception as e:
        exit_code = 127
        output = f"[svq-cron] No se pudo ejecutar: {e}"
    duration_ms = int((time.monotonic() - t0) * 1000)

    _enqueue(cron_id, started, duration_ms, exit_code, output)
    return {"exit_code": exit_code, "duration_ms": duration_ms,
            "output": output.strip()[:OUTPUT_CAP]}


def _enqueue(cron_id, started, duration_ms, exit_code, output):
    """Deja un .json en la cola. Best-effort: nunca rompe la ejecución del cron."""
    try:
        if not os.path.isdir(QUEUE_DIR):
            return  # sin cola instalada (compat): no registramos, no fallamos
        payload = {
            "cron_id": int(cron_id),
            "started_at": started.isoformat(),
            "duration_ms": int(duration_ms),
            "exit_code": int(exit_code) if exit_code is not None else None,
            "output": (output or "")[:OUTPUT_CAP],
        }
        fname = f"{int(cron_id)}.{int(time.time())}.{uuid.uuid4().hex[:8]}.json"
        path = os.path.join(QUEUE_DIR, fname)
        # O_CREAT|O_EXCL: no pisar; 0600 para que solo el dueño lo lea.
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f)
    except Exception as e:
        logger.warning(f"cron_run no encolado (cron {cron_id}): {e}")


# ── Lado PANEL (root, con BD): ingiere la cola y guarda en cron_runs ─────────
def _write_run(db, cron_id, started_at, duration_ms, exit_code, output, trigger,
               owner_uid=None):
    """Inserta en cron_runs validando propiedad, actualiza last_run y poda."""
    from api.models.models_cron import CronJob
    from api.models.models_cron_run import CronRun

    cj = db.query(CronJob).filter(CronJob.id == cron_id).first()
    if not cj:
        return False
    # Seguridad: si viene de la cola (owner_uid), el cron debe pertenecer al
    # usuario del sistema que escribió el fichero (un cliente no registra crons
    # de otro). Se valida en el ingestor antes de llamar aquí.
    run = CronRun(cron_id=cron_id, started_at=started_at,
                  finished_at=datetime.utcnow(), duration_ms=duration_ms,
                  exit_code=exit_code, output=(output or "")[:OUTPUT_CAP],
                  trigger=trigger)
    db.add(run)
    cj.last_run = datetime.utcnow()
    db.commit()
    ids = [r.id for r in db.query(CronRun.id)
           .filter(CronRun.cron_id == cron_id)
           .order_by(CronRun.started_at.desc()).all()]
    if len(ids) > KEEP_RUNS:
        db.query(CronRun).filter(CronRun.id.in_(ids[KEEP_RUNS:])).delete(
            synchronize_session=False)
        db.commit()
    return True


def ingest_queue() -> int:
    """Procesa los .json de la cola: valida propiedad, guarda en BD y borra.
    Devuelve el nº de ejecuciones ingeridas. Pensado para un hilo interno."""
    if not os.path.isdir(QUEUE_DIR):
        return 0
    from api.models.database import SessionLocal, load_all_models
    from api.models.models_cron import CronJob
    from api.models.models_user import User
    load_all_models()

    n = 0
    db = SessionLocal()
    try:
        for fname in sorted(os.listdir(QUEUE_DIR)):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(QUEUE_DIR, fname)
            try:
                st = os.stat(path)
                with open(path) as f:
                    data = json.load(f)
                cron_id = int(data.get("cron_id"))
                # Validación de propiedad: el UID que creó el fichero debe ser el
                # usuario de sistema del dueño del cron (evita falsear historiales
                # de otros). Se resuelve por username del owner.
                cj = db.query(CronJob).filter(CronJob.id == cron_id).first()
                if not cj:
                    os.remove(path)  # cron borrado: descartar
                    continue
                owner = db.query(User).filter(User.id == cj.user_id).first()
                expected_uid = _username_uid(owner.username) if owner else None
                if expected_uid is not None and st.st_uid != 0 and st.st_uid != expected_uid:
                    logger.warning(f"cron-run descartado: uid {st.st_uid} no es dueño del cron {cron_id}")
                    os.remove(path)
                    continue
                started = datetime.fromisoformat(data["started_at"])
                _write_run(db, cron_id, started, data.get("duration_ms"),
                           data.get("exit_code"), data.get("output"), "auto")
                os.remove(path)
                n += 1
            except Exception as e:
                logger.warning(f"cron-run {fname} no ingerido: {e}")
                # Fichero corrupto/antiguo: si tiene >1 día, borrar.
                try:
                    if time.time() - os.path.getmtime(path) > 86400:
                        os.remove(path)
                except OSError:
                    pass
    finally:
        db.close()
    return n


def _username_uid(username: str):
    try:
        import pwd
        return pwd.getpwnam(username).pw_uid
    except Exception:
        return None


def record_manual_run(db, cron_id: int, command: str, run_as: str,
                      timeout: int = 120) -> dict:
    """'Ejecutar ahora' (endpoint, ya como root): ejecuta como el usuario y
    escribe el historial directo en BD (sin cola). trigger='manual'."""
    env = {**os.environ,
           "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}
    started = datetime.utcnow()
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            ["runuser", "-u", run_as, "--", "/bin/bash", "-lc", command],
            capture_output=True, text=True, timeout=timeout, env=env)
        exit_code = proc.returncode
        output = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    except subprocess.TimeoutExpired:
        exit_code = 124
        output = f"[svq-cron] La tarea superó el límite de {timeout}s y se canceló."
    duration_ms = int((time.monotonic() - t0) * 1000)
    _write_run(db, cron_id, started, duration_ms, exit_code, output, "manual")
    return {"exit_code": exit_code, "duration_ms": duration_ms,
            "output": output.strip()[:OUTPUT_CAP]}
