"""
Helper de auditoría para Fase 12 — escribe entradas en SecurityAuditLog.
"""

import json
from typing import Optional, Any
from sqlalchemy.orm import Session
from fastapi import Request

from api.models.models_security import SecurityAuditLog


def _serialize(obj: Any) -> Optional[str]:
    """Serializa a JSON tolerando datetime y objetos SQLAlchemy básicos."""
    if obj is None:
        return None
    try:
        if hasattr(obj, "__table__"):
            obj = {c.name: getattr(obj, c.name, None) for c in obj.__table__.columns}
        return json.dumps(obj, default=str, ensure_ascii=False)[:8000]
    except Exception:
        return str(obj)[:8000]


def client_ip(request: Optional[Request]) -> Optional[str]:
    """Extrae la IP origen del request, respetando X-Forwarded-For si existe."""
    if request is None:
        return None
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def log_audit(
    db:          Session,
    *,
    user:        Optional[Any]   = None,
    category:    str             = "firewall",
    action:      str             = "",
    target:      Optional[str]   = None,
    before:      Optional[Any]   = None,
    after:       Optional[Any]   = None,
    request:     Optional[Request] = None,
    success:     bool            = True,
    error:       Optional[str]   = None,
) -> None:
    """Escribe una entrada de auditoría y hace commit. Nunca lanza excepciones."""
    try:
        entry = SecurityAuditLog(
            user_id    = getattr(user, "id", None),
            user_label = getattr(user, "username", None),
            category   = category,
            action     = action,
            target     = (target or "")[:255] or None,
            before     = _serialize(before),
            after      = _serialize(after),
            ip_origin  = client_ip(request),
            success    = success,
            error      = (error or "")[:8000] or None,
        )
        db.add(entry)
        db.commit()
    except Exception:
        db.rollback()
