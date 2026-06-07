"""
Motor de alertas de monitorización.

Evalúa periódicamente (desde el timer de métricas) las condiciones de alerta
configuradas en AlertConfig y, cuando una se cumple, registra un AlertEvent y
envía un email (vía panel_mailer) a los admins. Con deduplicación: mientras la
condición persista no reenvía; cuando se resuelve, lo marca y la próxima vez
que vuelva a ocurrir avisará de nuevo.

Alertas soportadas (cada una se puede activar/desactivar en AlertConfig):
  - disk     : disco / por encima de warn/crit %
  - service  : un servicio vigilado no está activo
  - load/ram : carga del sistema o RAM por encima de umbral
  - ssl      : certificado de dominio expira en < N días

Las notificaciones también se crean in-app para los admins (campana del panel).
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Servicios por defecto a vigilar si no hay lista configurada
DEFAULT_SERVICES = ["nginx", "postgresql", "php-fpm", "postfix", "dovecot"]


def _get_or_create_alert_config(db):
    from api.models.models_metrics import AlertConfig
    cfg = db.query(AlertConfig).first()
    if cfg is None:
        cfg = AlertConfig(id=1)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def _notify_email(db, subject, body):
    """Envía el email de alerta al destino configurado (o al admin)."""
    try:
        from scripts.panel_mailer import send_panel_email
        from api.routes.settings import get_or_create_settings
        from api.models.models_user import User

        settings = get_or_create_settings(db)
        if not settings.panel_smtp_enabled:
            logger.info("SMTP del panel no activo; alerta solo in-app: %s", subject)
            return False

        cfg = _get_or_create_alert_config(db)
        to = (cfg.notify_email or "").strip()
        if not to:
            admin = db.query(User).filter(User.role == "admin", User.is_active == True).first()  # noqa: E712
            to = (admin.email if admin else "").strip()
        if not to or "@" not in to:
            logger.info("Sin email de destino para alertas")
            return False

        send_panel_email(db, to=to, subject=subject, body_text=body, settings=settings)
        return True
    except Exception as e:
        logger.warning("No se pudo enviar email de alerta: %s", e)
        return False


def _fire(db, kind, level, target, message, dedup_key):
    """
    Registra un AlertEvent si no hay uno abierto con el mismo dedup_key, y
    envía email + notificación in-app. Devuelve True si disparó (era nueva).
    """
    from api.models.models_metrics import AlertEvent

    existing = (
        db.query(AlertEvent)
        .filter(AlertEvent.dedup_key == dedup_key, AlertEvent.resolved_at.is_(None))
        .first()
    )
    if existing:
        return False  # ya avisado, no spamear

    ev = AlertEvent(
        kind=kind, level=level, target=target, message=message,
        dedup_key=dedup_key, created_at=datetime.utcnow(),
    )
    db.add(ev)
    db.commit()

    subject = f"[SVQPanel] {'⛔' if level == 'critical' else '⚠'} {message}"
    body = (
        f"Alerta de monitorización en tu servidor:\n\n"
        f"  {message}\n\n"
        f"  Tipo: {kind}\n  Nivel: {level}\n"
        f"  Cuándo: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        f"Revisa el panel para más detalles.\n"
    )
    ev.email_sent = _notify_email(db, subject, body)

    # Notificación in-app a admins
    try:
        from scripts.notify import create_notification
        from api.models.models_user import User
        admins = db.query(User).filter(User.role == "admin", User.is_active == True).all()  # noqa: E712
        for a in admins:
            create_notification(
                db, a.id,
                "danger" if level == "critical" else "warning",
                "Alerta del sistema", message, dedup_key=dedup_key,
            )
    except Exception as e:
        logger.warning("No se pudo crear notificación in-app: %s", e)

    db.commit()
    logger.info("Alerta disparada: %s (%s)", message, dedup_key)
    return True


def _resolve(db, dedup_key):
    """Marca como resuelta una alerta abierta (la condición ya no se cumple)."""
    from api.models.models_metrics import AlertEvent
    ev = (
        db.query(AlertEvent)
        .filter(AlertEvent.dedup_key == dedup_key, AlertEvent.resolved_at.is_(None))
        .first()
    )
    if ev:
        ev.resolved_at = datetime.utcnow()
        db.commit()
        # Limpiar la notificación in-app correspondiente
        try:
            from scripts.notify import clear_notification
            from api.models.models_user import User
            for a in db.query(User).filter(User.role == "admin").all():
                clear_notification(db, a.id, dedup_key)
        except Exception:
            pass


# ── Evaluadores de cada alerta ────────────────────────────────────────────

def _check_disk(db, cfg, stats):
    if not cfg.disk_enabled:
        return
    pct = float(stats.get("disk_percent", 0))
    key = "disk:/"
    if pct >= cfg.disk_crit_pct:
        _fire(db, "disk", "critical", "/",
              f"Disco al {pct:.0f}% (crítico, umbral {cfg.disk_crit_pct}%)", key)
    elif pct >= cfg.disk_warn_pct:
        _fire(db, "disk", "warning", "/",
              f"Disco al {pct:.0f}% (aviso, umbral {cfg.disk_warn_pct}%)", key)
    else:
        _resolve(db, key)


def _check_load_ram(db, cfg, stats):
    if not cfg.load_enabled:
        return
    ncpu = max(1, int(stats.get("cpu_count", 1)))
    load5 = float(stats.get("load_5", 0))
    threshold = ncpu * float(cfg.load_factor)
    key_load = "load:system"
    if load5 > threshold:
        _fire(db, "load", "warning", None,
              f"Carga alta: load_5={load5:.2f} > {threshold:.1f} ({ncpu} CPU × {cfg.load_factor})",
              key_load)
    else:
        _resolve(db, key_load)

    ram = float(stats.get("mem_percent", 0))
    key_ram = "ram:system"
    if ram >= cfg.ram_warn_pct:
        _fire(db, "ram", "warning", None,
              f"RAM al {ram:.0f}% (umbral {cfg.ram_warn_pct}%)", key_ram)
    else:
        _resolve(db, key_ram)


def _check_services(db, cfg):
    if not cfg.service_enabled:
        return
    import subprocess
    watch = [s.strip() for s in (cfg.service_watch or "").split(",") if s.strip()] or DEFAULT_SERVICES
    for svc in watch:
        # Algunos servicios tienen sufijo de versión (php8.3-fpm); probamos variantes
        candidates = [svc]
        if svc == "php-fpm":
            candidates = ["php8.3-fpm", "php8.4-fpm", "php8.5-fpm", "php8.2-fpm"]
        active = False
        checked_any = False
        for c in candidates:
            try:
                r = subprocess.run(["systemctl", "is-active", c],
                                   capture_output=True, text=True, timeout=5)
                checked_any = True
                if r.stdout.strip() == "active":
                    active = True
                    break
            except Exception:
                continue
        key = f"service:{svc}"
        if checked_any and not active:
            _fire(db, "service", "critical", svc,
                  f"Servicio caído: {svc} no está activo", key)
        else:
            _resolve(db, key)


def _check_ssl(db, cfg):
    if not cfg.ssl_enabled:
        return
    from api.models.models_domain import Domain
    from datetime import timedelta
    soon = datetime.utcnow() + timedelta(days=cfg.ssl_days_before)
    domains = db.query(Domain).filter(
        Domain.ssl_enabled == True,  # noqa: E712
        Domain.ssl_expires.isnot(None),
    ).all()
    seen_keys = set()
    for d in domains:
        key = f"ssl:{d.domain_name}"
        seen_keys.add(key)
        if d.ssl_expires and d.ssl_expires <= soon:
            days = (d.ssl_expires - datetime.utcnow()).days
            if days < 0:
                _fire(db, "ssl", "critical", d.domain_name,
                      f"Certificado SSL de {d.domain_name} EXPIRADO", key)
            else:
                _fire(db, "ssl", "warning", d.domain_name,
                      f"SSL de {d.domain_name} expira en {days} días", key)
        else:
            _resolve(db, key)


def evaluate_alerts(db, stats: dict) -> int:
    """
    Evalúa todas las alertas con el snapshot `stats` (de get_system_stats).
    Devuelve el nº de alertas nuevas disparadas. Tolerante a fallos por alerta.
    """
    cfg = _get_or_create_alert_config(db)
    before = _open_count(db)
    for check in (
        lambda: _check_disk(db, cfg, stats),
        lambda: _check_load_ram(db, cfg, stats),
        lambda: _check_services(db, cfg),
        lambda: _check_ssl(db, cfg),
    ):
        try:
            check()
        except Exception as e:
            logger.warning("Fallo evaluando una alerta: %s", e)
    return max(0, _open_count(db) - before)


def _open_count(db) -> int:
    from api.models.models_metrics import AlertEvent
    return db.query(AlertEvent).filter(AlertEvent.resolved_at.is_(None)).count()
