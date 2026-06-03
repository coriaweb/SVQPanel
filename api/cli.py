"""
CLI utilitario para SVQPanel.

Uso típico (desde systemd timer):
    /opt/svqpanel/venv/bin/python -m api.cli refresh_ip_lists
"""

import sys
import argparse
import logging
from datetime import datetime, timedelta

from api.models.database import SessionLocal, load_all_models
# Cargar TODOS los modelos para que SQLAlchemy pueda resolver las FK y las
# relationships por nombre (ej. Domain → 'GitDeployment', User → 'CronJob').
# Sin esto, el primer query()/flush() casca con InvalidRequestError.
load_all_models()
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


def _eval_quota_notifications(db, user, kind, used_mb, quota_mb):
    """
    Genera/limpia avisos para un recurso (kind = 'disco' o 'tráfico').
    - >=90% y <100%  → aviso warning (dedup_key quota_<kind>_90)
    - >=100%         → aviso danger  (dedup_key quota_<kind>_100)
    - <90%           → limpia ambos
    quota_mb == 0 significa ilimitado: no se avisa de nada.
    """
    from scripts.notify import create_notification, clear_notification

    key90  = f"quota_{kind}_90"
    key100 = f"quota_{kind}_100"
    label  = "disco" if kind == "disco" else "tráfico"

    if not quota_mb or quota_mb <= 0:
        clear_notification(db, user.id, key90)
        clear_notification(db, user.id, key100)
        return

    pct = (used_mb / quota_mb) * 100

    if pct >= 100:
        clear_notification(db, user.id, key90)
        create_notification(
            db, user.id, "danger",
            f"Cuota de {label} superada",
            f"Has alcanzado el 100% de tu cuota de {label} "
            f"({used_mb} MB de {quota_mb} MB). No podrás crear nuevos "
            f"recursos hasta liberar espacio.",
            dedup_key=key100,
        )
    elif pct >= 90:
        clear_notification(db, user.id, key100)
        create_notification(
            db, user.id, "warning",
            f"Cuota de {label} casi llena",
            f"Estás usando el {pct:.0f}% de tu cuota de {label} "
            f"({used_mb} MB de {quota_mb} MB). Considera liberar espacio.",
            dedup_key=key90,
        )
    else:
        clear_notification(db, user.id, key90)
        clear_notification(db, user.id, key100)


