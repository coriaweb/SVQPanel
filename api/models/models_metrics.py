"""
Monitorización: histórico de métricas del sistema y configuración de alertas.

- MetricSample: una muestra periódica (cada ~5 min) de CPU/RAM/disco/load/red.
  Se purga lo más antiguo (retención 30 días) para mantener la tabla pequeña.
- AlertConfig: configuración (singleton) de las alertas por email, con toggle
  por cada tipo y los umbrales. Permite activar/desactivar cada alerta desde
  el panel.
- AlertEvent: registro de alertas disparadas (para no spamear y para histórico).
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, Text, Index
from datetime import datetime
from api.models.database import Base


class MetricSample(Base):
    """Una muestra puntual de métricas del sistema."""
    __tablename__ = "metric_samples"

    id          = Column(Integer, primary_key=True, index=True)
    ts          = Column(DateTime, default=datetime.utcnow, index=True)

    cpu_percent   = Column(Float, default=0.0)    # 0–100
    ram_percent   = Column(Float, default=0.0)    # 0–100
    ram_used_mb   = Column(Integer, default=0)
    ram_total_mb  = Column(Integer, default=0)
    disk_percent  = Column(Float, default=0.0)    # 0–100 (partición /)
    disk_used_gb  = Column(Float, default=0.0)
    disk_total_gb = Column(Float, default=0.0)
    load_1        = Column(Float, default=0.0)
    load_5        = Column(Float, default=0.0)
    load_15       = Column(Float, default=0.0)
    # Red: bytes acumulados desde el arranque; el front calcula la tasa entre muestras
    net_rx_bytes  = Column(Integer, default=0)
    net_tx_bytes  = Column(Integer, default=0)

    __table_args__ = (
        Index("ix_metric_samples_ts", "ts"),
    )


class AlertConfig(Base):
    """
    Configuración singleton de alertas por email. Un único registro (id=1).
    Cada alerta se puede activar/desactivar y ajustar su umbral.
    """
    __tablename__ = "alert_config"

    id = Column(Integer, primary_key=True, default=1)

    # Email destino de las alertas (si vacío, se usa el email del admin)
    notify_email = Column(String(255), nullable=True)

    # ── Disco lleno ──
    disk_enabled    = Column(Boolean, default=True)
    disk_warn_pct   = Column(Integer, default=85)   # aviso
    disk_crit_pct   = Column(Integer, default=95)   # crítico

    # ── Servicio caído ──
    service_enabled = Column(Boolean, default=True)
    # Lista de servicios a vigilar (CSV). Si vacío, se usa una lista por defecto.
    service_watch   = Column(Text, default="nginx,postgresql,php-fpm,postfix,dovecot")

    # ── Carga / RAM alta ──
    load_enabled    = Column(Boolean, default=True)
    load_factor     = Column(Float, default=1.5)    # alerta si load_5 > nCPU * factor
    ram_warn_pct    = Column(Integer, default=90)

    # ── SSL por expirar ──
    ssl_enabled     = Column(Boolean, default=True)
    ssl_days_before = Column(Integer, default=14)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AlertEvent(Base):
    """
    Una alerta disparada. Sirve para:
      - Deduplicar (no reenviar la misma alerta cada 5 min mientras persiste).
      - Histórico de incidencias en la UI.
    Cuando la condición se resuelve, se marca resolved_at.
    """
    __tablename__ = "alert_events"

    id          = Column(Integer, primary_key=True, index=True)
    kind        = Column(String(32), index=True)   # disk | service | load | ram | ssl
    level       = Column(String(16))               # warning | critical
    target      = Column(String(255), nullable=True)  # ej. nombre del servicio o dominio
    message     = Column(Text)
    dedup_key   = Column(String(128), index=True)  # ej. "disk:/" o "service:nginx"
    created_at  = Column(DateTime, default=datetime.utcnow, index=True)
    resolved_at = Column(DateTime, nullable=True)
    email_sent  = Column(Boolean, default=False)
