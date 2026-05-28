"""
CLI utilitario para SVQPanel.

Uso típico (desde systemd timer):
    /opt/svqpanel/venv/bin/python -m api.cli refresh_ip_lists
"""

import sys
import argparse
import logging
from datetime import datetime, timedelta

from api.models.database import SessionLocal
# Cargar TODOS los modelos para que SQLAlchemy pueda resolver las FK
# (ej. ip_lists.created_by → users.id). Sin esto, el primer flush() casca
# con NoReferencedTableError.
from api.models import (  # noqa: F401
    models_user, models_domain, models_settings, models_dns,
    models_mail, models_client_db, models_security, models_plan,
    models_cron,
)
from api.models.models_security import IpList, SecurityAuditLog
from api.models.models_domain import Domain
from api.models.models_user import User
from api.utils import ip_list_fetcher, nftables_helper as nft

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("svqpanel-cli")


def cmd_refresh_ip_lists(force: bool = False) -> int:
    """
    Refresca TODAS las IpList habilitadas (fetch + parse), actualiza estado
    en BD, regenera svqpanel-iplists.nft con todas las activas y recarga
    nftables una sola vez al final.

    El flag --force solo afecta a si imprimimos "no tocaba aún"; siempre
    refetcheamos todas porque necesitamos las entradas para regenerar
    el archivo entero. Si una lista falla, conservamos su última versión
    aceptada en BD (sha256_last) pero queda fuera del archivo regenerado
    esta corrida — la siguiente ejecución reintentará.
    """
    db = SessionLocal()
    try:
        enabled = db.query(IpList).filter(IpList.enabled.is_(True)).all()
        if not enabled:
            logger.info("No hay listas IP habilitadas.")
            content = ip_list_fetcher.regenerate_iplists_nft([])
            ip_list_fetcher.write_iplists_nft(content)
            ok, msg = nft.reload_nftables()
            return 0 if ok else 1

        logger.info(f"Listas habilitadas: {len(enabled)}")

        active_tuples = []
        now = datetime.utcnow()

        for il in enabled:
            due = (
                force
                or il.last_success_at is None
                or now >= il.last_success_at + timedelta(hours=il.refresh_interval_hours)
            )
            logger.info(f"  - {il.name}  due={due}  url={il.url}")

            v4, v6, err = ip_list_fetcher.refresh_one(il)
            db.commit()

            if err == "unchanged":
                logger.info(f"      sha256 sin cambios → refetch para incluir en regeneración")
                # Necesitamos las entradas igualmente; refetch puro sin tocar estado:
                try:
                    text, _ = ip_list_fetcher.fetch_url(il.url)
                    v4, v6, _ = ip_list_fetcher.parse_list_content(text, il.max_entries)
                except Exception as e:
                    logger.warning(f"      refetch falló: {e}; omitiendo de regen esta vuelta")
                    continue
            elif err:
                logger.warning(f"      ERROR: {err}")
                continue

            logger.info(f"      v4={len(v4)} v6={len(v6)}")
            active_tuples.append((il, v4, v6))

        # Regen + reload
        content = ip_list_fetcher.regenerate_iplists_nft(active_tuples)
        ip_list_fetcher.write_iplists_nft(content)

        ok, msg = nft.reload_nftables()
        if not ok:
            logger.error(f"Reload nftables falló: {msg}")
        else:
            logger.info(f"nftables recargado OK ({len(active_tuples)} listas activas)")

        # Audit
        entry = SecurityAuditLog(
            user_label = "cron",
            category   = "iplist",
            action     = "refresh_all",
            target     = f"{len(active_tuples)}/{len(enabled)} listas regeneradas",
            success    = ok,
            error      = None if ok else msg,
        )
        db.add(entry)
        db.commit()
        return 0 if ok else 1

    except Exception as e:
        logger.exception(f"refresh_ip_lists falló: {e}")
        return 2
    finally:
        db.close()


