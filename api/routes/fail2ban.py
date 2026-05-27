"""
Rutas API — Fail2ban — Fase 12.3
"""

import logging
from typing import List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from api.models.database import get_db
from api.models.models_security import BannedIp
from api.schemas.security_schemas import (
    JailStatus,
    BannedIpResponse,
    UnbanRequest,
    ManualBanRequest,
    WhitelistF2BRequest,
)
from api.dependencies import require_admin
from api.utils import fail2ban_helper as f2b
from api.utils.security_audit import log_audit

router = APIRouter()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Jails
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/fail2ban/status")
async def f2b_overall_status(_: dict = Depends(require_admin)):
    running = f2b.is_running()
    return {
        "running":     running,
        "jails":       f2b.list_jails() if running else [],
        "ignoreip":    f2b.get_ignoreip(),
    }


@router.get("/fail2ban/jails", response_model=List[JailStatus])
async def list_jails(_: dict = Depends(require_admin)):
    if not f2b.is_running():
        raise HTTPException(status_code=503, detail="fail2ban no está corriendo")
    out: List[JailStatus] = []
    for jail in f2b.list_jails():
        status = f2b.jail_status(jail)
        if not status:
            continue
        out.append(
            JailStatus(
                name              = jail,
                enabled           = True,
                currently_failed  = status["currently_failed"],
                total_failed      = status["total_failed"],
                currently_banned  = status["currently_banned"],
                total_banned      = status["total_banned"],
                file_list         = status["file_list"],
            )
        )
    return out


@router.post("/fail2ban/jails/{jail}/toggle")
async def toggle_jail(
    jail:    str,
    enabled: bool,
    request: Request,
    db:      Session = Depends(get_db),
    user:    dict    = Depends(require_admin),
):
    ok, msg = f2b.jail_set_enabled(jail, enabled)
    log_audit(
        db, user=user, category="fail2ban",
        action="enable_jail" if enabled else "disable_jail",
        target=jail, request=request, success=ok, error=None if ok else msg,
    )
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"jail": jail, "enabled": enabled}


# ─────────────────────────────────────────────────────────────────────────────
# Banned IPs
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/fail2ban/banned", response_model=List[BannedIpResponse])
async def list_banned(_: dict = Depends(require_admin)):
    """
    Junta las IPs baneadas vivas (consultando fail2ban-client) con las
    entradas BannedIp manuales activas en la BD.
    """
    out: List[BannedIpResponse] = []
    seen = set()

    if f2b.is_running():
        for jail in f2b.list_jails():
            status = f2b.jail_status(jail) or {}
            for ip in status.get("banned_ips", []):
                key = (ip, jail)
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    BannedIpResponse(
                        ip        = ip,
                        jail      = jail,
                        banned_by = "fail2ban",
                    )
                )
    return out


@router.post("/fail2ban/unban")
async def unban_ip(
    payload: UnbanRequest,
    request: Request,
    db:      Session = Depends(get_db),
    user:    dict    = Depends(require_admin),
):
    if payload.jail:
        ok, msg = f2b.unban(payload.jail, payload.ip)
        results = {payload.jail: msg if ok else f"error: {msg}"}
    else:
        results = f2b.unban_all_jails(payload.ip)
        ok = all(not v.startswith("error") for v in results.values())

    # Marcar como desbaneado en BD si hay registro
    rows = (
        db.query(BannedIp)
        .filter(BannedIp.ip == payload.ip, BannedIp.unbanned_at.is_(None))
        .all()
    )
    for r in rows:
        r.unbanned_at = datetime.utcnow()
    db.commit()

    log_audit(
        db, user=user, category="fail2ban", action="unban",
        target=payload.ip, after=results, request=request, success=ok,
    )
    return {"ip": payload.ip, "results": results}


@router.post("/fail2ban/ban")
async def manual_ban(
    payload: ManualBanRequest,
    request: Request,
    db:      Session = Depends(get_db),
    user:    dict    = Depends(require_admin),
):
    """
    Ban manual: lo registra en BD y mete la IP en el set f2b_v4/v6 de nftables.
    No usa fail2ban-client porque queremos control fino del timeout y de la
    fuente de verdad.
    """
    import ipaddress
    from api.utils import nftables_helper as nft

    try:
        ip_obj = ipaddress.ip_address(payload.ip)
    except ValueError:
        raise HTTPException(status_code=400, detail="IP inválida")

    set_name = "f2b_v6" if ip_obj.version == 6 else "f2b_v4"
    timeout_clause = ""
    if payload.duration_seconds:
        timeout_clause = f" timeout {payload.duration_seconds}s"

    ok, msg = nft.nft_set_add_element(set_name, f"{payload.ip}{timeout_clause}")

    record = BannedIp(
        ip         = payload.ip,
        banned_by  = "manual",
        reason     = payload.reason,
        banned_at  = datetime.utcnow(),
        expires_at = (
            datetime.utcnow() + timedelta(seconds=payload.duration_seconds)
            if payload.duration_seconds else None
        ),
    )
    db.add(record)
    db.commit()

    log_audit(
        db, user=user, category="fail2ban", action="manual_ban",
        target=payload.ip, after={"set": set_name, "duration": payload.duration_seconds,
                                  "reason": payload.reason, "result": msg},
        request=request, success=ok, error=None if ok else msg,
    )

    if not ok:
        raise HTTPException(status_code=500, detail=f"nft falló: {msg}")
    return {"ip": payload.ip, "banned_until": record.expires_at}


# ─────────────────────────────────────────────────────────────────────────────
# Whitelist permanente (ignoreip)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/fail2ban/whitelist")
async def get_whitelist(_: dict = Depends(require_admin)):
    return {"ignoreip": f2b.get_ignoreip()}


@router.post("/fail2ban/whitelist")
async def add_whitelist(
    payload: WhitelistF2BRequest,
    request: Request,
    db:      Session = Depends(get_db),
    user:    dict    = Depends(require_admin),
):
    ok, msg = f2b.add_to_ignoreip(payload.ip)
    log_audit(
        db, user=user, category="fail2ban", action="add_ignoreip",
        target=payload.ip, request=request, success=ok, error=None if ok else msg,
    )
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"ip": payload.ip, "status": msg}


@router.delete("/fail2ban/whitelist/{ip}")
async def remove_whitelist(
    ip:      str,
    request: Request,
    db:      Session = Depends(get_db),
    user:    dict    = Depends(require_admin),
):
    ok, msg = f2b.remove_from_ignoreip(ip)
    log_audit(
        db, user=user, category="fail2ban", action="remove_ignoreip",
        target=ip, request=request, success=ok, error=None if ok else msg,
    )
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"ip": ip, "status": msg}
