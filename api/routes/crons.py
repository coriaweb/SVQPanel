"""
Rutas API para gestión de cron jobs de clientes.
"""

import threading

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime

from api.models.database import get_db
from api.models.models_user import User
from api.models.models_cron import CronJob
from api.models.models_domain import Domain
from api.schemas.cron_schemas import (
    CronJobCreate, CronJobUpdate, CronJobResponse,
    CronBuildRequest, CronTestRequest, CronScheduleRequest,
)
from api.dependencies import require_auth, require_admin
from api.utils.scope import managed_user_ids, can_manage_owner

router = APIRouter()

_TESTS_LOCK = threading.Lock()
_TESTS_RUNNING: set[int] = set()   # user_id con una prueba de cron en curso


def _get_cron_or_404(cron_id: int, db: Session) -> CronJob:
    cron = db.query(CronJob).filter(CronJob.id == cron_id).first()
    if not cron:
        raise HTTPException(status_code=404, detail="Cron no encontrado")
    return cron


def _check_cron_access(current_user: User, cron: CronJob, db: Session):
    # Admin: todos; reseller: los suyos y los de sus clientes; usuario: los suyos.
    if not can_manage_owner(db, current_user, cron.user_id):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar este cron")


def _get_username_for_user(user: User) -> str:
    """Devuelve el nombre de usuario del sistema para ejecutar el cron.
    Los admins del panel corren como root en el sistema."""
    if user.is_admin:
        return "root"
    return user.username


def _resolve_owner(current_user: User, user_id: int | None, db: Session) -> User:
    """Propietario de un cron nuevo. Admin/reseller puede asignarlo a un cliente:
    entonces se ejecuta BAJO el usuario de sistema de ese cliente (aislado), no
    como root. Si no se indica user_id, es del propio usuario que lo crea."""
    is_admin_or_reseller = current_user.is_admin or getattr(current_user, "role", None) == "reseller"
    if not (user_id and is_admin_or_reseller):
        return current_user
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario propietario no encontrado")
    # Un reseller solo puede crear crons para sus propios clientes
    if not current_user.is_admin and target.id != current_user.id and target.parent_id != current_user.id:
        raise HTTPException(status_code=403, detail="Ese usuario no es tu cliente")
    return target


def _cron_to_response(cron: CronJob, db: Session) -> dict:
    """Serializa un cron añadiendo el username del propietario (para la vista admin)."""
    owner = db.query(User).filter(User.id == cron.user_id).first()
    data = {c.name: getattr(cron, c.name) for c in cron.__table__.columns}
    data["username"] = owner.username if owner else None
    return data


