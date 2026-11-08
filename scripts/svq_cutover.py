"""
Migrador SVQPanel → SVQPanel · FASE 4: el corte y lo que va después.

  - cutover():         activa y PUBLICA las zonas DNS de la cuenta (cluster o
                       BIND local, por el mismo camino que el panel). Desde aquí
                       el servidor nuevo es el bueno: ya no se resincroniza web
                       ni BDs (machacaría lo nuevo), solo se recoge correo.
  - ssl_after_cutover(): cuando el DNS público ya apunta aquí, emite Let's
                       Encrypt y retira la copia del certificado del origen
                       (que se instaló como «propio» para no cortar HTTPS).
  - mark_migrated():   se ejecuta en el ORIGEN. Marca la cuenta como migrada y
                       pausa lo que no debe correr dos veces (crons, backups
                       programados, auto-update de WordPress). No borra nada.
"""

import logging
import subprocess
from datetime import datetime
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


def _account_names(db, user) -> List[str]:
    from api.models.models_domain import Domain
    from api.models.models_mail import MailDomain
    names = {d.domain_name for d in db.query(Domain).filter(Domain.user_id == user.id).all()}
    names |= {m.domain_name for m in db.query(MailDomain).filter(MailDomain.user_id == user.id).all()}
    return sorted(names)


def _publish_zone(zone, db):
    from api.routes.dns import _sync_zone_to_bind
    _sync_zone_to_bind(zone, db)


def cutover(db, username: str, publish: Callable = _publish_zone) -> Dict:
    """Activa y publica las zonas DNS de la cuenta. Idempotente: las que ya
    estaban activas se vuelven a publicar (inocuo)."""
    from api.models.models_user import User
    from api.models.models_dns import DnsZone
    from scripts.dns_manager import next_serial
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise ValueError(f"«{username}» no está en este panel")
    out = {"zones": [], "ok": True}
    zones = db.query(DnsZone).filter(DnsZone.domain_name.in_(_account_names(db, user))).all()
    for z in zones:
        z.is_active = True
        try:
            z.serial = max(int(z.serial or 0) + 1, int(next_serial()))
        except Exception:
            z.serial = int(z.serial or 0) + 1
        db.commit()
        try:
            publish(z, db)
            out["zones"].append({"zone": z.domain_name, "published": True})
        except Exception as e:
            # Queda ACTIVA: el chequeo de salud del cluster la reintentará.
            out["ok"] = False
            out["zones"].append({"zone": z.domain_name, "published": False, "error": str(e)[:300]})
    return out


def _points_here(name: str, ipv4: Optional[str], resolve: Callable) -> bool:
    return bool(ipv4) and ipv4 in resolve(name)


def _dig_a(name: str) -> List[str]:
    found = set()
    for srv in ("1.1.1.1", "8.8.8.8"):
        try:
            r = subprocess.run(["dig", "+short", "+time=3", "+tries=1", "A", name, f"@{srv}"],
                               capture_output=True, text=True, timeout=15)
            found |= {l.strip() for l in r.stdout.splitlines() if l.strip() and l[0].isdigit()}
        except Exception:
            pass
    return sorted(found)


def _issue_le(domain, email: str):
    from scripts.ssl_manager import SSLManager
    SSLManager().create_ssl_with_email(domain.domain_name, email,
                                       include_www=not domain.is_subdomain)


def _finish_le(domain, db):
    """Retira la copia del origen y deja el dominio con su Let's Encrypt."""
    from datetime import timedelta
    from scripts import custom_ssl
    from api.routes.domains import _regenerate_from_domain
    custom_ssl.remove(domain.domain_name)
    domain.ssl_enabled = True
    domain.ssl_certificate = "Let's Encrypt"
    domain.ssl_expires = datetime.utcnow() + timedelta(days=90)
    domain.ssl_renewed_at = datetime.utcnow()
    db.commit()
    _regenerate_from_domain(domain, db)


def ssl_after_cutover(db, username: str, letsencrypt_names: List[str], email: str,
                      server_ipv4: Optional[str], resolve: Callable = _dig_a,
                      issue: Callable = _issue_le, finish: Callable = _finish_le) -> Dict:
    """Para cada dominio cuyo certificado era de Let's Encrypt en el origen: si
    el DNS público ya apunta aquí, emite el suyo y retira la copia. Los que aún
    no apuntan se dejan con la copia (sigue valiendo) para reintentar luego."""
    from api.models.models_user import User
    from api.models.models_domain import Domain
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise ValueError(f"«{username}» no está en este panel")
    want = set(letsencrypt_names or [])
    out = {"issued": [], "waiting_dns": [], "failed": [], "manual": []}
    for d in db.query(Domain).filter(Domain.user_id == user.id).order_by(Domain.domain_name).all():
        if d.domain_name not in want or getattr(d, "mail_dns_only", False):
            continue
        if not _points_here(d.domain_name, server_ipv4, resolve):
            out["waiting_dns"].append(d.domain_name)
            continue
        try:
            issue(d, email)
            finish(d, db)
            out["issued"].append(d.domain_name)
        except Exception as e:
            out["failed"].append({"domain": d.domain_name, "error": str(e)[:300]})
    # mail./webmail. llevan su propio flujo de emisión en la sección Correo
    out["manual"] = sorted(n for n in want if n.split(".", 1)[0] in ("mail", "webmail"))
    return out


def mark_migrated(db, username: str, to_host: str, remove_cron: Callable = None) -> Dict:
    """EN EL ORIGEN. Marca la cuenta como migrada y pausa lo que correría dos
    veces. Devuelve lo que se ha cambiado (para poder deshacerlo a mano)."""
    from api.models.models_user import User
    from api.models.models_cron import CronJob
    from api.models.models_backup import BackupJob
    from api.models.models_domain import Domain
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise ValueError(f"«{username}» no está en este panel")
    if remove_cron is None:
        from scripts.cron_manager import CronManager
        remove_cron = CronManager().remove_cron
    changed = {"crons_paused": [], "backups_paused": [], "wp_autoupdate_off": []}
    for cj in db.query(CronJob).filter(CronJob.user_id == user.id, CronJob.is_active == True).all():  # noqa: E712
        try:
            remove_cron(username, cj.id)
        except Exception as e:
            logger.warning(f"mark_migrated: cron {cj.id}: {e}")
        cj.is_active = False
        changed["crons_paused"].append(cj.id)
    for bj in db.query(BackupJob).filter(BackupJob.user_id == user.id,
                                         BackupJob.schedule_enabled == True).all():  # noqa: E712
        bj.schedule_enabled = False
        changed["backups_paused"].append(bj.id)
    for d in db.query(Domain).filter(Domain.user_id == user.id, Domain.wp_auto_update == True).all():  # noqa: E712
        d.wp_auto_update = False
        changed["wp_autoupdate_off"].append(d.domain_name)
    user.migrated_to = to_host
    user.migrated_at = datetime.utcnow()
    db.commit()
    return changed
