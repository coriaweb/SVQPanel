"""
Recolector de métricas del sistema para el histórico de monitorización.

Toma una muestra (CPU/RAM/disco/load/red) reutilizando get_system_stats()
y la guarda en la tabla metric_samples. Purga las muestras más antiguas que
RETENTION_DAYS para mantener la tabla pequeña.

Lo invoca el comando `python -m api.cli sample_metrics` desde un systemd timer
cada 5 minutos. No usa dependencias externas (lee de /proc como el resto del
panel).
"""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

RETENTION_DAYS = 30


def _read_net_totals() -> tuple[int, int]:
    """
    Suma los bytes rx/tx de todas las interfaces físicas (excluye lo/loopback)
    desde /proc/net/dev. Son contadores acumulados desde el arranque; el front
    calcula la tasa restando muestras consecutivas.
    """
    rx_total = tx_total = 0
    try:
        with open("/proc/net/dev") as f:
            for line in f:
                if ":" not in line:
                    continue
                iface, data = line.split(":", 1)
                iface = iface.strip()
                if iface == "lo" or iface.startswith(("veth", "docker", "br-")):
                    continue
                cols = data.split()
                if len(cols) >= 9:
                    rx_total += int(cols[0])   # bytes recibidos
                    tx_total += int(cols[8])   # bytes transmitidos
    except Exception as e:
        logger.warning(f"No se pudo leer /proc/net/dev: {e}")
    return rx_total, tx_total


def collect_sample(db) -> dict:
    """
    Toma una muestra de métricas y la guarda en metric_samples.
    Devuelve el dict de la muestra. No hace commit (lo hace el llamador) salvo
    que se pase un db; aquí sí commit para que el timer sea autónomo.
    """
    from scripts.services_manager import get_system_stats
    from api.models.models_metrics import MetricSample

    stats = get_system_stats()
    rx, tx = _read_net_totals()

    sample = MetricSample(
        ts=datetime.utcnow(),
        cpu_percent=float(stats.get("cpu_percent", 0.0)),
        ram_percent=float(stats.get("mem_percent", 0.0)),
        ram_used_mb=int(stats.get("mem_used_mb", 0)),
        ram_total_mb=int(stats.get("mem_total_mb", 0)),
        disk_percent=float(stats.get("disk_percent", 0.0)),
        disk_used_gb=float(stats.get("disk_used_gb", 0.0)),
        disk_total_gb=float(stats.get("disk_total_gb", 0.0)),
        load_1=float(stats.get("load_1", 0.0)),
        load_5=float(stats.get("load_5", 0.0)),
        load_15=float(stats.get("load_15", 0.0)),
        net_rx_bytes=rx,
        net_tx_bytes=tx,
    )
    db.add(sample)
    db.commit()

    # Purga de muestras antiguas
    cutoff = datetime.utcnow() - timedelta(days=RETENTION_DAYS)
    deleted = db.query(MetricSample).filter(MetricSample.ts < cutoff).delete()
    if deleted:
        db.commit()
        logger.info(f"Purgadas {deleted} muestras de métricas antiguas (>{RETENTION_DAYS}d)")

    return {
        "ts": sample.ts.isoformat(),
        "cpu_percent": sample.cpu_percent,
        "ram_percent": sample.ram_percent,
        "disk_percent": sample.disk_percent,
        "load_5": sample.load_5,
    }
