"""
Consumo de CPU y RAM por dominio (su pool PHP-FPM).

  GET /api/domains/{id}/resources?range=24h|7d|30d  → serie + resumen + ahora mismo
  GET /api/resources/top?range=24h|7d|30d           → (admin) dominios que más consumen

La CPU se da en % del servidor entero (como la gráfica de Monitorización): un
proceso PHP a tope en un servidor de 4 núcleos es un 25%. Los datos los recoge
scripts/domain_resources.py en buckets de 5 min; un bucket sin fila = 0.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.dependencies import require_admin, require_auth
from api.models.database import get_db
from api.models.models_domain import Domain
from api.models.models_domain_resources import DomainResourceSample
from api.models.models_user import User
from scripts import domain_resources as dr

router = APIRouter()

SLOT = dr.FLUSH_SECONDS
_RANGES = {   # (ventana, bucket) en segundos, igual que /monitoring/history
    "24h": (24 * 3600, 300),
    "7d":  (7 * 86400, 3600),
    "30d": (30 * 86400, 6 * 3600),
}


def _cpu_pct(cpu_seconds: float, seconds: float) -> float:
    if seconds <= 0:
        return 0.0
    return round(cpu_seconds / seconds / dr._NCPU * 100, 2)


def _window(range_: str):
    window, bucket = _RANGES[range_]
    # Fin = último bucket de 5 min ya guardado (el que está en curso aún no tiene fila)
    end = int(datetime.utcnow().timestamp() // SLOT) * SLOT
    start = -(-(end - window) // bucket) * bucket   # primer límite de bucket dentro de la ventana
    return start, end, bucket


def build_series(rows, start: int, end: int, bucket: int) -> dict:
    """rows: DomainResourceSample de un dominio dentro de [start, end).
    Agrega en buckets rellenando con 0 y calcula el resumen del periodo."""
    agg = {}
    for r in rows:
        t = int(r.ts.timestamp()) if r.ts.tzinfo else int((r.ts - datetime(1970, 1, 1)).total_seconds())
        b = t // bucket * bucket
        a = agg.setdefault(b, {"cpu": 0.0, "mem": 0.0, "mem_max": 0.0, "procs": 0, "hits": 0})
        a["cpu"] += r.cpu_seconds or 0
        a["mem"] += r.mem_avg_mb or 0
        a["mem_max"] = max(a["mem_max"], r.mem_max_mb or 0)
        a["procs"] = max(a["procs"], r.procs_max or 0)
        a["hits"] += r.maxchildren_hits or 0

    points = []
    for b in range(start, end, bucket):
        span = min(bucket, end - b)          # el último bucket puede ir a medias
        a = agg.get(b, {"cpu": 0.0, "mem": 0.0, "mem_max": 0.0, "procs": 0, "hits": 0})
        points.append({
            "ts": datetime.utcfromtimestamp(b).isoformat() + "Z",
            "cpu": _cpu_pct(a["cpu"], span),
            "mem": round(a["mem"] / max(1, span // SLOT), 1),
            "mem_max": a["mem_max"],
            "procs": a["procs"],
            "hits": a["hits"],
        })

    total = end - start
    cpu_total = sum(r.cpu_seconds or 0 for r in rows)
    summary = {
        "cpu_seconds": round(cpu_total, 1),
        "cpu_avg": _cpu_pct(cpu_total, total),
        "cpu_peak": max((_cpu_pct(r.cpu_seconds or 0, SLOT) for r in rows), default=0.0),
        "mem_avg": round(sum(r.mem_avg_mb or 0 for r in rows) / max(1, total // SLOT), 1),
        "mem_peak": max((r.mem_max_mb or 0 for r in rows), default=0.0),
        "procs_peak": max((r.procs_max or 0 for r in rows), default=0),
        "hits": sum(r.maxchildren_hits or 0 for r in rows),
    }
    return {"points": points, "summary": summary}


def _rows(db: Session, domain_id: int, start: int, end: int):
    return (db.query(DomainResourceSample)
              .filter(DomainResourceSample.domain_id == domain_id,
                      DomainResourceSample.ts >= datetime.utcfromtimestamp(start),
                      DomainResourceSample.ts < datetime.utcfromtimestamp(end))
              .order_by(DomainResourceSample.ts).all())


@router.get("/domains/{domain_id}/resources")
def domain_resources(domain_id: int,
                     range: str = Query("24h", pattern="^(24h|7d|30d)$"),
                     current_user: User = Depends(require_auth),
                     db: Session = Depends(get_db)):
    from api.routes.domains import _get_owned_domain, _fpm_tuning_of
    from scripts import php_ini_manager as phpini

    domain = _get_owned_domain(domain_id, db, current_user)
    start, end, bucket = _window(range)
    data = build_series(_rows(db, domain.id, start, end), start, end, bucket)
    tuning = _fpm_tuning_of(domain)
    eff = phpini.resolve_fpm_tuning(tuning)
    return {
        "range": range,
        "bucket_seconds": bucket,
        "cores": dr._NCPU,
        **data,
        "live": dr.sampler.live_for(domain.domain_name),
        "pool": {"preset": (tuning or {}).get("preset") or phpini.FPM_DEFAULT_PRESET,
                 "pm": eff.get("pm"), "max_children": eff.get("pm.max_children")},
    }


@router.get("/resources/top")
def top_consumers(range: str = Query("24h", pattern="^(24h|7d|30d)$"),
                  limit: int = Query(20, ge=1, le=200),
                  current_user: User = Depends(require_admin),
                  db: Session = Depends(get_db)):
    start, end, _ = _window(range)
    S = DomainResourceSample
    q = (db.query(S.domain_id,
                  func.sum(S.cpu_seconds), func.sum(S.mem_avg_mb), func.max(S.mem_max_mb),
                  func.max(S.procs_max), func.sum(S.maxchildren_hits))
           .filter(S.ts >= datetime.utcfromtimestamp(start), S.ts < datetime.utcfromtimestamp(end))
           .group_by(S.domain_id)
           .order_by(func.sum(S.cpu_seconds).desc())
           .limit(limit).all())
    ids = [r[0] for r in q]
    doms = {d.id: d for d in db.query(Domain).filter(Domain.id.in_(ids)).all()} if ids else {}
    owners = ({u.id: u.username for u in db.query(User).filter(
                  User.id.in_({d.user_id for d in doms.values()})).all()} if doms else {})
    total, slots = end - start, max(1, (end - start) // SLOT)
    out = []
    for did, cpu, mem_sum, mem_max, procs, hits in q:
        d = doms.get(did)
        if not d:
            continue
        out.append({
            "domain_id": did, "domain": d.domain_name, "owner": owners.get(d.user_id, ""),
            "cpu_seconds": round(cpu or 0, 1), "cpu_avg": _cpu_pct(cpu or 0, total),
            "mem_avg": round((mem_sum or 0) / slots, 1), "mem_peak": mem_max or 0,
            "procs_peak": procs or 0, "hits": int(hits or 0),
            "live": dr.sampler.live_for(d.domain_name),
        })
    return {"range": range, "cores": dr._NCPU, "domains": out}
