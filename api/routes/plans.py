"""
Rutas API — Planes (Fase 13)

Scoping:
  - Admin: ve y gestiona TODOS los planes (globales + de cualquier reseller)
  - Reseller: ve planes globales (owner_id NULL) y los suyos (owner_id=self).
              Solo puede CREAR/EDITAR/BORRAR planes con owner_id=self.
  - User normal: 403 — no debería tocar planes.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from api.models.database import get_db
from api.models.models_user import User
from api.models.models_plan import Plan
from api.schemas.plan_schemas import PlanCreate, PlanUpdate, PlanResponse
from api.dependencies import get_current_user, require_admin
from api.utils.security_audit import log_audit


router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de autorización
# ─────────────────────────────────────────────────────────────────────────────
def _require_admin_or_reseller(user: User) -> None:
    if user.role not in ("admin", "reseller"):
        raise HTTPException(status_code=403, detail="Solo admin o reseller pueden gestionar planes")


def _plan_visible_to(plan: Plan, user: User) -> bool:
    if user.role == "admin":
        return True
    if user.role == "reseller":
        return plan.owner_id is None or plan.owner_id == user.id
    return False


def _plan_editable_by(plan: Plan, user: User) -> bool:
    if user.role == "admin":
        return True
    if user.role == "reseller":
        # Solo edita los suyos. Los globales (owner=NULL) son de admin.
        return plan.owner_id == user.id
    return False


def _users_count(db: Session, plan_id: int) -> int:
    return db.query(func.count(User.id)).filter(User.plan_id == plan_id).scalar() or 0


def _to_response(db: Session, plan: Plan) -> PlanResponse:
    owner_username = None
    if plan.owner_id and plan.owner:
        owner_username = plan.owner.username
    return PlanResponse(
        id=plan.id,
        name=plan.name,
        description=plan.description,
        owner_id=plan.owner_id,
        owner_username=owner_username,
        disk_quota_mb=plan.disk_quota_mb,
        traffic_quota_mb_month=plan.traffic_quota_mb_month,
        domains_limit=plan.domains_limit,
        databases_limit=plan.databases_limit,
        mailboxes_limit=plan.mailboxes_limit,
        dns_zones_limit=plan.dns_zones_limit,
        is_default=plan.is_default,
        users_count=_users_count(db, plan.id),
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


# ─────────────────────────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/plans", response_model=List[PlanResponse])
async def list_plans(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    _require_admin_or_reseller(user)
    q = db.query(Plan)
    if user.role == "reseller":
        q = q.filter(or_(Plan.owner_id == None, Plan.owner_id == user.id))   # noqa: E711
    plans = q.order_by(Plan.owner_id.nullsfirst(), Plan.name).all()
    return [_to_response(db, p) for p in plans]


@router.get("/plans/{plan_id}", response_model=PlanResponse)
async def get_plan(
    plan_id: int,
    db:      Session = Depends(get_db),
    user:    User    = Depends(get_current_user),
):
    _require_admin_or_reseller(user)
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    if not _plan_visible_to(plan, user):
        raise HTTPException(status_code=403, detail="No tienes acceso a este plan")
    return _to_response(db, plan)


@router.post("/plans", response_model=PlanResponse)
async def create_plan(
    payload: PlanCreate,
    request: Request,
    db:      Session = Depends(get_db),
    user:    User    = Depends(get_current_user),
):
    _require_admin_or_reseller(user)

    # Resolver owner_id según rol
    owner_id: Optional[int]
    if user.role == "reseller":
        # Reseller no puede crear planes para otros owners
        if payload.owner_id is not None and payload.owner_id != user.id:
            raise HTTPException(status_code=403, detail="Reseller solo puede crear planes propios")
        owner_id = user.id
    else:
        # Admin: si pasa owner_id, validar que existe; si no, plan global
        owner_id = payload.owner_id
        if owner_id is not None:
            owner = db.query(User).filter(User.id == owner_id).first()
            if not owner:
                raise HTTPException(status_code=400, detail="owner_id no existe")

    # Si is_default, desmarcar el resto del mismo owner
    if payload.is_default:
        db.query(Plan).filter(Plan.owner_id == owner_id, Plan.is_default == True).update(   # noqa: E712
            {Plan.is_default: False}
        )

    plan = Plan(
        name=payload.name,
        description=payload.description,
        owner_id=owner_id,
        disk_quota_mb=payload.disk_quota_mb,
        traffic_quota_mb_month=payload.traffic_quota_mb_month,
        domains_limit=payload.domains_limit,
        databases_limit=payload.databases_limit,
        mailboxes_limit=payload.mailboxes_limit,
        dns_zones_limit=payload.dns_zones_limit,
        is_default=payload.is_default,
    )
    db.add(plan)
    try:
        db.commit()
        db.refresh(plan)
    except Exception as e:
        db.rollback()
        msg = str(e)
        if "uq_plans_owner_name" in msg:
            raise HTTPException(status_code=409, detail=f"Ya existe un plan llamado '{payload.name}' para este propietario")
        raise HTTPException(status_code=500, detail=f"Error guardando plan: {msg}")

    log_audit(db, user=user, category="plan", action="create",
              target=plan.name, after=plan.snapshot(), request=request, success=True)
    return _to_response(db, plan)


@router.put("/plans/{plan_id}", response_model=PlanResponse)
async def update_plan(
    plan_id: int,
    payload: PlanUpdate,
    request: Request,
    db:      Session = Depends(get_db),
    user:    User    = Depends(get_current_user),
):
    _require_admin_or_reseller(user)
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    if not _plan_editable_by(plan, user):
        raise HTTPException(status_code=403, detail="No puedes editar este plan")

    before = plan.snapshot()
    data = payload.model_dump(exclude_unset=True)

    if data.get("is_default") is True:
        db.query(Plan).filter(
            Plan.owner_id == plan.owner_id,
            Plan.is_default == True,                                                       # noqa: E712
            Plan.id != plan.id,
        ).update({Plan.is_default: False})

    for field, value in data.items():
        setattr(plan, field, value)

    try:
        db.commit()
        db.refresh(plan)
    except Exception as e:
        db.rollback()
        msg = str(e)
        if "uq_plans_owner_name" in msg:
            raise HTTPException(status_code=409, detail="Ya existe un plan con ese nombre")
        raise HTTPException(status_code=500, detail=f"Error actualizando plan: {msg}")

    log_audit(db, user=user, category="plan", action="update",
              target=plan.name, before=before, after=plan.snapshot(),
              request=request, success=True)
    return _to_response(db, plan)


@router.delete("/plans/{plan_id}")
async def delete_plan(
    plan_id: int,
    request: Request,
    db:      Session = Depends(get_db),
    user:    User    = Depends(get_current_user),
):
    _require_admin_or_reseller(user)
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    if not _plan_editable_by(plan, user):
        raise HTTPException(status_code=403, detail="No puedes borrar este plan")

    snap = plan.snapshot()
    # Los usuarios con este plan quedan con plan_id=NULL (ON DELETE SET NULL)
    db.delete(plan)
    db.commit()

    log_audit(db, user=user, category="plan", action="delete",
              target=snap["plan_name"], before=snap, request=request, success=True)
    return {"status": "deleted", "id": plan_id}


# ─────────────────────────────────────────────────────────────────────────────
# Asignar plan a un usuario (snapshot)
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/users/{user_id}/assign-plan/{plan_id}")
async def assign_plan_to_user(
    user_id: int,
    plan_id: int,
    request: Request,
    db:      Session = Depends(get_db),
    actor:   User    = Depends(get_current_user),
):
    _require_admin_or_reseller(actor)

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if not actor.can_manage_user(target):
        raise HTTPException(status_code=403, detail="No puedes gestionar este usuario")

    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    if not _plan_visible_to(plan, actor):
        raise HTTPException(status_code=403, detail="No tienes acceso a este plan")

    before = {
        "plan_id":              target.plan_id,
        "plan_name":            target.plan_name,
        "disk_quota_mb":        target.disk_quota_mb,
        "domains_limit":        target.domains_limit,
        "databases_limit":      target.databases_limit,
        "mailboxes_limit":      target.mailboxes_limit,
        "dns_zones_limit":      target.dns_zones_limit,
        "traffic_quota_mb_month": target.traffic_quota_mb_month,
    }

    snap = plan.snapshot()
    for k, v in snap.items():
        setattr(target, k, v)
    db.commit()

    log_audit(db, user=actor, category="plan", action="assign",
              target=f"{target.username} ← {plan.name}",
              before=before, after=snap, request=request, success=True)
    return {"status": "applied", "user_id": user_id, "plan": snap}


@router.post("/users/{user_id}/unassign-plan")
async def unassign_plan_from_user(
    user_id: int,
    request: Request,
    db:      Session = Depends(get_db),
    actor:   User    = Depends(get_current_user),
):
    """Quita la referencia al plan (no toca límites — los deja como están)."""
    _require_admin_or_reseller(actor)
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if not actor.can_manage_user(target):
        raise HTTPException(status_code=403, detail="No puedes gestionar este usuario")

    before = {"plan_id": target.plan_id, "plan_name": target.plan_name}
    target.plan_id   = None
    target.plan_name = None
    db.commit()

    log_audit(db, user=actor, category="plan", action="unassign",
              target=target.username, before=before, request=request, success=True)
    return {"status": "ok", "user_id": user_id}
