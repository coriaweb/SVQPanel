"""
Daemon de muestreo de métricas (hilo de fondo dentro del panel).

Sustituye al timer systemd svqpanel-metrics, que arrancaba un proceso Python
entero cada 5 min (~1.4s CPU + ruido en el log: Starting/Finished/Consumed +
"metrics sample: ..." cada vez). Este hilo corre DENTRO del proceso del panel,
toma una muestra cada 5 min y evalúa alertas, sin arrancar nada nuevo.

Como en backup_scheduler: load_all_models() a nivel de módulo (si no, la primera
query revienta con InvalidRequestError('CronJob'...) y el hilo muere en silencio),
e imports pesados una sola vez.
"""
import logging
import threading
import time

logger = logging.getLogger(__name__)

_started = False
_lock = threading.Lock()

# Cargar TODOS los modelos para resolver relationships por nombre (ver memoria
# svqpanel-load-all-models). Sin esto el hilo muere en su primera query.
from api.models.database import SessionLocal, load_all_models
load_all_models()

INTERVAL_SECONDS = 300  # 5 minutos


def _loop():
    logger.info("Metrics scheduler iniciado")
    # Primera muestra a los ~15s del arranque, luego cada INTERVAL_SECONDS.
    time.sleep(15)
    while True:
        try:
            _sample_once()
        except Exception:
            logger.exception("Error en metrics loop")
        time.sleep(INTERVAL_SECONDS)


def _sample_once():
    """Toma una muestra de métricas + evalúa alertas. Loguea en DEBUG para no
    ensuciar (antes era INFO cada 5 min)."""
    from scripts.metrics_collector import collect_sample
    from scripts.alerts_manager import evaluate_alerts
    from scripts.services_manager import get_system_stats

    db = SessionLocal()
    try:
        sample = collect_sample(db)
        logger.debug("metrics sample: cpu=%.1f%% ram=%.1f%% disk=%.1f%%",
                     sample.get("cpu_percent", 0), sample.get("ram_percent", 0),
                     sample.get("disk_percent", 0))
        fired = evaluate_alerts(db, get_system_stats())
        if fired:
            # Esto SÍ interesa verlo: se disparó una alerta.
            logger.warning("metrics: %d alertas nuevas disparadas", fired)
    finally:
        db.close()


def start_metrics_scheduler():
    """Arranca el hilo de muestreo (idempotente)."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    t = threading.Thread(target=_loop, daemon=True, name="metrics-scheduler")
    t.start()
    logger.info("Hilo metrics-scheduler arrancado")
