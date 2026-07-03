"""
Actualizaciones seguras de WordPress con checkpoint y rollback automático
(estilo "Smart Updates" del WP Toolkit de Plesk).

Flujo de una actualización segura (manual o automática):
  1. Sonda de salud ANTES: `wp eval` cargando plugins (detecta PHP fatal) +
     petición HTTP por el stack local con query-string aleatoria (cualquier
     query activa $skip_cache en el vhost, así la sonda llega SIEMPRE a PHP
     aunque la caché de página sirviera 200 rancios con use_stale).
  2. Checkpoint: tar del docroot + mysqldump de la BD del wp-config en
     /var/lib/svqpanel/wp-checkpoints/{dominio}/{stamp}/ (se conservan 2).
  3. Actualizar core (+ core update-db), plugins y temas con wp-cli, como el
     usuario del dominio y con el PHP del dominio (php{version}, nunca el del
     sistema — un sitio en 7.4 revienta con el 8.x del sistema).
  4. Sonda DESPUÉS y comparación: solo cuenta la rotura NUEVA (antes OK →
     ahora fatal/5xx). Un sitio que YA daba error crítico en wp-cli antes de
     actualizar (plugins viejos en PHP 7.4) no dispara rollback por ese
     síntoma preexistente.
  5. Si se rompió: rollback automático (rsync --delete desde el tar + import
     del dump). Mismo dominio y misma URL → no hace falta search-replace.

Cada ejecución queda registrada en la tabla wp_update_runs (WpUpdateRun) con
qué se actualizó, las sondas antes/después y si hubo rollback.

Modo automático: Domain.wp_auto_update=True + hilo programador dentro del
panel (como backup_scheduler) que cada madrugada (04:30 hora del panel)
recorre los dominios con el toggle y les aplica este mismo flujo en serie.
No puede ser un CronJob por dominio: esos corren en el crontab del usuario
sin privilegios, y el checkpoint necesita mysqldump admin y escribir en
/var/lib/svqpanel.

Reutiliza los helpers del staging (wp_staging): _wp con PHP del dominio,
_dump_db/_import_db, _sync_files.
"""

import json
import logging
import os
import secrets
import shutil
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional

from scripts.app_installer import _run
from scripts.wp_staging import (_wp, _wp_config_get, _dump_db, _import_db,
                                _sync_files, StagingError)

logger = logging.getLogger(__name__)


class SafeUpdateError(RuntimeError):
    """Error legible de una actualización segura (el endpoint lo da como 4xx)."""


CHECKPOINT_DIR = "/var/lib/svqpanel/wp-checkpoints"
KEEP_CHECKPOINTS = 2

# Hora local (zona del panel) del pase automático nocturno. A las 04:30: el
# update del panel corre a las 03:00 y así no se pisan.
AUTO_HOUR = 4
AUTO_MINUTE = 30

STEPS = [
    "Comprobando el estado del sitio",
    "Creando el punto de restauración",
    "Actualizando WordPress",
    "Verificando el sitio",
    "Limpiando cachés",
]


# ─────────────────────────────────────────────────────────────────────────────
# Registro de jobs en memoria (mismo patrón que wp_staging: el estado
# persistente vive en la tabla wp_update_runs; esto solo refleja la operación
# en curso para el polling de la UI).
# ─────────────────────────────────────────────────────────────────────────────
_JOBS: Dict[int, Dict] = {}
_JOBS_LOCK = threading.Lock()


def _job_init(domain_id: int, steps: List[str]) -> None:
    with _JOBS_LOCK:
        _JOBS[domain_id] = {
            "op": "safe-update", "status": "running", "steps": steps,
            "current": 0, "error": None, "rolled_back": False,
            "started_at": datetime.utcnow().isoformat(), "finished_at": None,
        }


def _job_step(domain_id: int, idx: int) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(domain_id)
        if job:
            job["current"] = idx


def _job_end(domain_id: int, error: Optional[str] = None,
             rolled_back: bool = False) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(domain_id)
        if job:
            job["status"] = "failed" if error else "success"
            job["error"] = error
            job["rolled_back"] = rolled_back
            job["finished_at"] = datetime.utcnow().isoformat()


def job_status(domain_id: int) -> Optional[Dict]:
    with _JOBS_LOCK:
        job = _JOBS.get(domain_id)
        return dict(job) if job else None


def job_running(domain_id: int) -> bool:
    job = job_status(domain_id)
    return bool(job and job["status"] == "running")


