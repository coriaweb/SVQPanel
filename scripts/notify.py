"""
Helper para crear notificaciones de usuario con deduplicación.

create_notification() no crea un aviso si ya existe uno NO leído con el mismo
(user_id, dedup_key). Así el timer de stats puede llamarse cada hora sin
inundar al usuario con el mismo aviso "estás al 90%".

Cuando el uso vuelve por debajo del umbral, clear_notification() marca como
leídas las notificaciones de esa clave, para que un futuro cruce vuelva a
avisar.
"""

import logging
from datetime import datetime

from api.models.models_notification import Notification

logger = logging.getLogger(__name__)


def create_notification(db, user_id, level, title, message, dedup_key=None):
    """
    Crea una notificación. Si dedup_key tiene una notificación NO leída para
    ese usuario, no crea otra (devuelve la existente). No hace commit.
    """
    if dedup_key:
        existing = (
            db.query(Notification)
            .filter(
                Notification.user_id == user_id,
                Notification.dedup_key == dedup_key,
                Notification.is_read == False,  # noqa: E712
            )
            .first()
        )
        if existing:
            return existing

    n = Notification(
        user_id=user_id,
        level=level,
        title=title,
        message=message,
        dedup_key=dedup_key,
    )
    db.add(n)
    return n


def clear_notification(db, user_id, dedup_key):
    """
    Marca como leídas las notificaciones NO leídas de (user_id, dedup_key).
    Se usa cuando la condición que generó el aviso ya no se cumple. No hace
    commit.
    """
    if not dedup_key:
        return
    db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.dedup_key == dedup_key,
        Notification.is_read == False,  # noqa: E712
    ).update(
        {"is_read": True, "read_at": datetime.utcnow()},
        synchronize_session=False,
    )
