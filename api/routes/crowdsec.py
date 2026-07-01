"""
Rutas API — CrowdSec (Fase 12.7)

CrowdSec actúa en paralelo a fail2ban: detecta comportamientos a partir
de logs y mantiene una blocklist local (más opcionalmente comunitaria via
CAPI). Las decisiones son aplicadas por bouncers externos (firewall, nginx…).
"""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from api.models.database import get_db
from api.schemas.crowdsec_schemas import (
    CrowdsecStatus,
    CrowdsecDecision,
    CrowdsecAlert,
    CrowdsecBouncer,
    CrowdsecCollection,
    CrowdsecScenario,
    CrowdsecBanRequest,
    CrowdsecCapiStatus,
)
from api.dependencies import require_admin
from api.utils import crowdsec_helper as cs
from api.utils.security_audit import log_audit

router = APIRouter()
logger = logging.getLogger(__name__)


def _ensure_running():
    if not cs.is_installed():
        raise HTTPException(
            status_code=503,
            detail="CrowdSec no está instalado. Instálalo desde install.sh o "
                   "manualmente con: curl -s https://install.crowdsec.net | bash",
        )
    if not cs.is_running():
        raise HTTPException(status_code=503, detail="CrowdSec no está corriendo")


# ─────────────────────────────────────────────────────────────────────────────
# Estado
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/crowdsec/status", response_model=CrowdsecStatus)
async def crowdsec_status(_: dict = Depends(require_admin)):
    return cs.overview()


@router.get("/crowdsec/capi", response_model=CrowdsecCapiStatus)
async def crowdsec_capi(_: dict = Depends(require_admin)):
    _ensure_running()
    return cs.capi_status()


# ─────────────────────────────────────────────────────────────────────────────
# Decisiones
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/crowdsec/decisions", response_model=List[CrowdsecDecision])
async def list_decisions(_: dict = Depends(require_admin)):
    _ensure_running()
    return cs.list_decisions()


@router.post("/crowdsec/decisions")
async def add_decision(
    payload: CrowdsecBanRequest,
    request: Request,
    db:      Session = Depends(get_db),
    user:    dict    = Depends(require_admin),
):
    _ensure_running()
    ok, msg = cs.add_decision(
        ip=payload.ip,
        duration=payload.duration,
        reason=payload.reason,
        decision_type=payload.type,
    )
    log_audit(
        db, user=user, category="crowdsec", action="add_decision",
        target=payload.ip, after={"duration": payload.duration,
                                  "reason": payload.reason, "type": payload.type},
        request=request, success=ok, error=None if ok else msg,
    )
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"ip": payload.ip, "status": msg}


@router.delete("/crowdsec/decisions/by-id/{decision_id}")
async def delete_decision_by_id(
    decision_id: int,
    request:     Request,
    db:          Session = Depends(get_db),
    user:        dict    = Depends(require_admin),
):
    _ensure_running()
    ok, msg = cs.delete_decision_by_id(decision_id)
    log_audit(
        db, user=user, category="crowdsec", action="delete_decision",
        target=str(decision_id), request=request, success=ok,
        error=None if ok else msg,
    )
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"id": decision_id, "status": msg}


@router.delete("/crowdsec/decisions/by-ip/{ip}")
async def delete_decision_by_ip(
    ip:       str,
    request:  Request,
    db:       Session = Depends(get_db),
    user:     dict    = Depends(require_admin),
):
    _ensure_running()
    ok, msg = cs.delete_decision_by_ip(ip)
    log_audit(
        db, user=user, category="crowdsec", action="delete_decision_by_ip",
        target=ip, request=request, success=ok, error=None if ok else msg,
    )
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"ip": ip, "status": msg}


# ─────────────────────────────────────────────────────────────────────────────
# Alertas
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/crowdsec/alerts", response_model=List[CrowdsecAlert])
async def list_alerts(
    limit: int = 50,
    _:     dict = Depends(require_admin),
):
    _ensure_running()
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit fuera de rango (1-500)")
    return cs.list_alerts(limit=limit)


# ─────────────────────────────────────────────────────────────────────────────
# Bouncers
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/crowdsec/bouncers", response_model=List[CrowdsecBouncer])
async def list_bouncers(_: dict = Depends(require_admin)):
    _ensure_running()
    return cs.list_bouncers()


# ─────────────────────────────────────────────────────────────────────────────
# Colecciones
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/crowdsec/collections", response_model=List[CrowdsecCollection])
async def list_collections(_: dict = Depends(require_admin)):
    _ensure_running()
    return cs.list_collections()


# ─────────────────────────────────────────────────────────────────────────────
# Escenarios (reglas de detección concretas; incluye los sueltos que no van en
# ninguna colección, p. ej. http-bf-wordpress_bf_xmlrpc)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/crowdsec/scenarios", response_model=List[CrowdsecScenario])
async def list_scenarios(_: dict = Depends(require_admin)):
    _ensure_running()
    return cs.list_scenarios()


# ─────────────────────────────────────────────────────────────────────────────
# Métricas
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/crowdsec/metrics")
async def metrics(_: dict = Depends(require_admin)):
    _ensure_running()
    return cs.metrics_summary()
