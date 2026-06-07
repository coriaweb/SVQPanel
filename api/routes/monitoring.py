"""
Rutas API de monitorización: histórico de métricas, configuración de alertas y
eventos de alerta.

- GET  /monitoring/history?range=24h|7d|30d  → series temporales agregadas
- GET  /monitoring/alerts/config             → config de alertas
- PUT  /monitoring/alerts/config             → actualizar config (toggles/umbrales)
- GET  /monitoring/alerts/events             → alertas recientes (abiertas/cerradas)
- POST /monitoring/alerts/test               → enviar email de prueba de alerta
"""

from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from api.models.database import get_db
from api.models.models_metrics import MetricSample, AlertConfig, AlertEvent
from api.dependencies import require_admin

router = APIRouter()


# ── Histórico de métricas ─────────────────────────────────────────────────

# Configuración de cada rango: ventana y tamaño del "bucket" de agregación.
_RANGES = {
    "24h": (timedelta(hours=24), timedelta(minutes=5)),    # detalle 5 min
    "7d":  (timedelta(days=7),   timedelta(hours=1)),      # agregado por hora
    "30d": (timedelta(days=30),  timedelta(hours=6)),      # agregado cada 6h
}


@router.get("/monitoring/history")
async def metrics_history(
    range: str = Query("24h", pattern="^(24h|7d|30d)$"),
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Devuelve series temporales agregadas para el rango pedido. Agrega las
    muestras en buckets (media por bucket) para no devolver miles de puntos.
    """
    window, bucket = _RANGES[range]
    since = datetime.utcnow() - window

    samples = (
        db.query(MetricSample)
        .filter(MetricSample.ts >= since)
        .order_by(MetricSample.ts.asc())
        .all()
    )

    # Agrupar por bucket
    bucket_secs = bucket.total_seconds()
    buckets = {}
    prev_net = None
    for s in samples:
        b = int(s.ts.timestamp() // bucket_secs) * int(bucket_secs)
        agg = buckets.setdefault(b, {
            "ts": b, "cpu": [], "ram": [], "disk": [],
            "load": [], "rx_rate": [], "tx_rate": [],
        })
        agg["cpu"].append(s.cpu_percent)
        agg["ram"].append(s.ram_percent)
        agg["disk"].append(s.disk_percent)
        agg["load"].append(s.load_5)
        # Tasa de red entre muestras consecutivas (bytes/s)
        if prev_net is not None:
            dt = (s.ts - prev_net["ts"]).total_seconds()
            if dt > 0:
                rx = max(0, s.net_rx_bytes - prev_net["rx"]) / dt
                tx = max(0, s.net_tx_bytes - prev_net["tx"]) / dt
                agg["rx_rate"].append(rx)
                agg["tx_rate"].append(tx)
        prev_net = {"ts": s.ts, "rx": s.net_rx_bytes, "tx": s.net_tx_bytes}

    def avg(lst):
        return round(sum(lst) / len(lst), 2) if lst else 0.0

    points = []
    for b in sorted(buckets):
        agg = buckets[b]
        points.append({
            "ts": datetime.utcfromtimestamp(agg["ts"]).isoformat() + "Z",
            "cpu": avg(agg["cpu"]),
            "ram": avg(agg["ram"]),
            "disk": avg(agg["disk"]),
            "load": avg(agg["load"]),
            "rx_mbps": round(avg(agg["rx_rate"]) * 8 / 1_000_000, 3),  # bytes/s → Mbps
            "tx_mbps": round(avg(agg["tx_rate"]) * 8 / 1_000_000, 3),
        })

    return {"range": range, "points": points, "count": len(points)}


# ── Configuración de alertas ──────────────────────────────────────────────

def _get_cfg(db) -> AlertConfig:
    cfg = db.query(AlertConfig).first()
    if cfg is None:
        cfg = AlertConfig(id=1)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


class AlertConfigUpdate(BaseModel):
    notify_email:    Optional[str]  = None
    disk_enabled:    Optional[bool] = None
    disk_warn_pct:   Optional[int]  = None
    disk_crit_pct:   Optional[int]  = None
    service_enabled: Optional[bool] = None
    service_watch:   Optional[str]  = None
    load_enabled:    Optional[bool] = None
    load_factor:     Optional[float]= None
    ram_warn_pct:    Optional[int]  = None
    ssl_enabled:     Optional[bool] = None
    ssl_days_before: Optional[int]  = None


def _cfg_dict(cfg: AlertConfig) -> dict:
    return {
        "notify_email":    cfg.notify_email or "",
        "disk_enabled":    cfg.disk_enabled,
        "disk_warn_pct":   cfg.disk_warn_pct,
        "disk_crit_pct":   cfg.disk_crit_pct,
        "service_enabled": cfg.service_enabled,
        "service_watch":   cfg.service_watch or "",
        "load_enabled":    cfg.load_enabled,
        "load_factor":     cfg.load_factor,
        "ram_warn_pct":    cfg.ram_warn_pct,
        "ssl_enabled":     cfg.ssl_enabled,
        "ssl_days_before": cfg.ssl_days_before,
    }


@router.get("/monitoring/alerts/config")
async def get_alerts_config(current_user=Depends(require_admin), db: Session = Depends(get_db)):
    return _cfg_dict(_get_cfg(db))


@router.put("/monitoring/alerts/config")
async def update_alerts_config(
    data: AlertConfigUpdate,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    cfg = _get_cfg(db)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(cfg, field, value)
    db.commit()
    db.refresh(cfg)
    return _cfg_dict(cfg)


# ── Eventos de alerta ─────────────────────────────────────────────────────

@router.get("/monitoring/alerts/events")
async def list_alert_events(
    only_open: bool = False,
    limit: int = Query(50, ge=1, le=200),
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Lista los eventos de alerta más recientes (abiertos primero)."""
    q = db.query(AlertEvent)
    if only_open:
        q = q.filter(AlertEvent.resolved_at.is_(None))
    events = q.order_by(AlertEvent.created_at.desc()).limit(limit).all()
    return [{
        "id": e.id, "kind": e.kind, "level": e.level, "target": e.target,
        "message": e.message,
        "created_at": e.created_at.isoformat() + "Z" if e.created_at else None,
        "resolved_at": e.resolved_at.isoformat() + "Z" if e.resolved_at else None,
        "open": e.resolved_at is None,
        "email_sent": e.email_sent,
    } for e in events]


@router.post("/monitoring/alerts/test")
async def test_alert_email(current_user=Depends(require_admin), db: Session = Depends(get_db)):
    """Envía un email de prueba al destino de alertas para validar la entrega."""
    from scripts.alerts_manager import _notify_email
    ok = _notify_email(
        db,
        "[SVQPanel] Prueba de alerta",
        "Esto es un email de prueba del sistema de alertas de SVQPanel.\n"
        "Si lo recibes, las alertas de monitorización se entregarán correctamente.\n",
    )
    if not ok:
        raise HTTPException(
            400,
            "No se pudo enviar. Comprueba que el SMTP del panel está configurado "
            "(Configuración → Email) y que hay un email de destino.",
        )
    return {"status": "success"}