def cmd_refresh_domain_stats() -> int:
    """
    Recalcula disk_usage (MB) de cada dominio midiendo su public_html.
    Se ejecuta desde el timer svqpanel-domain-stats.timer (cada 4 horas).
    """
    import os
    import subprocess

    def _du_mb(path: str) -> int:
        if not os.path.isdir(path):
            return 0
        try:
            r = subprocess.run(
                ["/usr/bin/du", "-sb", "--apparent-size", path],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode != 0:
                return 0
            return int(r.stdout.split()[0]) // (1024 * 1024)
        except Exception:
            return 0

    db = SessionLocal()
    try:
        domains = db.query(Domain).filter(Domain.is_active == True).all()  # noqa: E712
        updated = 0
        for d in domains:
            mb = _du_mb(d.public_html)
            d.disk_usage = mb
            updated += 1
            logger.info(f"  {d.domain_name:40s} {mb} MB")
        db.commit()
        logger.info(f"disk_usage actualizado para {updated} dominios")
        return 0
    except Exception as e:
        logger.exception(f"refresh_domain_stats falló: {e}")
        db.rollback()
        return 2
    finally:
        db.close()


def cmd_refresh_ssl_expires() -> int:
    """
    Lee la fecha de expiración real de cada certificado Let's Encrypt
    (openssl x509 -enddate) y la sincroniza en la BD (Domain.ssl_expires).
    Se ejecuta desde el timer svqpanel-ssl-check.timer (diario a las 05:00).
    """
    import subprocess
    import re

    def _cert_expiry(domain: str):
        """Devuelve datetime de expiración o None si no existe/falla."""
        cert = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
        if not __import__("os").path.exists(cert):
            return None
        try:
            r = subprocess.run(
                ["/usr/bin/openssl", "x509", "-enddate", "-noout", "-in", cert],
                capture_output=True, text=True, timeout=10,
            )
            # notAfter=May 28 12:00:00 2026 GMT
            m = re.search(r"notAfter=(.+)", r.stdout)
            if not m:
                return None
            from datetime import datetime
            return datetime.strptime(m.group(1).strip(), "%b %d %H:%M:%S %Y %Z")
        except Exception:
            return None

    db = SessionLocal()
    try:
        domains = db.query(Domain).filter(Domain.ssl_enabled == True).all()  # noqa: E712
        updated = expiring_soon = 0
        now = datetime.utcnow()
        for d in domains:
            expiry = _cert_expiry(d.domain_name)
            if expiry is None:
                continue
            d.ssl_expires = expiry
            updated += 1
            days_left = (expiry - now).days
            if days_left <= 15:
                expiring_soon += 1
                logger.warning(f"  SSL PRONTO A VENCER: {d.domain_name} — {days_left} días")
            else:
                logger.info(f"  {d.domain_name:40s} expira {expiry.date()} ({days_left}d)")
        db.commit()
        logger.info(f"ssl_expires actualizado para {updated} dominios ({expiring_soon} próximos a vencer)")
        return 0
    except Exception as e:
        logger.exception(f"refresh_ssl_expires falló: {e}")
        db.rollback()
        return 2
    finally:
        db.close()


def cmd_refresh_user_stats() -> int:
    """
    Para cada usuario con home_dir definido, recalcula disk_used_mb y
    traffic_used_mb_month (mes en curso) parseando /home/{user}/web/.
    """
    from scripts.user_stats import compute_user_stats

    db = SessionLocal()
    try:
        users = db.query(User).filter(User.is_active == True).all()        # noqa: E712
        updated = 0
        for u in users:
            home = u.home_dir or f"/home/{u.username}"
            if not home:
                continue
            try:
                disk_mb, traffic_mb = compute_user_stats(home)
            except Exception as e:
                logger.warning(f"stats {u.username}: {e}")
                continue
            u.disk_used_mb          = disk_mb
            u.traffic_used_mb_month = traffic_mb
            u.stats_updated_at      = datetime.utcnow()
            updated += 1
            logger.info(f"  {u.username:20s} disk={disk_mb}MB traffic={traffic_mb}MB")
        db.commit()
        logger.info(f"Stats refrescadas para {updated}/{len(users)} usuarios")
        return 0
    except Exception as e:
        logger.exception(f"refresh_user_stats falló: {e}")
        db.rollback()
        return 2
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(prog="api.cli", description="SVQPanel CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_refresh = sub.add_parser("refresh_ip_lists", help="Refresca listas IP vencidas")
    p_refresh.add_argument("--force", action="store_true", help="Refresca todas, ignorar interval")

    sub.add_parser("refresh_user_stats",   help="Recalcula disk + traffic por usuario")
    sub.add_parser("refresh_domain_stats", help="Recalcula disk_usage por dominio")
    sub.add_parser("refresh_ssl_expires",  help="Sincroniza fechas de expiración SSL desde certbot")

    args = parser.parse_args()
    if args.cmd == "refresh_ip_lists":
        sys.exit(cmd_refresh_ip_lists(force=args.force))
    if args.cmd == "refresh_user_stats":
        sys.exit(cmd_refresh_user_stats())
    if args.cmd == "refresh_domain_stats":
        sys.exit(cmd_refresh_domain_stats())
    if args.cmd == "refresh_ssl_expires":
        sys.exit(cmd_refresh_ssl_expires())


if __name__ == "__main__":
    main()
