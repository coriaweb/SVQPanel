"""
Gestión de Laravel por dominio (pestaña «Laravel» de la ficha del dominio).

  GET  /api/domains/{id}/laravel/info              → resumen + diagnóstico + crons
  POST /api/domains/{id}/laravel/fix/{check}       → arreglo de un clic de un aviso
  POST /api/domains/{id}/laravel/action/{action}   → artisan habitual (optimize, migrate…)
  POST /api/domains/{id}/laravel/artisan           → consola artisan libre
  GET  /api/domains/{id}/laravel/artisan-history   → historial (audit log)
  GET  /api/domains/{id}/laravel/env               → contenido del .env
  PUT  /api/domains/{id}/laravel/env               → guardar .env (validado)
  GET  /api/domains/{id}/laravel/logs?file=&lines= → últimas líneas de un log
  POST /api/domains/{id}/laravel/logs/clear        → vaciar un log
  POST /api/domains/{id}/laravel/cron/{kind}       → planificador / cola por cron

Todo se ejecuta como el usuario del dominio y con su PHP (scripts/laravel_manager).
Los endpoints son `def` (no async): artisan puede tardar y un subprocess
bloqueante en una corrutina congelaría el panel entero (1 worker).
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import require_auth
from api.models.database import get_db
from api.models.models_user import User
from scripts.utils import get_domain_root

router = APIRouter()


def _ctx(domain_id: int, db: Session, user: User):
    """(domain, owner, docroot, raíz Laravel). 409 si no hay Laravel."""
    from api.routes.domains import _resolve_docroot_owner
    from scripts.laravel_manager import find_root
    domain, owner, docroot = _resolve_docroot_owner(domain_id, db, user)
    root = find_root(get_domain_root(owner, domain.domain_name), docroot)
    if not root:
        raise HTTPException(status_code=409,
                            detail="No se encuentra un proyecto Laravel (artisan + composer.json) en este dominio.")
    return domain, owner, docroot, root


def _served_dir(domain, docroot: str) -> str:
    sub = (getattr(domain, "docroot_subdir", None) or "").strip("/")
    return f"{docroot.rstrip('/')}/{sub}" if sub else docroot


def _base_url(domain) -> str:
    return f"{'https' if domain.ssl_enabled else 'http'}://{domain.domain_name}"


def _err(e: Exception):
    from scripts.laravel_manager import LaravelError
    if isinstance(e, HTTPException):
        raise e
    if isinstance(e, LaravelError):
        raise HTTPException(status_code=422, detail=str(e))
    raise HTTPException(status_code=500, detail=f"Error en Laravel: {e}")


# ── Crons (planificador / cola) ──────────────────────────────────────────────
def _cron_job(domain, kind: str, db: Session):
    from api.models.models_cron import CronJob
    from scripts.laravel_manager import cron_comment
    return (db.query(CronJob)
              .filter(CronJob.domain_id == domain.id,
                      CronJob.comment == cron_comment(kind, domain.domain_name))
              .first())


def _cron_state(domain, db: Session) -> dict:
    """Estado de los crons gestionados + si hay alguno hecho a mano."""
    from api.models.models_cron import CronJob
    from scripts.laravel_manager import CRON_KINDS
    out = {}
    others = db.query(CronJob).filter(CronJob.domain_id == domain.id).all()
    for kind, spec in CRON_KINDS.items():
        job = _cron_job(domain, kind, db)
        needle = spec["args"].split()[0]
        manual = [j.id for j in others
                  if needle in (j.command or "") and (job is None or j.id != job.id)]
        out[kind] = {"enabled": bool(job and job.is_active),
                     "cron_id": job.id if job else None,
                     "manual_ids": manual}
    return out


def _set_cron(domain, owner: str, root: str, kind: str, enable: bool, db: Session) -> dict:
    from api.models.models_cron import CronJob
    from scripts.cron_manager import CronManager
    from scripts import laravel_manager as lm

    job = _cron_job(domain, kind, db)
    if enable:
        if job is None:
            job = CronJob(user_id=domain.user_id, domain_id=domain.id,
                          minute="*", hour="*", day="*", month="*", weekday="*",
                          command=lm.cron_command(kind, root, domain.php_version),
                          comment=lm.cron_comment(kind, domain.domain_name),
                          is_active=True)
            db.add(job); db.commit(); db.refresh(job)
        else:
            job.is_active = True
            job.command = lm.cron_command(kind, root, domain.php_version)
            db.commit()
        CronManager().add_cron(username=owner, cron_id=job.id, minute=job.minute,
                               hour=job.hour, day=job.day, month=job.month,
                               weekday=job.weekday, command=job.command,
                               comment=job.comment or "")
        msg = ("Planificador activado: schedule:run cada minuto (visible en Cron)."
               if kind == "scheduler" else
               "Cola activada: cada minuto se procesan los trabajos pendientes (visible en Cron).")
    else:
        if job is not None:
            try:
                CronManager().remove_cron(owner, job.id)
            except Exception:
                pass
            db.delete(job); db.commit()
        msg = "Planificador desactivado." if kind == "scheduler" else "Proceso de la cola desactivado."
    return {"ok": True, "enabled": enable, "output": msg}


# ── Info / diagnóstico ───────────────────────────────────────────────────────
@router.get("/domains/{domain_id}/laravel/info")
def laravel_info(domain_id: int,
                 current_user: User = Depends(require_auth),
                 db: Session = Depends(get_db)):
    domain, owner, docroot, root = _ctx(domain_id, db, current_user)
    from scripts import laravel_manager as lm
    try:
        data = lm.info(root, owner, domain.php_version, domain.domain_name,
                       _served_dir(domain, docroot), bool(domain.ssl_enabled))
    except Exception as e:
        _err(e)
    data["crons"] = _cron_state(domain, db)
    # El planificador solo es un aviso si el proyecto define tareas y no hay cron.
    c = data["crons"]["scheduler"]
    if data.get("uses_scheduler") and not c["enabled"] and not c["manual_ids"]:
        data["checks"].append({
            "id": "scheduler", "level": "warning",
            "title": "Hay tareas programadas pero no se ejecutan",
            "detail": "El proyecto define tareas (schedule) y no hay ningún cron con "
                      "schedule:run: nunca se lanzan.",
            "fix": "scheduler", "fix_label": "Activar planificador"})
    data["base_url"] = _base_url(domain)
    return {"status": "success", "data": data}


@router.post("/domains/{domain_id}/laravel/fix/{check}")
def laravel_fix(domain_id: int, check: str, request: Request,
                current_user: User = Depends(require_auth),
                db: Session = Depends(get_db)):
    from scripts import laravel_manager as lm
    from api.utils.security_audit import log_audit
    domain, owner, docroot, root = _ctx(domain_id, db, current_user)
    php = domain.php_version
    try:
        if check == "template":
            import os as _os
            if _os.path.realpath(docroot) != root:   # la plantilla sirve {docroot}/public
                raise lm.LaravelError("El proyecto no está en la carpeta web del dominio; "
                                      "ajusta la carpeta raíz en Avanzado.")
            from api.routes.domains import _apply_builtin_template
            owner_row = db.query(User).filter(User.id == domain.user_id).first()
            _apply_builtin_template(domain, "laravel", owner_row, db)
            data = {"ok": True, "output": "Plantilla Laravel aplicada: la web sirve ya /public."}
        elif check == "vendor":
            from scripts.composer_manager import composer_install
            data = composer_install(root, owner, php_version=php)
        elif check == "env":
            data = lm.create_env_from_example(root, owner, php)
        elif check == "app_key":
            env = lm.parse_env(lm.read_env(root, owner) or "")
            if env.get("APP_KEY"):
                raise lm.LaravelError("APP_KEY ya tiene valor; cambiarla cerraría todas las "
                                      "sesiones y haría ilegible lo cifrado.")
            data = lm.run_action(root, owner, php, "key-generate")
        elif check == "app_debug":
            data = lm.update_env_keys(root, owner, php, {"APP_DEBUG": "false"})
        elif check == "app_env":
            data = lm.update_env_keys(root, owner, php, {"APP_ENV": "production"})
        elif check == "app_url":
            data = lm.update_env_keys(root, owner, php, {"APP_URL": _base_url(domain)})
        elif check == "permissions":
            data = lm.fix_permissions(root, owner)
        elif check == "storage_link":
            data = lm.run_action(root, owner, php, "storage-link")
        elif check == "log_size":
            logs = [f for f in lm._log_files(root) if f["size"] >= lm.LOG_WARN_BYTES]
            outs = [lm.clear_log(root, owner, f["name"])["output"] for f in logs]
            data = {"ok": True, "output": "\n".join(outs) or "Nada que vaciar."}
        elif check == "scheduler":
            data = _set_cron(domain, owner, root, "scheduler", True, db)
        else:
            raise HTTPException(status_code=400, detail=f"Arreglo no soportado: {check}")
    except Exception as e:
        log_audit(db, user=current_user, category="laravel", action=f"fix-{check}",
                  target=domain.domain_name, request=request, success=False, error=str(e)[:500])
        _err(e)
    log_audit(db, user=current_user, category="laravel", action=f"fix-{check}",
              target=domain.domain_name, request=request, success=True)
    return {"status": "success", "data": data}


@router.post("/domains/{domain_id}/laravel/action/{action}")
def laravel_action(domain_id: int, action: str, request: Request,
                   current_user: User = Depends(require_auth),
                   db: Session = Depends(get_db)):
    from scripts import laravel_manager as lm
    from api.utils.security_audit import log_audit
    if action == "key-generate":   # solo vía arreglo: rompe sesiones y datos cifrados
        raise HTTPException(status_code=400, detail="Acción no soportada")
    domain, owner, _docroot, root = _ctx(domain_id, db, current_user)
    try:
        data = lm.run_action(root, owner, domain.php_version, action, _base_url(domain))
    except Exception as e:
        log_audit(db, user=current_user, category="laravel", action=action,
                  target=domain.domain_name, request=request, success=False, error=str(e)[:500])
        _err(e)
    log_audit(db, user=current_user, category="laravel", action=action,
              target=domain.domain_name, request=request, success=True)
    return {"status": "success", "data": data}


# ── Consola artisan ──────────────────────────────────────────────────────────
class ArtisanRequest(BaseModel):
    command: str = Field(..., max_length=2000)


@router.post("/domains/{domain_id}/laravel/artisan")
def laravel_artisan(domain_id: int, payload: ArtisanRequest, request: Request,
                    current_user: User = Depends(require_auth),
                    db: Session = Depends(get_db)):
    from scripts import laravel_manager as lm
    from api.utils.security_audit import log_audit
    domain, owner, _docroot, root = _ctx(domain_id, db, current_user)
    try:
        data = lm.artisan_console(root, owner, domain.php_version, payload.command)
    except Exception as e:
        _err(e)
    log_audit(db, user=current_user, category="artisan", action="run",
              target=domain.domain_name, after={"command": data["command"], "rc": data["rc"]},
              request=request, success=data["rc"] == 0,
              error=None if data["rc"] == 0 else (data["stderr"] or data["stdout"] or "")[:500])
    return {"status": "success", "data": data}


@router.get("/domains/{domain_id}/laravel/artisan-history")
def laravel_artisan_history(domain_id: int, limit: int = 30,
                            current_user: User = Depends(require_auth),
                            db: Session = Depends(get_db)):
    from api.routes.domains import _resolve_docroot_owner
    from api.models.models_security import SecurityAuditLog
    domain, _o, _d = _resolve_docroot_owner(domain_id, db, current_user)
    rows = (db.query(SecurityAuditLog)
              .filter(SecurityAuditLog.category == "artisan",
                      SecurityAuditLog.target == domain.domain_name)
              .order_by(SecurityAuditLog.created_at.desc())
              .limit(min(max(limit, 1), 100)).all())
    history = []
    for r in rows:
        try:
            p = json.loads(r.after) if r.after else {}
        except (ValueError, TypeError):
            p = {}
        history.append({"command": p.get("command"), "rc": p.get("rc"),
                        "at": r.created_at.isoformat() if r.created_at else None})
    return {"status": "success", "data": history}


# ── .env ─────────────────────────────────────────────────────────────────────
class EnvRequest(BaseModel):
    content: str = Field(..., max_length=65536)


@router.get("/domains/{domain_id}/laravel/env")
def laravel_env_get(domain_id: int,
                    current_user: User = Depends(require_auth),
                    db: Session = Depends(get_db)):
    from scripts import laravel_manager as lm
    domain, owner, _docroot, root = _ctx(domain_id, db, current_user)
    text = lm.read_env(root, owner)
    return {"status": "success", "data": {"exists": text is not None, "content": text or ""}}


@router.put("/domains/{domain_id}/laravel/env")
def laravel_env_put(domain_id: int, payload: EnvRequest, request: Request,
                    current_user: User = Depends(require_auth),
                    db: Session = Depends(get_db)):
    from scripts import laravel_manager as lm
    from api.utils.security_audit import log_audit
    domain, owner, _docroot, root = _ctx(domain_id, db, current_user)
    try:
        data = lm.write_env(root, owner, domain.php_version, payload.content)
    except Exception as e:
        _err(e)
    # Sin el contenido en el audit: lleva contraseñas.
    log_audit(db, user=current_user, category="laravel", action="env-save",
              target=domain.domain_name, request=request, success=True)
    return {"status": "success", "data": data}


# ── Logs ─────────────────────────────────────────────────────────────────────
@router.get("/domains/{domain_id}/laravel/logs")
def laravel_logs(domain_id: int, file: Optional[str] = None, lines: int = 300,
                 current_user: User = Depends(require_auth),
                 db: Session = Depends(get_db)):
    from scripts import laravel_manager as lm
    domain, owner, _docroot, root = _ctx(domain_id, db, current_user)
    files = lm._log_files(root)
    name = file or (files[0]["name"] if files else None)
    if not name:
        return {"status": "success", "data": {"files": [], "log": None}}
    try:
        log = lm.read_log(root, owner, name, lines)
    except Exception as e:
        _err(e)
    return {"status": "success", "data": {"files": files, "log": log}}


class LogClearRequest(BaseModel):
    file: str = Field(..., max_length=130)


@router.post("/domains/{domain_id}/laravel/logs/clear")
def laravel_logs_clear(domain_id: int, payload: LogClearRequest,
                       current_user: User = Depends(require_auth),
                       db: Session = Depends(get_db)):
    from scripts import laravel_manager as lm
    domain, owner, _docroot, root = _ctx(domain_id, db, current_user)
    try:
        return {"status": "success", "data": lm.clear_log(root, owner, payload.file)}
    except Exception as e:
        _err(e)


# ── Crons ────────────────────────────────────────────────────────────────────
class CronToggle(BaseModel):
    enable: bool


@router.post("/domains/{domain_id}/laravel/cron/{kind}")
def laravel_cron(domain_id: int, kind: str, payload: CronToggle, request: Request,
                 current_user: User = Depends(require_auth),
                 db: Session = Depends(get_db)):
    from scripts.laravel_manager import CRON_KINDS
    from api.utils.security_audit import log_audit
    if kind not in CRON_KINDS:
        raise HTTPException(status_code=400, detail="Tipo no soportado")
    domain, owner, _docroot, root = _ctx(domain_id, db, current_user)
    try:
        data = _set_cron(domain, owner, root, kind, payload.enable, db)
    except Exception as e:
        _err(e)
    log_audit(db, user=current_user, category="laravel",
              action=f"cron-{kind}-{'on' if payload.enable else 'off'}",
              target=domain.domain_name, request=request, success=True)
    data["crons"] = _cron_state(domain, db)
    return {"status": "success", "data": data}
