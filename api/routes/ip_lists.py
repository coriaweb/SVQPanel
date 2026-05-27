"""
Rutas API — Listas IP desde URL — Fase 12.4
"""

import logging
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from api.models.database import get_db
from api.models.models_security import IpList
from api.schemas.security_schemas import (
    IpListCreate,
    IpListUpdate,
    IpListResponse,
)
from api.dependencies import require_admin
from api.utils import ip_list_fetcher, nftables_helper as nft
from api.utils.security_audit import log_audit

router = APIRouter()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/firewall/ip-lists", response_model=List[IpListResponse])
async def list_iplists(db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    return db.query(IpList).order_by(IpList.created_at.desc()).all()


@router.post(
    "/firewall/ip-lists",
    response_model=IpListResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_iplist(
    payload: IpListCreate,
    request: Request,
    db:      Session = Depends(get_db),
    user:    dict    = Depends(require_admin),
):
    # Comprobar nombre único
    if db.query(IpList).filter(IpList.name == payload.name).first():
        raise HTTPException(status_code=409, detail=f"Ya existe una lista con name='{payload.name}'")

    # Validar URL (SSRF guard)
    ok, msg = ip_list_fetcher.url_resolves_safe(payload.url)
    if not ok:
        raise HTTPException(status_code=400, detail=f"URL rechazada: {msg}")

    il = IpList(**payload.model_dump(), created_by=user.id)
    db.add(il)
    db.commit()
    db.refresh(il)

    log_audit(db, user=user, category="iplist", action="create",
              target=il.name, after=il, request=request)

    # Primer fetch + apply
    _refresh_and_apply(db, request, user)
    db.refresh(il)
    return il


@router.put("/firewall/ip-lists/{iplist_id}", response_model=IpListResponse)
async def update_iplist(
    iplist_id: int,
    payload:   IpListUpdate,
    request:   Request,
    db:        Session = Depends(get_db),
    user:      dict    = Depends(require_admin),
):
    il = db.query(IpList).filter(IpList.id == iplist_id).first()
    if not il:
        raise HTTPException(status_code=404, detail="Lista no encontrada")

    before = {c.name: getattr(il, c.name) for c in il.__table__.columns}

    data = payload.model_dump(exclude_unset=True)
    # Validar URL si la cambian
    if "url" in data:
        ok, msg = ip_list_fetcher.url_resolves_safe(data["url"])
        if not ok:
            raise HTTPException(status_code=400, detail=f"URL rechazada: {msg}")
        # invalidar sha para forzar refetch
        il.sha256_last = None

    for k, v in data.items():
        setattr(il, k, v)
    db.commit()
    db.refresh(il)

    log_audit(db, user=user, category="iplist", action="update",
              target=il.name, before=before, after=il, request=request)

    _refresh_and_apply(db, request, user)
    db.refresh(il)
    return il


@router.delete("/firewall/ip-lists/{iplist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_iplist(
    iplist_id: int,
    request:   Request,
    db:        Session = Depends(get_db),
    user:      dict    = Depends(require_admin),
):
    il = db.query(IpList).filter(IpList.id == iplist_id).first()
    if not il:
        raise HTTPException(status_code=404, detail="Lista no encontrada")

    snapshot = {c.name: getattr(il, c.name) for c in il.__table__.columns}
    db.delete(il)
    db.commit()

    log_audit(db, user=user, category="iplist", action="delete",
              target=snapshot.get("name"), before=snapshot, request=request)

    _refresh_and_apply(db, request, user)


# ─────────────────────────────────────────────────────────────────────────────
# Refresh / preview
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/firewall/ip-lists/{iplist_id}/refresh")
async def refresh_iplist(
    iplist_id: int,
    request:   Request,
    db:        Session = Depends(get_db),
    user:      dict    = Depends(require_admin),
):
    il = db.query(IpList).filter(IpList.id == iplist_id).first()
    if not il:
        raise HTTPException(status_code=404, detail="Lista no encontrada")

    # Forzar refetch invalidando sha
    il.sha256_last = None
    db.commit()

    _refresh_and_apply(db, request, user)
    db.refresh(il)
    return {
        "id":              il.id,
        "name":            il.name,
        "entry_count_v4":  il.entry_count_v4,
        "entry_count_v6":  il.entry_count_v6,
        "last_fetched_at": il.last_fetched_at,
        "last_success_at": il.last_success_at,
        "last_error":      il.last_error,
    }


@router.get("/firewall/ip-lists/{iplist_id}/preview")
async def preview_iplist(
    iplist_id: int,
    limit:     int = 50,
    db:        Session = Depends(get_db),
    _:         dict    = Depends(require_admin),
):
    """Descarga la URL y devuelve las primeras N entradas válidas — debug."""
    il = db.query(IpList).filter(IpList.id == iplist_id).first()
    if not il:
        raise HTTPException(status_code=404, detail="Lista no encontrada")

    try:
        text, _ = ip_list_fetcher.fetch_url(il.url)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    v4, v6, errors = ip_list_fetcher.parse_list_content(text, max_entries=il.max_entries)
    return {
        "ipv4_sample": v4[:limit],
        "ipv6_sample": v6[:limit],
        "ipv4_total":  len(v4),
        "ipv6_total":  len(v6),
        "errors":      errors[:20],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helper interno: refetch all + regen + reload
# ─────────────────────────────────────────────────────────────────────────────
def _refresh_and_apply(db: Session, request: Request, user) -> None:
    """
    Refetcha todas las listas habilitadas, regenera svqpanel-iplists.nft y
    recarga nftables. Usado al crear/editar/borrar/refresh manual.
    """
    enabled = db.query(IpList).filter(IpList.enabled.is_(True)).all()
    active_tuples = []
    for il in enabled:
        v4, v6, err = ip_list_fetcher.refresh_one(il)
        db.commit()
        if err == "unchanged":
            try:
                text, _ = ip_list_fetcher.fetch_url(il.url)
                v4, v6, _ = ip_list_fetcher.parse_list_content(text, il.max_entries)
            except Exception as e:
                logger.warning(f"iplist {il.name}: refetch unchanged falló: {e}")
                continue
        elif err:
            logger.warning(f"iplist {il.name}: refresh falló: {err}")
            continue
        active_tuples.append((il, v4, v6))

    content = ip_list_fetcher.regenerate_iplists_nft(active_tuples)
    ip_list_fetcher.write_iplists_nft(content)

    ok, msg = nft.reload_nftables()
    log_audit(db, user=user, category="iplist", action="apply",
              target=f"{len(active_tuples)} listas activas",
              request=request, success=ok, error=None if ok else msg)
    if not ok:
        raise HTTPException(status_code=500, detail=f"Reload nftables: {msg}")