# ─────────────────────────────────────────────────────────────────────────────
# Sonda de salud (comparable antes/después)
# ─────────────────────────────────────────────────────────────────────────────
def probe_health(docroot: str, owner: str, php_version: Optional[str],
                 domain_name: str, ssl_enabled: bool) -> Dict:
    """
    Dos señales independientes:
      - wp_ok:   `wp eval 'echo SVQ_OK'` CARGANDO plugins/temas. Si un plugin
                 tiene un fatal, wp-cli devuelve rc!=0 → detección determinista
                 sin depender de HTTP ni cachés.
      - http_ok: GET a la home por el stack local (--resolve → 127.0.0.1, no
                 pasa por Cloudflare/DNS) con ?svqpanel=<token>: la query
                 activa $skip_cache en el vhost → llega a PHP sí o sí.
                 Se considera roto solo el 5xx (o no responder); un 401/403/404
                 sigue siendo "PHP responde".
    """
    rc, out, err = _wp(docroot, owner, ["eval", 'echo "SVQ_OK";'],
                       php_version, timeout=180)
    wp_ok = (rc == 0 and "SVQ_OK" in (out or ""))

    scheme = "https" if ssl_enabled else "http"
    token = secrets.token_hex(8)
    url = f"{scheme}://{domain_name}/?svqpanel={token}"
    rc2, code, _err2 = _run([
        "curl", "-k", "-s", "-o", "/dev/null", "-w", "%{http_code}",
        "-m", "30", "-L", "--max-redirs", "3",
        "--resolve", f"{domain_name}:443:127.0.0.1",
        "--resolve", f"{domain_name}:80:127.0.0.1",
        url,
    ], timeout=60)
    try:
        http_status = int((code or "0").strip())
    except ValueError:
        http_status = 0
    http_ok = 0 < http_status < 500

    return {
        "wp_ok": wp_ok,
        "wp_error": None if wp_ok else ((err or out or "")[-400:] or "wp-cli no respondió"),
        "http_status": http_status,
        "http_ok": http_ok,
    }


def _newly_broken(pre: Dict, post: Dict) -> Optional[str]:
    """Qué se ha roto POR el update (ignora lo que ya estaba roto antes)."""
    reasons = []
    if pre.get("wp_ok") and not post.get("wp_ok"):
        reasons.append(f"PHP fatal al cargar WordPress: {post.get('wp_error')}")
    if pre.get("http_ok") and not post.get("http_ok"):
        reasons.append(f"la web ha dejado de responder (HTTP {post.get('http_status')})")
    return "; ".join(reasons) or None


# ─────────────────────────────────────────────────────────────────────────────
# Checkpoint (tar + dump) y rollback
# ─────────────────────────────────────────────────────────────────────────────
def create_checkpoint(domain_name: str, docroot: str, db_name: str) -> str:
    """Crea el punto de restauración y devuelve su directorio."""
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    cdir = os.path.join(CHECKPOINT_DIR, domain_name, stamp)
    os.makedirs(cdir, mode=0o700, exist_ok=True)
    rc, _out, err = _run(["tar", "-czf", os.path.join(cdir, "files.tar.gz"),
                          "-C", docroot, "."], timeout=3600)
    if rc != 0:
        shutil.rmtree(cdir, ignore_errors=True)
        raise SafeUpdateError(f"No pude crear el checkpoint de archivos: {(err or '')[:300]}")
    sql = os.path.join(cdir, "database.sql")
    try:
        _dump_db(db_name, sql)
    except StagingError as e:
        shutil.rmtree(cdir, ignore_errors=True)
        raise SafeUpdateError(str(e))
    _run(["gzip", "-f", sql], timeout=1800)
    _prune_checkpoints(domain_name)
    return cdir


def remove_domain_checkpoints(domain_name: str) -> None:
    """Borra TODOS los checkpoints y backups pre-push de un dominio. Se llama
    al eliminar el dominio (DELETE /domains, purge de usuario, borrado de
    staging) para no dejar copias huérfanas en /var/lib/svqpanel."""
    from scripts.wp_staging import BACKUP_DIR as STAGING_BACKUP_DIR
    for base in (CHECKPOINT_DIR, STAGING_BACKUP_DIR):
        shutil.rmtree(os.path.join(base, domain_name), ignore_errors=True)


def _prune_checkpoints(domain_name: str) -> None:
    base = os.path.join(CHECKPOINT_DIR, domain_name)
    try:
        dirs = sorted(d for d in os.listdir(base)
                      if os.path.isdir(os.path.join(base, d)))
        for old in dirs[:-KEEP_CHECKPOINTS]:
            shutil.rmtree(os.path.join(base, old), ignore_errors=True)
    except FileNotFoundError:
        pass


