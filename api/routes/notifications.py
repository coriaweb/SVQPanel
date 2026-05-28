"""
Rutas API para notificaciones del usuario (campana del panel).

Cada usuario solo ve y gestiona sus propias notificaciones.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from datetime import datetime

from api.models.database import get_db
from api.models.models_user import User
from api.models.models_notification import Notification
from api.schemas.notification_schemas import NotificationResponse
from api.dependencies import require_auth

router = APIRouter()


@router.get("/notifications", response_model=list[NotificationResponse])
async def list_notifications(
    only_unread: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Lista las notificaciones del usuario, más recientes primero."""
    q = db.query(Notification).filter(Notification.user_id == current_user.id)
    if only_unread:
        q = q.filter(Notification.is_read == False)  # noqa: E712
    return q.order_by(Notification.created_at.desc()).limit(limit).all()


@router.get("/notifications/unread-count")
async def unread_count(
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Número de notificaciones sin leer (para el badge de la campana)."""
    count = (
        db.query(Notification)
        .filter(
            Notification.user_id == current_user.id,
            Notification.is_read == False,  # noqa: E712
        )
        .count()
    )
    return {"unread": count}


@router.post("/notifications/{notification_id}/read")
async def mark_read(
    notification_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Marca una notificación como leída."""
    n = (
        db.query(Notification)
        .filter(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
        )
        .first()
    )
    if n and not n.is_read:
        n.is_read = True
        n.read_at = datetime.utcnow()
        db.commit()
    return {"status": "ok"}


@router.post("/notifications/read-all")
async def mark_all_read(
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Marca todas las notificaciones del usuario como leídas."""
    updated = (
        db.query(Notification)
        .filter(
            Notification.user_id == current_user.id,
            Notification.is_read == False,  # noqa: E712
        )
        .update(
            {"is_read": True, "read_at": datetime.utcnow()},
            synchronize_session=False,
        )
    )
    db.commit()
    return {"status": "ok", "marked": updated}
