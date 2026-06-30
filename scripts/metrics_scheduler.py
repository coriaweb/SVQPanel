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

INTERVAL_SECONDS = 300        # métricas: cada 5 minutos
DNS_HEALTH_SECONDS = 600      # salud del cluster DNS: cada 10 minutos
LICENSE_SECONDS = 43200       # validación de licencia: cada 12 horas
DISK_USAGE_SECONDS = 43200    # peso en disco de los dominios: cada 12 horas


def _loop():
    logger.info("Tareas periódicas del panel: scheduler iniciado")
    time.sleep(15)
    last_dns = 0.0
    last_license = 0.0
    last_disk = 0.0
    while True:
        try:
            _sample_once()
        except Exception:
            logger.exception("Error en metrics loop")
        now = time.monotonic()
        # Salud del cluster DNS cada DNS_HEALTH_SECONDS (no en cada tick de 5 min)
        if now - last_dns >= DNS_HEALTH_SECONDS:
            last_dns = now
            try:
                _dns_health_once()
            except Exception:
                logger.exception("Error en dns-health")
        # Validación de licencia cada 12h (la primera, al arranque)
        if now - last_license >= LICENSE_SECONDS:
            last_license = now
            try:
                _license_check_once()
            except Exception:
                logger.exception("Error en license-check")
        # Peso en disco de los dominios cada 12h (du es caro: NO en cada carga
        # de la lista; la vista lee el valor cacheado en BD).
        if now - last_disk >= DISK_USAGE_SECONDS:
            last_disk = now
            try:
                _disk_usage_once()
            except Exception:
                logger.exception("Error en disk-usage")
        time.sleep(INTERVAL_SECONDS)


def _disk_usage_once():
    """Recalcula y persiste el peso en disco de TODOS los dominios (du -sb por
    dominio). Caro pero infrecuente (2/día). La lista de dominios lee de BD, así
    que esta es la única vía que toca disco salvo el botón 'refrescar' manual.
    Salta los solo-correo/DNS (sin web)."""
    from api.models.models_domain import Domain
    from api.routes.domains import compute_domain_disk

    db = SessionLocal()
    try:
        domains = db.query(Domain).all()
        n = 0
        for d in domains:
            if getattr(d, "mail_dns_only", False):
                continue
            try:
                compute_domain_disk(d, db)
                n += 1
            except Exception:
                logger.exception("disk-usage: fallo en %s", d.domain_name)
        logger.info("disk-usage: peso recalculado para %d dominio(s)", n)
    finally:
        db.close()


def _license_check_once():
    """Revalida la licencia contra el servidor y persiste el estado en Settings
    (para que la UI lo lea sin red). Tolerante a fallos: si no hay red, mantiene
    el estado cacheado."""
    from datetime import datetime
    from scripts import license_client
    from api.models.models_settings import Settings

    result = license_client.validate(force=True)
    db = SessionLocal()
    try:
        s = db.query(Settings).filter(Settings.id == 1).first()
        if not s:
            s = Settings(id=1); db.add(s)
        s.license_valid = bool(result.get("valid"))
        s.license_plan = result.get("plan")
        s.license_reason = result.get("reason")
        exp = result.get("expires")
        if exp:
            try:
                s.license_expires = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            except Exception:
                s.license_expires = None
        s.license_checked_at = datetime.utcnow()
        db.commit()
        if not result.get("valid"):
            logger.warning("license: estado no válido (%s)", result.get("reason"))
    finally:
        db.close()


def _dns_health_once():
    """Comprueba la salud del cluster DNS. Si NO hay cluster configurado, no hace
    nada (antes el timer arrancaba Python cada 10 min solo para loguear 'nada que
    comprobar'). Persiste el estado y avisa a admins si hay problemas."""
    import json
    from datetime import datetime
    from scripts.dns_cluster import compute_cluster_health
    from api.models.models_settings import Settings

    db = SessionLocal()
    try:
        health = compute_cluster_health(db)
        if health is None:
            return  # sin cluster → silencio total
        s = db.query(Settings).filter(Settings.id == 1).first()
        if not s:
            s = Settings(id=1); db.add(s)
        s.dns_cluster_health_json = json.dumps(health)
        s.dns_cluster_health_at = datetime.utcnow()
        summary = health["summary"]
        # Reusar la lógica de avisos del CLI (no duplicar)
        from api.cli import _notify_all_admins
        if summary["master_down"]:
            _notify_all_admins(db, "danger", "Cluster DNS: master no responde",
                "El nameserver master (ns1) no responde a las consultas SOA.",
                dedup_key="dns_cluster_master_down")
        else:
            _notify_all_admins(db, None, "", "", "dns_cluster_master_down")
        if summary["slave_down"]:
            _notify_all_admins(db, "warning", "Cluster DNS: slave no responde",
                "El nameserver slave (ns2) no responde. Sin redundancia hasta que vuelva.",
                dedup_key="dns_cluster_slave_down")
        else:
            _notify_all_admins(db, None, "", "", "dns_cluster_slave_down")
        if summary["desync"]:
            desynced = [r["domain"] for r in health["rows"] if r["status"] == "desync"]
            sample = ", ".join(desynced[:5]) + ("…" if len(desynced) > 5 else "")
            _notify_all_admins(db, "warning",
                f"Cluster DNS: {summary['desync']} zona(s) desincronizada(s)",
                f"Zonas con distinto serial en ns1/ns2 vs panel: {sample}.",
                dedup_key="dns_cluster_desync")
        else:
            _notify_all_admins(db, None, "", "", "dns_cluster_desync")
        db.commit()
    finally:
        db.close()


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
