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
# Aplicación a nftables en SEGUNDO PLANO con coalescing (debounce)
#
# Aplicar listas IP a nftables es lento (descarga + parseo + reload). Si el
# usuario bloquea/desbloquea varios países seguidos, no queremos bloquear cada
# clic ni lanzar N reloads en paralelo. En su lugar:
#   - cada cambio marca "hay trabajo pendiente" y responde al instante;
#   - un único hilo de fondo espera una pequeña pausa (coalescing) y entonces
#     aplica el estado actual de TODAS las listas una sola vez;
#   - si llegan más cambios mientras espera, reinicia la pausa (así 10 clics
#     seguidos = 1 sola aplicación al final).
# ─────────────────────────────────────────────────────────────────────────────
import threading

_apply_lock = threading.Lock()
_apply_timer: Optional[threading.Timer] = None
_apply_state = {
    "applying": False,      # hay una aplicación en curso
    "pending":  False,      # hay cambios esperando a aplicarse
    "last_error": None,     # error de la última aplicación (o None)
    "last_applied_at": None,
}
_COALESCE_SECONDS = 1.5     # espera tras el último cambio antes de aplicar


def _do_background_apply():
    """Aplica el estado actual de las listas a nftables. Corre en un hilo."""
    from api.models.database import SessionLocal
    with _apply_lock:
        _apply_state["applying"] = True
        _apply_state["pending"] = False
    db = SessionLocal()
    try:
        enabled = db.query(IpList).filter(IpList.enabled.is_(True)).all()
        active_tuples = []
        for il in enabled:
            v4, v6, err = ip_list_fetcher.refresh_one(il)
            db.commit()
            # refresh_one ya devuelve los CIDRs parseados tanto si la lista cambió
            # como si está "unchanged" (antes había que re-descargar aquí; se
            # eliminó la doble descarga). Solo saltamos si hubo un error real.
            if err and err != "unchanged":
                logger.warning(f"iplist {il.name}: refresh falló: {err}")
                continue
            active_tuples.append((il, v4, v6))

        content = ip_list_fetcher.regenerate_iplists_nft(active_tuples)
        ip_list_fetcher.write_iplists_nft(content)
        ok, msg = nft.reload_nftables()
        with _apply_lock:
            _apply_state["last_error"] = None if ok else msg
            _apply_state["last_applied_at"] = datetime.utcnow().isoformat()
        if not ok:
            logger.error(f"geo/iplist apply: reload nftables falló: {msg}")
    except Exception as e:
        logger.error(f"geo/iplist background apply error: {e}")
        with _apply_lock:
            _apply_state["last_error"] = str(e)
    finally:
        db.close()
        with _apply_lock:
            _apply_state["applying"] = False
            # ¿Llegaron cambios mientras aplicábamos? Reprograma otra pasada.
            if _apply_state["pending"]:
                _schedule_apply()


def _schedule_apply():
    """Programa (o reprograma) una aplicación en background con debounce."""
    global _apply_timer
    with _apply_lock:
        _apply_state["pending"] = True
        if _apply_timer is not None:
            _apply_timer.cancel()
        _apply_timer = threading.Timer(_COALESCE_SECONDS, _do_background_apply)
        _apply_timer.daemon = True
        _apply_timer.start()


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
        # refresh_one devuelve los CIDRs tanto si cambió como si está "unchanged"
        # (ya no re-descargamos aquí). Solo saltamos ante un error real.
        if err and err != "unchanged":
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


# ─────────────────────────────────────────────────────────────────────────────
# Bloqueo geográfico (por país) — atajo sobre el sistema de listas IP
# ─────────────────────────────────────────────────────────────────────────────
from api.utils import country_blocklist as geo


@router.get("/firewall/geo/catalog")
async def geo_catalog(db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    """
    Catálogo de países bloqueables + cuáles están ya activos. La UI lo usa para
    mostrar los países con un toggle de "bloquear/desbloquear" por país.
    """
    existing = {il.name: il for il in db.query(IpList).all()}
    out = []
    for c in geo.catalog():
        il = existing.get(c["list_name"])
        out.append({
            **c,
            "blocked":     il is not None,
            "enabled":     bool(il.enabled) if il else False,
            "entry_count": (il.entry_count_v4 or 0) + (il.entry_count_v6 or 0) if il else 0,
            "last_error":  il.last_error if il else None,
        })
    return {"countries": out}


@router.post("/firewall/geo/{cc}/block")
async def geo_block(
    cc: str,
    request: Request,
    db:   Session = Depends(get_db),
    user: dict    = Depends(require_admin),
):
    """Bloquea un país: crea (si no existe) una lista IP 'block' con su zona CIDR."""
    cc = cc.lower()
    if not geo.is_valid_cc(cc):
        raise HTTPException(status_code=404, detail=f"País '{cc}' no está en el catálogo")

    country = geo.get_country(cc)
    name = geo.list_name_for(cc)

    il = db.query(IpList).filter(IpList.name == name).first()
    if il:
        # Ya existe: asegurar que está habilitada
        if not il.enabled:
            il.enabled = True
            db.commit()
            _schedule_apply()   # aplicar en segundo plano (respuesta inmediata)
        return {"status": "ok", "country": cc, "list": name, "already": True, "applying": True}

    url = geo.country_url(cc)
    ok, msg = ip_list_fetcher.url_resolves_safe(url)
    if not ok:
        raise HTTPException(status_code=400, detail=f"URL del país rechazada: {msg}")

    il = IpList(
        name=name,
        description=f"Geo-bloqueo: {country['name']} ({cc.upper()})",
        url=url,
        action="block",
        address_family="both",
        refresh_interval_hours=24,
        max_entries=500_000,
        enabled=True,
        created_by=user.id,
    )
    db.add(il)
    db.commit()
    log_audit(db, user=user, category="iplist", action="geo_block",
              target=f"{country['name']} ({cc})", request=request)

    # Registrado en BD → respondemos YA. La descarga + nftables va en background
    # (con coalescing: si bloqueas varios países seguidos, se aplica todo junto).
    _schedule_apply()
    return {"status": "ok", "country": cc, "list": name, "applying": True}


@router.post("/firewall/geo/{cc}/unblock")
async def geo_unblock(
    cc: str,
    request: Request,
    db:   Session = Depends(get_db),
    user: dict    = Depends(require_admin),
):
    """Desbloquea un país: elimina su lista IP geo_ y reaplica nftables."""
    cc = cc.lower()
    name = geo.list_name_for(cc)
    il = db.query(IpList).filter(IpList.name == name).first()
    if not il:
        return {"status": "ok", "country": cc, "removed": False}

    db.delete(il)
    db.commit()
    log_audit(db, user=user, category="iplist", action="geo_unblock",
              target=cc, request=request)

    _schedule_apply()   # reaplicar nftables en segundo plano
    return {"status": "ok", "country": cc, "removed": True, "applying": True}


@router.get("/firewall/geo/apply-status")
async def geo_apply_status(_: dict = Depends(require_admin)):
    """Estado de la aplicación a nftables en background (para que la UI muestre
    'aplicando…' y avise cuando termina o si hubo error)."""
    with _apply_lock:
        return {
            "applying":        _apply_state["applying"] or _apply_state["pending"],
            "last_error":      _apply_state["last_error"],
            "last_applied_at": _apply_state["last_applied_at"],
        }