def restore_checkpoint(checkpoint_dir: str, docroot: str, owner: str,
                       db_name: str) -> None:
    """
    Restaura archivos + BD desde el checkpoint. El tar se extrae a un temporal
    y se vuelca con rsync --delete: así desaparecen también los ficheros NUEVOS
    que dejó la actualización fallida (extraer encima los dejaría mezclados con
    los viejos y el sitio seguiría roto). Misma URL → sin search-replace.
    """
    tarball = os.path.join(checkpoint_dir, "files.tar.gz")
    dumpgz = os.path.join(checkpoint_dir, "database.sql.gz")
    if not os.path.exists(tarball) or not os.path.exists(dumpgz):
        raise SafeUpdateError("Checkpoint incompleto: no puedo restaurar.")

    tmp = os.path.join(checkpoint_dir, "restore-tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, mode=0o700)
    try:
        rc, _out, err = _run(["tar", "-xzf", tarball, "-C", tmp], timeout=3600)
        if rc != 0:
            raise SafeUpdateError(f"No pude extraer el checkpoint: {(err or '')[:300]}")
        _sync_files(tmp, docroot, owner, delete=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    sql = os.path.join(checkpoint_dir, "database.sql")
    rc, _out, err = _run(["gunzip", "-kf", dumpgz], timeout=1800)
    if rc != 0:
        raise SafeUpdateError(f"No pude descomprimir el dump: {(err or '')[:300]}")
    try:
        _import_db(db_name, sql)
    except StagingError as e:
        raise SafeUpdateError(str(e))
    finally:
        try:
            os.remove(sql)
        except OSError:
            pass


def _purge_page_cache(domain_name: str) -> None:
    """Vacía la caché de página nginx del dominio (best-effort)."""
    try:
        from scripts.utils import get_fastcgi_cache_dir
        cdir = get_fastcgi_cache_dir(domain_name)
        if cdir and os.path.isdir(cdir):
            for entry in os.listdir(cdir):
                p = os.path.join(cdir, entry)
                shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)
    except Exception as e:
        logger.info(f"Safe-update {domain_name}: purga de caché de página: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Inventario de actualizaciones (para el registro histórico)
# ─────────────────────────────────────────────────────────────────────────────
def _pending_updates(docroot: str, owner: str, php_version) -> Dict:
    """Qué hay pendiente ANTES de actualizar: core + plugins/temas con update."""
    pend = {"core": None, "plugins": [], "themes": []}
    rc, out, _ = _wp(docroot, owner, ["core", "check-update", "--format=json"],
                     php_version, skip_plugins=True)
    if rc == 0 and (out or "").strip() not in ("", "[]"):
        try:
            rows = json.loads(out)
            if rows:
                pend["core"] = rows[0].get("version")
        except (ValueError, TypeError):
            pass
    for kind, key in (("plugin", "plugins"), ("theme", "themes")):
        rc, out, _ = _wp(docroot, owner,
                         [kind, "list", "--update=available",
                          "--fields=name,version,update_version", "--format=json"],
                         php_version, skip_plugins=True)
        if rc == 0 and (out or "").strip():
            try:
                pend[key] = json.loads(out)
            except (ValueError, TypeError):
                pass
    return pend


# ─────────────────────────────────────────────────────────────────────────────
# Job principal
# ─────────────────────────────────────────────────────────────────────────────
def run_safe_update(domain_id: int, mode: str = "manual") -> None:
    """Job de fondo: checkpoint → update → verificación → rollback si procede.
    Registra el resultado en wp_update_runs pase lo que pase."""
    from api.models.database import SessionLocal, load_all_models
    load_all_models()
    db = SessionLocal()
    run = None
    try:
        from api.models.models_domain import Domain
        from api.models.models_user import User
        from api.models.models_wp_update import WpUpdateRun
        from scripts.utils import get_domain_root

        domain = db.query(Domain).filter(Domain.id == domain_id).first()
        if not domain:
            raise SafeUpdateError("Dominio no encontrado")
        owner = db.query(User).filter(User.id == domain.user_id).first()
        if not owner:
            raise SafeUpdateError("El dominio no tiene propietario")
        username = owner.username
        docroot = (domain.custom_docroot
                   or get_domain_root(username, domain.domain_name) + "/public_html")
        php_version = domain.php_version or "8.2"

        run = WpUpdateRun(domain_id=domain.id, mode=mode, status="running")
        db.add(run); db.commit(); db.refresh(run)

        _execute(db, run, domain, username, docroot, php_version)
        _job_end(domain_id, rolled_back=bool(run.rollback))
    except Exception as e:
        logger.exception(f"Safe-update: fallo en dominio {domain_id}")
        msg = str(e) if isinstance(e, (SafeUpdateError, StagingError)) \
            else f"Error inesperado: {e}"
        if run is not None:
            try:
                run.status = "rolled_back" if run.rollback else "failed"
                run.error = msg
                run.finished_at = datetime.utcnow()
                db.commit()
            except Exception:
                db.rollback()
        _job_end(domain_id, error=msg,
                 rolled_back=bool(run.rollback) if run is not None else False)
    finally:
        db.close()


def _execute(db, run, domain, username: str, docroot: str, php_version: str) -> None:
    domain_id = domain.id
    dname = domain.domain_name
    log: List[str] = []

    # ── 1. Sonda ANTES ───────────────────────────────────────────────────────
    _job_step(domain_id, 0)
    pre = probe_health(docroot, username, php_version, dname,
                       bool(domain.ssl_enabled))
    run.pre_health = json.dumps(pre)
    if not pre["wp_ok"]:
        log.append(f"AVISO: el sitio YA daba error en wp-cli antes de actualizar "
                   f"({pre['wp_error']}); ese síntoma preexistente no disparará rollback.")
    pending = _pending_updates(docroot, username, php_version)
    run.updated_items = json.dumps(pending)
    db.commit()
    if not pending["core"] and not pending["plugins"] and not pending["themes"]:
        run.status = "success"
        run.log = "No había actualizaciones pendientes."
        run.finished_at = datetime.utcnow()
        db.commit()
        return

    # ── 2. Checkpoint ────────────────────────────────────────────────────────
    _job_step(domain_id, 1)
    db_name = _wp_config_get(docroot, username, "DB_NAME", php_version)
    checkpoint = create_checkpoint(dname, docroot, db_name)
    run.checkpoint_path = checkpoint
    db.commit()
    log.append(f"Checkpoint: {checkpoint}")

    # ── 3. Actualizar (core → update-db → plugins → temas) ──────────────────
    _job_step(domain_id, 2)
    upd_errors = []
    if pending["core"]:
        rc, out, err = _wp(docroot, username, ["core", "update"],
                           php_version, timeout=900)
        log.append(f"core update → rc={rc} {out or err}".strip())
        if rc != 0:
            upd_errors.append(f"core: {(err or out)[:200]}")
        else:
            _wp(docroot, username, ["core", "update-db"], php_version, timeout=600)
    for kind, key in (("plugin", "plugins"), ("theme", "themes")):
        if not pending[key]:
            continue
        rc, out, err = _wp(docroot, username, [kind, "update", "--all"],
                           php_version, timeout=1800)
        log.append(f"{kind} update --all → rc={rc} {out or err}".strip())
        if rc != 0:
            upd_errors.append(f"{kind}s: {(err or out)[:200]}")

    # ── 4. Sonda DESPUÉS + comparación ───────────────────────────────────────
    _job_step(domain_id, 3)
    post = probe_health(docroot, username, php_version, dname,
                        bool(domain.ssl_enabled))
    run.post_health = json.dumps(post)
    broke = _newly_broken(pre, post)

    if broke:
        log.append(f"ROTURA detectada tras actualizar: {broke}. Restaurando checkpoint…")
        restore_checkpoint(checkpoint, docroot, username, db_name)
        run.rollback = True
        _wp(docroot, username, ["cache", "flush"], php_version)
        _purge_page_cache(dname)
        after = probe_health(docroot, username, php_version, dname,
                             bool(domain.ssl_enabled))
        log.append(f"Tras el rollback: wp_ok={after['wp_ok']} "
                   f"http={after['http_status']}")
        run.status = "rolled_back"
        run.error = broke
        run.log = "\n".join(log)[-8000:]
        run.finished_at = datetime.utcnow()
        db.commit()
        _notify_result(db, domain, run)
        return

    # ── 5. Cachés ────────────────────────────────────────────────────────────
    _job_step(domain_id, 4)
    _wp(docroot, username, ["cache", "flush"], php_version)
    _wp(docroot, username, ["rewrite", "flush"], php_version)
    _purge_page_cache(dname)

    run.status = "failed" if upd_errors else "success"
    run.error = ("; ".join(upd_errors) or None) if upd_errors else None
    run.log = "\n".join(log)[-8000:]
    run.finished_at = datetime.utcnow()
    db.commit()
    if upd_errors:
        _notify_result(db, domain, run)


def _notify_result(db, domain, run) -> None:
    """Aviso en el panel al dueño del dominio si hubo rollback o error."""
    try:
        from scripts.notify import create_notification
        if run.status == "rolled_back":
            title = f"WordPress de {domain.domain_name}: rollback automático"
            msg = (f"La actualización rompió el sitio ({run.error}) y se restauró "
                   f"el punto de recuperación automáticamente. El sitio quedó como estaba.")
        else:
            title = f"WordPress de {domain.domain_name}: error al actualizar"
            msg = f"La actualización terminó con errores: {run.error}"
        create_notification(db, domain.user_id, "warning", title, msg,
                            dedup_key=f"wp-safe-update-{domain.id}")
        db.commit()
    except Exception as e:
        logger.warning(f"Safe-update: no pude notificar: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Historial / estado para el endpoint GET
# ─────────────────────────────────────────────────────────────────────────────
def get_status(domain, db, limit: int = 10) -> Dict:
    from api.models.models_wp_update import WpUpdateRun
    runs = (db.query(WpUpdateRun)
              .filter(WpUpdateRun.domain_id == domain.id)
              .order_by(WpUpdateRun.id.desc())
              .limit(limit).all())
    return {
        "auto_update": bool(getattr(domain, "wp_auto_update", False)),
        "job": job_status(domain.id),
        "history": [_run_dict(r) for r in runs],
    }


def _run_dict(r) -> Dict:
    def _j(v):
        try:
            return json.loads(v) if v else None
        except (ValueError, TypeError):
            return None
    return {
        "id": r.id, "mode": r.mode, "status": r.status,
        "rollback": bool(r.rollback), "error": r.error,
        "updated_items": _j(r.updated_items),
        "pre_health": _j(r.pre_health), "post_health": _j(r.post_health),
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler del modo automático (hilo dentro del panel, como backup_scheduler)
# ─────────────────────────────────────────────────────────────────────────────
_scheduler_started = False
_scheduler_lock = threading.Lock()


def _auto_pass() -> None:
    """Un pase nocturno: actualiza en serie todos los dominios con el toggle."""
    from api.models.database import SessionLocal, load_all_models
    load_all_models()
    db = SessionLocal()
    try:
        from api.models.models_domain import Domain
        ids = [d.id for d in (db.query(Domain)
                                .filter(Domain.wp_auto_update == True,   # noqa: E712
                                        Domain.is_active == True)        # noqa: E712
                                .order_by(Domain.id).all())
               if not d.staging_of_domain_id]
    finally:
        db.close()
    if not ids:
        return
    logger.info(f"WP auto-update: pase nocturno de {len(ids)} dominio(s)")
    for did in ids:
        if job_running(did):
            continue
        _job_init(did, STEPS)
        try:
            run_safe_update(did, mode="auto")
        except Exception:
            logger.exception(f"WP auto-update: dominio {did}")


def _scheduler_loop() -> None:
    from scripts.backup_scheduler import _now_local
    logger.info("WP auto-update scheduler iniciado")
    last_date = None
    while True:
        try:
            now = _now_local()
            due = (now.hour, now.minute) >= (AUTO_HOUR, AUTO_MINUTE)
            if due and last_date != now.date():
                last_date = now.date()
                _auto_pass()
        except Exception:
            logger.exception("Error en el scheduler de WP auto-update")
        time.sleep(60)


def _recover_zombie_runs() -> None:
    """Una fila 'running' al arrancar = el panel murió a media actualización."""
    from api.models.database import SessionLocal, load_all_models
    load_all_models()
    db = SessionLocal()
    try:
        from api.models.models_wp_update import WpUpdateRun
        zombies = db.query(WpUpdateRun).filter(WpUpdateRun.status == "running").all()
        for z in zombies:
            z.status = "failed"
            z.error = "El panel se reinició durante la actualización."
            z.finished_at = datetime.utcnow()
        if zombies:
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def start_wp_update_scheduler() -> None:
    """Arranca el hilo del modo automático (idempotente)."""
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True
    try:
        _recover_zombie_runs()
    except Exception:
        logger.exception("WP auto-update: recuperación de runs zombie")
    t = threading.Thread(target=_scheduler_loop, daemon=True,
                         name="wp-update-scheduler")
    t.start()
