"""
Rutas API para gestión de cron jobs de clientes.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime

from api.models.database import get_db
from api.models.models_user import User
from api.models.models_cron import CronJob
from api.models.models_domain import Domain
from api.schemas.cron_schemas import CronJobCreate, CronJobUpdate, CronJobResponse
from api.dependencies import require_auth, require_admin

router = APIRouter()


def _get_cron_or_404(cron_id: int, db: Session) -> CronJob:
    cron = db.query(CronJob).filter(CronJob.id == cron_id).first()
    if not cron:
        raise HTTPException(status_code=404, detail="Cron no encontrado")
    return cron


def _check_cron_access(current_user: User, cron: CronJob):
    if not current_user.is_admin and cron.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar este cron")


def _get_username_for_user(user: User) -> str:
    """Devuelve el nombre de usuario del sistema para ejecutar el cron.
    Los admins del panel corren como root en el sistema."""
    if user.is_admin:
        return "root"
    return user.username


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
    if current_user.is_admin:
        if user_id is not None:
            query = query.filter(CronJob.user_id == user_id)
    else:
        # Un usuario normal solo ve los suyos, pase lo que pase en ?user_id
        query = query.filter(CronJob.user_id == current_user.id)
    crons = query.order_by(CronJob.created_at.desc()).all()
    return [_cron_to_response(c, db) for c in crons]


@router.post("/crons", response_model=CronJobResponse, status_code=status.HTTP_201_CREATED)
async def create_cron(
    payload: CronJobCreate,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Crea un nuevo cron job."""
    # ── Determinar propietario ────────────────────────────────────────────────
    # Admin/reseller puede asignar el cron a un cliente: entonces se ejecuta BAJO
    # el usuario de sistema de ese cliente (aislado), no como root. Si no se
    # indica user_id, el cron es del propio usuario que lo crea.
    is_admin_or_reseller = current_user.is_admin or getattr(current_user, "role", None) == "reseller"
    owner = current_user
    if payload.user_id and is_admin_or_reseller:
        target = db.query(User).filter(User.id == payload.user_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="Usuario propietario no encontrado")
        # Un reseller solo puede crear crons para sus propios clientes
        if not current_user.is_admin and target.id != current_user.id and target.parent_id != current_user.id:
            raise HTTPException(status_code=403, detail="Ese usuario no es tu cliente")
        owner = target

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


@router.get("/crons/{cron_id}", response_model=CronJobResponse)
async def get_cron(
    cron_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    cron = _get_cron_or_404(cron_id, db)
    _check_cron_access(current_user, cron)
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
    _check_cron_access(current_user, cron)

    updated = payload.model_dump(exclude_unset=True)
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
    _check_cron_access(current_user, cron)

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
    _check_cron_access(current_user, cron)

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
