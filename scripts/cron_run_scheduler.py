"""
Hilo interno que ingiere la cola de ejecuciones de cron (cron_runner.ingest_queue)
y la vuelca a la BD. Patrón idéntico al metrics_scheduler: un daemon thread que
despierta cada INTERVAL segundos. Evita un timer systemd extra.
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)

INTERVAL = 30  # segundos entre barridos de la cola
_started = False


def _loop():
    from scripts.cron_runner import ingest_queue
    while True:
        try:
            n = ingest_queue()
            if n:
                logger.info(f"cron-runs ingeridos: {n}")
        except Exception as e:
            logger.warning(f"ingest_queue falló: {e}")
        time.sleep(INTERVAL)


def start_cron_run_scheduler():
    global _started
    if _started:
        return
    _started = True
    t = threading.Thread(target=_loop, name="cron-run-ingestor", daemon=True)
    t.start()