# ─────────────────────────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/crons", response_model=list[CronJobResponse])
async def list_crons(
    user_id: int | None = None,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Lista los crons del usuario actual. Admin: todos, o los de un usuario
    concreto si se pasa ?user_id=N (para filtrar por cliente en el panel)."""
    query = db.query(CronJob)
    # Alcance común (admin todo; reseller él + sus clientes; usuario lo suyo).
    # ?user_id solo acota DENTRO de ese alcance.
    ids = managed_user_ids(db, current_user)
    if ids is not None:
        query = query.filter(CronJob.user_id.in_(ids))
    if user_id is not None:
        query = query.filter(CronJob.user_id == user_id)
    crons = query.order_by(CronJob.created_at.desc()).all()
    return [_cron_to_response(c, db) for c in crons]


@router.post("/crons", response_model=CronJobResponse, status_code=status.HTTP_201_CREATED)
async def create_cron(
    payload: CronJobCreate,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Crea un nuevo cron job."""
    owner = _resolve_owner(current_user, payload.user_id, db)

    # Verificar que el dominio pertenece al propietario (si se especificó)
    if payload.domain_id:
        domain = db.query(Domain).filter(Domain.id == payload.domain_id).first()
        if not domain:
            raise HTTPException(status_code=404, detail="Dominio no encontrado")
        if not current_user.is_admin and domain.user_id != owner.id:
            raise HTTPException(status_code=403, detail="Ese dominio no te pertenece")

    cron = CronJob(
        user_id   = owner.id,
        domain_id = payload.domain_id,
        minute    = payload.minute,
        hour      = payload.hour,
        day       = payload.day,
        month     = payload.month,
        weekday   = payload.weekday,
        command   = payload.command,
        comment   = payload.comment,
        is_active = True,
    )
    db.add(cron)
    db.commit()
    db.refresh(cron)

    # Escribir en el crontab del sistema (bajo el usuario del PROPIETARIO)
    try:
        from scripts.cron_manager import CronManager
        mgr = CronManager()
        sys_user = _get_username_for_user(owner)
        mgr.add_cron(
            username=sys_user,
            cron_id=cron.id,
            minute=cron.minute,
            hour=cron.hour,
            day=cron.day,
            month=cron.month,
            weekday=cron.weekday,
            command=cron.command,
            comment=cron.comment or "",
        )
    except Exception as e:
        # Si falla el sistema de archivos, informamos pero no revertimos la BD
        # El admin puede corregirlo manualmente
        import logging
        logging.getLogger(__name__).warning(f"No se pudo escribir crontab: {e}")

    return _cron_to_response(cron, db)


# ─────────────────────────────────────────────────────────────────────────────
# Asistente (plantillas, explorador, próximas ejecuciones, probar)
# ─────────────────────────────────────────────────────────────────────────────

def _assistant_domain(domain_id: int, current_user: User, db: Session):
    """Dominio accesible + su carpeta base (/home/DUEÑO/web/DOMINIO)."""
    from scripts.cron_assistant import domain_base_dir
    domain = db.query(Domain).filter(Domain.id == domain_id).first()
    if not domain or not can_manage_owner(db, current_user, domain.user_id):
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    owner = db.query(User).filter(User.id == domain.user_id).first()
    if not owner:
        raise HTTPException(status_code=404, detail="Propietario del dominio no encontrado")
    return domain, owner, domain_base_dir(owner.username, domain.domain_name)


@router.get("/crons/assistant/domains")
def assistant_domains(
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Dominios con web del usuario (o de sus clientes) con el PHP que usarán
    sus crons y las apps detectadas que tienen tarea programada conocida."""
    from scripts.cron_assistant import detect_apps, domain_base_dir, php_binary
    q = db.query(Domain).filter(Domain.mail_dns_only.is_(False))
    ids = managed_user_ids(db, current_user)
    if ids is not None:
        q = q.filter(Domain.user_id.in_(ids))
    owners = {u.id: u.username for u in db.query(User.id, User.username).all()}
    out = []
    for d in q.order_by(Domain.domain_name.asc()).all():
        owner = owners.get(d.user_id)
        if not owner:
            continue
        base = domain_base_dir(owner, d.domain_name)
        try:
            apps = detect_apps(base, d.public_html, d.php_version)
        except Exception:
            apps = []
        out.append({"id": d.id, "domain_name": d.domain_name, "user_id": d.user_id,
                    "owner": owner, "php_version": d.php_version,
                    "php_bin": php_binary(d.php_version), "base_dir": base,
                    "apps": apps})
    return out


@router.get("/crons/assistant/browse")
def assistant_browse(
    domain_id: int,
    path: str = "",
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Carpetas y scripts (.php/.sh) dentro de la carpeta del dominio."""
    from scripts.cron_assistant import AssistantError, browse
    _domain, _owner, base = _assistant_domain(domain_id, current_user, db)
    try:
        return browse(base, path)
    except AssistantError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/crons/assistant/build")
def assistant_build(
    payload: CronBuildRequest,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Monta el comando de una plantilla. Devuelve también el dueño con el que
    se ejecutará (el del dominio) para que el cron se cree bajo ese usuario."""
    from scripts.cron_assistant import AssistantError, build_script_command, build_url_cmd
    try:
        if payload.template == "url":
            return {"command": build_url_cmd(payload.url), "user_id": None}
        if payload.template == "script":
            if not payload.domain_id or not payload.path:
                raise AssistantError("Elige el dominio y el script")
            domain, owner, base = _assistant_domain(payload.domain_id, current_user, db)
            cmd = build_script_command(base, payload.path, domain.php_version, payload.args or "")
            return {"command": cmd, "user_id": owner.id}
        raise AssistantError("Plantilla desconocida")
    except AssistantError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/crons/assistant/next-runs")
def assistant_next_runs(
    payload: CronScheduleRequest,
    current_user: User = Depends(require_auth),
):
    """Próximas 5 ejecuciones de la expresión, en la hora del servidor (la que
    usa cron y la que muestra el panel)."""
    from scripts.cron_assistant import AssistantError, next_runs
    try:
        runs = next_runs(payload.minute, payload.hour, payload.day,
                         payload.month, payload.weekday, count=5)
    except AssistantError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # naive local → con offset, para que el navegador la sitúe bien
    return {"runs": [r.astimezone().isoformat() for r in runs]}


@router.post("/crons/test")
def test_cron_command(  # def (no async): bloquea hasta 60 s → threadpool
    payload: CronTestRequest,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Ejecuta un comando ANTES de guardar el cron, como el usuario con el que
    se ejecutará, y devuelve la salida. No deja historial. Límite 60 s."""
    from scripts.cron_runner import run_as_user
    owner = _resolve_owner(current_user, payload.user_id, db)
    # Una prueba a la vez por usuario: cada una ocupa un hilo del threadpool
    # hasta 60 s; sin esto, pulsar en bucle agotaría los hilos del panel.
    with _TESTS_LOCK:
        if current_user.id in _TESTS_RUNNING:
            raise HTTPException(status_code=429, detail="Ya hay una prueba en curso; espera a que termine.")
        _TESTS_RUNNING.add(current_user.id)
    try:
        r = run_as_user(payload.command, _get_username_for_user(owner), timeout=60)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="No se pudo lanzar la tarea (runuser no disponible).")
    finally:
        with _TESTS_LOCK:
            _TESTS_RUNNING.discard(current_user.id)
    return {"status": "success" if r["exit_code"] == 0 else "error",
            "exit_code": r["exit_code"], "duration_ms": r["duration_ms"],
            "output": r["output"], "command": payload.command,
            "run_as": _get_username_for_user(owner)}


@router.get("/crons/last-runs")
async def crons_last_runs(
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Última ejecución de cada cron visible para el usuario, en UNA consulta y
    sin la salida (para la columna «Última ejecución» del listado). Antes la vista
    pedía /crons/{id}/runs por cada cron: con 200 crons, 200 peticiones y ~8 MB.
    Devuelve {cron_id: {started_at, duration_ms, exit_code, trigger}}."""
    from sqlalchemy import func
    from api.models.models_cron_run import CronRun

    latest = (db.query(CronRun.cron_id, func.max(CronRun.started_at).label("mx"))
              .group_by(CronRun.cron_id))
    ids = managed_user_ids(db, current_user)
    if ids is not None:
        latest = (latest.join(CronJob, CronJob.id == CronRun.cron_id)
                  .filter(CronJob.user_id.in_(ids)))
    latest = latest.subquery()

    rows = (db.query(CronRun.cron_id, CronRun.started_at, CronRun.duration_ms,
                     CronRun.exit_code, CronRun.trigger)
            .join(latest, (CronRun.cron_id == latest.c.cron_id)
                  & (CronRun.started_at == latest.c.mx))
            .all())
    return {
        str(r.cron_id): {
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "duration_ms": r.duration_ms,
            "exit_code": r.exit_code,
            "trigger": r.trigger,
        } for r in rows
    }


@router.get("/crons/{cron_id}", response_model=CronJobResponse)
async def get_cron(
    cron_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    cron = _get_cron_or_404(cron_id, db)
    _check_cron_access(current_user, cron, db)
    return _cron_to_response(cron, db)


@router.put("/crons/{cron_id}", response_model=CronJobResponse)
async def update_cron(
    cron_id: int,
    payload: CronJobUpdate,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Actualiza un cron job."""
    cron = _get_cron_or_404(cron_id, db)
    _check_cron_access(current_user, cron, db)

    updated = payload.model_dump(exclude_unset=True)
    # Igual que al crear: el dominio asociado debe ser del dueño del cron.
    if updated.get("domain_id") and not current_user.is_admin:
        _dom = db.query(Domain).filter(Domain.id == updated["domain_id"]).first()
        if not _dom or _dom.user_id != cron.user_id:
            raise HTTPException(status_code=403, detail="Ese dominio no pertenece al dueño del cron")
    for field, value in updated.items():
        setattr(cron, field, value)
    cron.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(cron)

    # Actualizar crontab del sistema
    try:
        from scripts.cron_manager import CronManager
        mgr = CronManager()
        owner = db.query(User).filter(User.id == cron.user_id).first()
        sys_user = _get_username_for_user(owner)
        if cron.is_active:
            mgr.add_cron(
                username=sys_user,
                cron_id=cron.id,
                minute=cron.minute,
                hour=cron.hour,
                day=cron.day,
                month=cron.month,
                weekday=cron.weekday,
                command=cron.command,
                comment=cron.comment or "",
            )
        else:
            mgr.remove_cron(sys_user, cron.id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"No se pudo actualizar crontab: {e}")

    return _cron_to_response(cron, db)


@router.delete("/crons/{cron_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cron(
    cron_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Elimina un cron job."""
    cron = _get_cron_or_404(cron_id, db)
    _check_cron_access(current_user, cron, db)

    # Eliminar del crontab del sistema
    try:
        from scripts.cron_manager import CronManager
        mgr = CronManager()
        owner = db.query(User).filter(User.id == cron.user_id).first()
        sys_user = _get_username_for_user(owner)
        mgr.remove_cron(sys_user, cron.id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"No se pudo eliminar del crontab: {e}")

    db.delete(cron)
    db.commit()


@router.post("/crons/{cron_id}/toggle", response_model=CronJobResponse)
async def toggle_cron(
    cron_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Activa o desactiva un cron job."""
    cron = _get_cron_or_404(cron_id, db)
    _check_cron_access(current_user, cron, db)

    cron.is_active = not cron.is_active
    cron.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(cron)

    # Actualizar crontab del sistema
    try:
        from scripts.cron_manager import CronManager
        mgr = CronManager()
        owner = db.query(User).filter(User.id == cron.user_id).first()
        sys_user = _get_username_for_user(owner)
        if cron.is_active:
            mgr.enable_cron(sys_user, cron.id)
        else:
            mgr.disable_cron(sys_user, cron.id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"No se pudo actualizar crontab: {e}")

    return _cron_to_response(cron, db)


@router.post("/crons/{cron_id}/run")
def run_cron_now(  # def (no async): el subprocess bloquea; así va al threadpool
    cron_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Ejecuta AHORA el comando del cron (como el usuario del sistema), sin esperar
    a su horario. Registra el historial (trigger='manual') y devuelve el resultado.
    Útil para probar un cron tras crearlo/migrarlo, igual que en Hestia."""
    cron = _get_cron_or_404(cron_id, db)
    _check_cron_access(current_user, cron, db)

    owner = db.query(User).filter(User.id == cron.user_id).first()
    sys_user = _get_username_for_user(owner)

    from scripts.cron_runner import record_manual_run
    try:
        res = record_manual_run(db, cron.id, cron.command, sys_user, timeout=120)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="No se pudo lanzar la tarea (runuser no disponible).")

    return {
        "status": "success" if res["exit_code"] == 0 else "error",
        "exit_code": res["exit_code"],
        "duration_ms": res["duration_ms"],
        "output": res["output"],
        "command": cron.command,
    }


@router.get("/crons/{cron_id}/runs")
async def cron_runs(
    cron_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Historial de las últimas ejecuciones de un cron (estado/duración/salida)."""
    from api.models.models_cron_run import CronRun
    cron = _get_cron_or_404(cron_id, db)
    _check_cron_access(current_user, cron, db)
    runs = (db.query(CronRun)
            .filter(CronRun.cron_id == cron_id)
            .order_by(CronRun.started_at.desc()).all())
    return [{
        "id": r.id,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "duration_ms": r.duration_ms,
        "exit_code": r.exit_code,
        "trigger": r.trigger,
        "output": r.output,
    } for r in runs]