def cmd_refresh_user_stats() -> int:
    """
    Para cada usuario con home_dir definido, recalcula disk_used_mb y
    traffic_used_mb_month (mes en curso) parseando /home/{user}/web/.
    Genera avisos de cuota al 90%/100%.
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
            _eval_quota_notifications(db, u, "disco",   disk_mb,    u.disk_quota_mb)
            _eval_quota_notifications(db, u, "tráfico", traffic_mb, u.traffic_quota_mb_month)
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


def cmd_register_server_ips() -> int:
    """
    Detecta las IPs asignadas al sistema ('ip addr show') y las registra
    en la tabla server_ips si todavía no existen.
    Se llama una vez desde install.sh al final de la instalación.
    Excluye loopback (127.x, ::1) y link-local (fe80::).
    """
    import subprocess
    import ipaddress
    import re
    from api.models.models_server_ip import ServerIP

    db = SessionLocal()
    try:
        proc = subprocess.run(
            ["/sbin/ip", "-o", "addr", "show"],
            capture_output=True, text=True, timeout=10,
        )
        registered = 0
        skipped = 0
        for line in proc.stdout.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            iface  = parts[1].rstrip(":")
            family = parts[2]   # inet | inet6
            cidr   = parts[3]   # addr/prefix
            if family not in ("inet", "inet6"):
                continue

            addr, _, prefix = cidr.partition("/")

            # Descartar loopback y link-local
            if iface in ("lo", "lo0") or addr.startswith("127.") or addr == "::1":
                continue
            if addr.lower().startswith("fe80"):
                continue

            is_v6  = (family == "inet6")
            netmask = f"/{prefix}" if prefix else None

            # ¿Ya existe?
            exists = db.query(ServerIP).filter(ServerIP.address == addr).first()
            if exists:
                skipped += 1
                logger.info(f"  {addr} ya registrada, omitida")
                continue

            ip = ServerIP(
                address=addr,
                netmask=netmask,
                interface=iface,
                ip_type="shared",
                is_ipv6=is_v6,
                is_active=True,
                note="Registrada automáticamente durante la instalación",
            )
            db.add(ip)
            registered += 1
            logger.info(f"  Registrada: {addr} ({iface}) {'IPv6' if is_v6 else 'IPv4'}")

        db.commit()
        logger.info(f"IPs registradas: {registered} nuevas, {skipped} ya existían")
        return 0
    except Exception as e:
        logger.exception(f"register_server_ips falló: {e}")
        db.rollback()
        return 2
    finally:
        db.close()


def cmd_migrate_php_pools(dry_run: bool = False, only_domain: str = None,
                          force: bool = False) -> int:
    """
    Crea el pool PHP-FPM dedicado (con bloque de seguridad: open_basedir +
    disable_functions + tmp aislado) para los dominios que aún no lo tengan,
    y repunta su vhost al socket dedicado. Idempotente.

    Con force=True reescribe TAMBIÉN los pools existentes, para aplicar
    cambios de política de seguridad (p. ej. quitar /tmp del open_basedir,
    añadir sys_temp_dir) a dominios que ya tenían pool.
    """
    import json as _json
    from scripts import php_ini_manager as phpini
    from scripts.domain_manager import DomainManager

    db = SessionLocal()
    try:
        domains = db.query(Domain).all()
        mgr = DomainManager()
        created = 0
        skipped = 0
        failed = 0
        for d in domains:
            if only_domain and d.domain_name != only_domain:
                continue
            owner = db.query(User).filter(User.id == d.user_id).first()
            if not owner:
                logger.warning(f"  {d.domain_name}: sin propietario, omitido")
                continue
            if phpini.has_pool(d.domain_name) and not force:
                skipped += 1
                logger.info(f"  {d.domain_name}: ya tiene pool, omitido")
                continue

            try:
                overrides = _json.loads(d.php_ini_overrides) if d.php_ini_overrides else {}
            except (ValueError, TypeError):
                overrides = {}
            relax = getattr(d, "php_hardening_relaxed", False) or False
            version = d.php_version or "8.2"

            if dry_run:
                logger.info(f"  {d.domain_name}: crearía pool (ver={version}, relax={relax})")
                created += 1
                continue

            # 1) crear pool + tmp + recargar FPM
            ok, msg = phpini.write_pool(d.domain_name, version, owner.username, overrides, relax)
            if not ok:
                failed += 1
                logger.error(f"  {d.domain_name}: write_pool falló: {msg}")
                continue
            # 2) repuntar vhost al socket dedicado, preservando TODO el estado
            try:
                mgr.regenerate_vhost(
                    username=owner.username,
                    domain_name=d.domain_name,
                    php_version=version,
                    ssl_enabled=d.ssl_enabled or False,
                    ipv6=d.ipv6,
                    fastcgi_cache_enabled=d.fastcgi_cache_enabled or False,
                    fastcgi_cache_ttl_minutes=d.fastcgi_cache_ttl_minutes or 60,
                    php_socket_override=phpini.pool_socket_path(d.domain_name),
                    template_nginx_extra=d.template_nginx_extra,
                    redirect_to=d.redirect_to,
                    custom_docroot=d.custom_docroot,
                    ipv4=d.ipv4,
                    force_https=d.force_https or False,
                    hsts=d.hsts_enabled or False,
                    rate_limit_enabled=d.rate_limit_enabled or False,
                    rate_limit_rps=d.rate_limit_rps or 10,
                    rate_limit_burst=d.rate_limit_burst or 20,
                )
            except Exception as e:
                failed += 1
                logger.error(f"  {d.domain_name}: regenerate_vhost falló: {e}")
                continue
            created += 1
            logger.info(f"  {d.domain_name}: pool creado (ver={version})")

        logger.info(f"migrate_php_pools: {created} creados, {skipped} ya tenían, {failed} fallidos")
        return 0 if failed == 0 else 1
    except Exception as e:
        logger.exception(f"migrate_php_pools falló: {e}")
        return 2
    finally:
        db.close()


def _notify_all_admins(db, level, title, message, dedup_key):
    """Crea una notificación para cada usuario admin (con dedup por usuario)."""
    from scripts.notify import create_notification, clear_notification
    admins = db.query(User).filter(User.role == "admin", User.is_active == True).all()  # noqa: E712
    for a in admins:
        if level is None:  # limpiar
            clear_notification(db, a.id, dedup_key)
        else:
            create_notification(db, a.id, level, title, message, dedup_key=dedup_key)


def cmd_dns_cluster_health() -> int:
    """
    Calcula la salud de sincronización del cluster DNS (serial BD↔ns1↔ns2 por
    zona), la persiste en settings y notifica a los admins si algo está mal.
    Se ejecuta desde el timer svqpanel-dns-cluster-health.timer (cada 10 min).
    """
    import json
    from scripts.dns_cluster import compute_cluster_health
    from api.models.models_settings import Settings

    db = SessionLocal()
    try:
        health = compute_cluster_health(db)
        if health is None:
            logger.info("Sin cluster DNS configurado; nada que comprobar.")
            return 0

        # Persistir el resultado para que la UI lo lea sin esperar
        s = db.query(Settings).filter(Settings.id == 1).first()
        if not s:
            s = Settings(id=1)
            db.add(s)
        s.dns_cluster_health_json = json.dumps(health)
        s.dns_cluster_health_at = datetime.utcnow()

        summary = health["summary"]
        logger.info(f"cluster health: {summary}")

        # Avisos al admin (con dedup para no inundar)
        problems = summary["desync"] + summary["master_down"] + summary["slave_down"]
        if summary["master_down"]:
            _notify_all_admins(
                db, "danger", "Cluster DNS: master no responde",
                "El nameserver master (ns1) no responde a las consultas SOA. "
                "Las zonas podrían no estar sirviéndose. Revisa ns1 y named.",
                dedup_key="dns_cluster_master_down")
        else:
            _notify_all_admins(db, None, "", "", "dns_cluster_master_down")

        if summary["slave_down"]:
            _notify_all_admins(
                db, "warning", "Cluster DNS: slave no responde",
                "El nameserver slave (ns2) no responde. El master sigue sirviendo, "
                "pero no hay redundancia hasta que ns2 vuelva.",
                dedup_key="dns_cluster_slave_down")
        else:
            _notify_all_admins(db, None, "", "", "dns_cluster_slave_down")

        if summary["desync"]:
            desynced = [r["domain"] for r in health["rows"] if r["status"] == "desync"]
            sample = ", ".join(desynced[:5]) + ("…" if len(desynced) > 5 else "")
            _notify_all_admins(
                db, "warning", f"Cluster DNS: {summary['desync']} zona(s) desincronizada(s)",
                f"Algunas zonas no tienen el mismo serial en ns1/ns2 que en el panel: "
                f"{sample}. Pulsa 'Resincronizar' en DNS → Cluster si persiste.",
                dedup_key="dns_cluster_desync")
        else:
            _notify_all_admins(db, None, "", "", "dns_cluster_desync")

        db.commit()
        logger.info(f"health-check OK ({problems} problemas detectados)")
        return 0
    except Exception as e:
        logger.exception(f"dns_cluster_health falló: {e}")
        db.rollback()
        return 2
    finally:
        db.close()


def cmd_run_scheduled_backups() -> int:
    """
    Ejecuta los BackupJobs cuya expresión cron coincida con el minuto actual.
    Diseñado para llamarse cada minuto desde el timer systemd svqpanel-backup-scheduler.
    Arranca cada job que toque en un hilo y espera a que terminen.
    """
    import json
    from api.models.models_backup import BackupJob, BackupRecord
    from api.models.models_domain import Domain
    from api.models.models_client_db import ClientDatabase
    from scripts.backup_scheduler import _cron_matches, _run_job
    import threading

    now = datetime.now(timezone.utc) if 'timezone' in dir() else __import__('datetime').datetime.utcnow()
    # Importar timezone si no está
    from datetime import timezone as _tz
    now = __import__('datetime').datetime.now(_tz.utc)

    db = SessionLocal()
    try:
        jobs = (
            db.query(BackupJob)
            .filter(BackupJob.is_active == True,         # noqa: E712
                    BackupJob.schedule_enabled == True)  # noqa: E712
            .all()
        )
        threads = []
        count = 0
        for job in jobs:
            if _cron_matches(job, now):
                logging.getLogger("svqpanel-cli").info("Lanzando backup job=%d (%s)", job.id, job.name)
                t = threading.Thread(target=_run_job, args=(job.id,), daemon=False)
                t.start()
                threads.append(t)
                count += 1
        for t in threads:
            t.join(timeout=3600)  # esperar máx 1h por job
        logging.getLogger("svqpanel-cli").info("run_scheduled_backups: %d jobs ejecutados", count)
        return 0
    except Exception as e:
        logging.getLogger("svqpanel-cli").error("run_scheduled_backups error: %s", e)
        return 1
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
    sub.add_parser("register_server_ips",  help="Registra las IPs del sistema en la BD (post-instalación)")
    sub.add_parser("dns_cluster_health",      help="Comprueba sincronización del cluster DNS y avisa a admins")
    sub.add_parser("run_scheduled_backups",   help="Ejecuta los backups programados cuyo cron coincide ahora")

    p_pools = sub.add_parser("migrate_php_pools", help="Crea pool PHP-FPM dedicado (seguridad) para dominios sin él")
    p_pools.add_argument("--dry-run", action="store_true", help="Solo muestra lo que haría")
    p_pools.add_argument("--domain", default=None, help="Migrar solo este dominio")
    p_pools.add_argument("--force", action="store_true", help="Reescribe también los pools existentes (aplica nuevas políticas de seguridad)")

    args = parser.parse_args()
    if args.cmd == "refresh_ip_lists":
        sys.exit(cmd_refresh_ip_lists(force=args.force))
    if args.cmd == "refresh_user_stats":
        sys.exit(cmd_refresh_user_stats())
    if args.cmd == "refresh_domain_stats":
        sys.exit(cmd_refresh_domain_stats())
    if args.cmd == "refresh_ssl_expires":
        sys.exit(cmd_refresh_ssl_expires())
    if args.cmd == "register_server_ips":
        sys.exit(cmd_register_server_ips())
    if args.cmd == "dns_cluster_health":
        sys.exit(cmd_dns_cluster_health())
    if args.cmd == "migrate_php_pools":
        sys.exit(cmd_migrate_php_pools(dry_run=args.dry_run, only_domain=args.domain, force=args.force))
    if args.cmd == "run_scheduled_backups":
        sys.exit(cmd_run_scheduled_backups())


if __name__ == "__main__":
    main()
