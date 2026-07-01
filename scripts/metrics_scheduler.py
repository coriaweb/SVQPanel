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
WP_ATTACK_SECONDS = 10800     # análisis de ataque WP (xmlrpc/wp-login): cada 3 horas
BOUNCER_HEALTH_SECONDS = 600  # salud del firewall-bouncer de CrowdSec: cada 10 min


def _loop():
    logger.info("Tareas periódicas del panel: scheduler iniciado")
    time.sleep(15)
    last_dns = 0.0
    last_license = 0.0
    last_disk = 0.0
    last_wp_attack = 0.0
    last_bouncer = 0.0
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
        # Análisis de ataque WP cada 3h: cachea los hits en BD para que la vista
        # admin lea de BD (instantáneo) sin escanear los access.log en vivo.
        if now - last_wp_attack >= WP_ATTACK_SECONDS:
            last_wp_attack = now
            try:
                _wp_attack_once()
            except Exception:
                logger.exception("Error en wp-attack-scan")
        # Salud del firewall-bouncer de CrowdSec cada 10 min: si CrowdSec tiene
        # decisiones pero el bouncer no las aplica al firewall (nftables), lo
        # reinicia. Detecta el fallo silencioso "banea en BD pero no en la red".
        if now - last_bouncer >= BOUNCER_HEALTH_SECONDS:
            last_bouncer = now
            try:
                _bouncer_health_once()
            except Exception:
                logger.exception("Error en bouncer-health")
        time.sleep(INTERVAL_SECONDS)


def _bouncer_health_once():
    """Detecta y repara el fallo SILENCIOSO del firewall-bouncer de CrowdSec:
    CrowdSec decide baneos pero el bouncer NO los aplica a nftables (típicamente
    porque un `flush ruleset` borró su tabla `ip crowdsec` y entra en bucle
    `netlink receive: no such file`). Efecto: detecta pero no bloquea → los
    ataques siguen pasando. Si se detecta, reinicia el bouncer (recrea la tabla
    y re-aplica todas las decisiones). Best-effort: si CrowdSec/bouncer no están
    instalados, no hace nada. Ver memoria svqpanel-crowdsec-bouncer-roto."""
    import subprocess

    def _sh(cmd):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            return r.returncode, (r.stdout or "")
        except Exception:
            return 1, ""

    # ¿está el bouncer instalado/activo? Si no, nada que vigilar.
    rc, _ = _sh(["systemctl", "is-active", "crowdsec-firewall-bouncer"])
    if rc != 0:
        return

    broken = False
    reason = ""

    # Señal 1 (inequívoca): errores netlink recientes en el log del bouncer.
    # El bouncer usa log_mode: file → /var/log/crowdsec-firewall-bouncer.log.
    try:
        with open("/var/log/crowdsec-firewall-bouncer.log", "r", errors="replace") as f:
            tail = f.readlines()[-200:]
        netlink_errs = sum(
            1 for ln in tail if "netlink receive: no such file" in ln
        )
        if netlink_errs >= 5:
            broken, reason = True, f"{netlink_errs} errores netlink en el log"
    except FileNotFoundError:
        pass

    # Señal 2 (corroboración): CrowdSec tiene decisiones pero la tabla nft del
    # bouncer no tiene IPs → no las está aplicando.
    if not broken:
        rc_d, out_d = _sh(["cscli", "decisions", "list", "-o", "raw"])
        n_decisions = max(0, len([l for l in out_d.splitlines() if l.strip()]) - 1)
        if rc_d == 0 and n_decisions > 0:
            # ¿cuántas IPs hay realmente en la tabla del bouncer?
            _, out_nft = _sh(["nft", "list", "table", "ip", "crowdsec"])
            has_elems = "elements = {" in out_nft
            if not has_elems:
                broken = True
                reason = f"{n_decisions} decisiones en CrowdSec pero 0 IPs en nft crowdsec"

    if not broken:
        return

    logger.warning(f"firewall-bouncer roto ({reason}) → reiniciando")
    _sh(["systemctl", "restart", "crowdsec-firewall-bouncer"])
    logger.info("firewall-bouncer reiniciado (health-check)")


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


def _wp_attack_once():
    """Refresca el cache de ataques WordPress (hits a xmlrpc/wp-login en 24h) de
    todos los dominios y lo persiste en BD. La vista admin de Seguridad lee esos
    valores cacheados en vez de escanear los access.log en vivo (que con 40+
    dominios era lento). Ventana/umbral por defecto del detector."""
    from scripts.wp_attack_detector import refresh_all_domains
    n = refresh_all_domains()
    logger.info("wp-attack-scan: ataques WP recalculados para %d dominio(s)", n)


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
