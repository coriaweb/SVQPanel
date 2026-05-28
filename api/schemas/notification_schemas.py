"""
Esquemas Pydantic para notificaciones del panel.
"""

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class NotificationResponse(BaseModel):
    id:         int
    level:      str
    title:      str
    message:    str
    is_read:    bool
    created_at: datetime
    read_at:    Optional[datetime] = None

    class Config:
        from_attributes = True
