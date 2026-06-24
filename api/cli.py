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
                    canonical_domain=d.canonical_domain or "www",
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


def cmd_change_server_ip(args) -> int:
    """Cambia la IP principal del servidor. OPERACIÓN PELIGROSA: ver el aviso."""
    from scripts import server_ip_migrator as mig

    # Subcomandos de control que no necesitan old/new
    if getattr(args, "autorevert_check", False):
        return mig.autorevert_check()
    if getattr(args, "confirm", False):
        return mig.confirm()
    if getattr(args, "rollback", False):
        return mig.rollback()

    old_ip, new_ip = args.old_ip, args.new_ip
    if not old_ip or not new_ip:
        print("Uso: change_server_ip <IP_actual> <IP_nueva> [--no-os-network] [--dry-run]")
        print("     change_server_ip --confirm   (hacer firme un cambio en curso)")
        print("     change_server_ip --rollback  (revertir el último cambio)")
        return 1
    if not mig._valid_ip(old_ip) or not mig._valid_ip(new_ip):
        print("✗ IP inválida.")
        return 1

    plan = mig.plan_change(old_ip, new_ip)
    osd = plan.get("os_detected", {})

    # ── Preview / dry-run ──
    print()
    print(f"  Cambio de IP:  {old_ip}  →  {new_ip}")
    print(f"  Se actualizarán: settings={plan['settings']}  dominios={plan['domains']}  "
          f"registros DNS (A)={plan['dns_records']}")
    print(f"  Red del SO detectada: {osd.get('ip')}/{osd.get('prefix')} en {osd.get('iface')} (gw {osd.get('gateway')})")
    toca_red = not args.no_os_network
    print(f"  ¿Reconfigurar la red del SO?: {'SÍ (PELIGROSO)' if toca_red else 'NO (solo propaga)'}")
    print()

    if args.dry_run:
        print("  (--dry-run: no se ha cambiado nada)")
        return 0

    # ── AVISO GRANDE DE RIESGOS ──
    print("  ╔══════════════════════════════════════════════════════════════════╗")
    print("  ║                    ⚠  AVISO IMPORTANTE  ⚠                         ║")
    print("  ╠══════════════════════════════════════════════════════════════════╣")
    print("  ║  Cambiar la IP principal del servidor es una operación de RIESGO. ║")
    print("  ║                                                                    ║")
    print("  ║  • Si reconfiguras la red del SO y la IP nueva NO está enrutada    ║")
    print("  ║    por tu proveedor, el servidor quedará INCOMUNICADO (sin SSH).   ║")
    print("  ║  • Los dominios dejarán de resolver hasta que propague el DNS      ║")
    print("  ║    (depende del TTL de cada registro: minutos u horas).           ║")
    print("  ║  • El correo puede verse afectado (PTR/SPF apuntan a la IP).       ║")
    print("  ║  • TEN A MANO la consola KVM de tu proveedor como plan B.          ║")
    print("  ║                                                                    ║")
    print("  ║  Red de seguridad: si tocas la red del SO, hay AUTO-REVERSIÓN.     ║")
    print(f"  ║  Si no ejecutas `--confirm` en {args.revert_timeout} min, vuelve sola a la IP vieja. ║")
    print("  ║  Se hace BACKUP de red+BD+zonas antes de tocar nada.              ║")
    print("  ╚══════════════════════════════════════════════════════════════════╝")
    print()

    if not args.yes:
        try:
            resp = input(f"  Para CONFIRMAR, escribe la IP nueva ({new_ip}): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelado.")
            return 1
        if resp != new_ip:
            print("  La IP no coincide. Cancelado.")
            return 1

    # ── Ejecutar ──
    print("\n  → Backup del estado actual…")
    backup_dir = mig.backup_state(old_ip, new_ip)

    print("  → Propagando en la base de datos…")
    mig.apply_db(old_ip, new_ip)

    print("  → Regenerando zonas DNS…")
    nz = mig.regen_dns()
    print(f"    {nz} zonas regeneradas")

    print("  → Regenerando vhosts nginx…")
    mig.regen_vhosts()

    if toca_red:
        print("  → Aplicando la IP nueva en la red del SO…")
        ok = mig.apply_os_network(new_ip, prefix=osd.get("prefix"),
                                  iface=osd.get("iface"), gateway=osd.get("gateway"))
        if ok:
            mig.schedule_autorevert(backup_dir, args.revert_timeout)
            print()
            print(f"  ✓ IP aplicada. AUTO-REVERSIÓN en {args.revert_timeout} min si no confirmas.")
            print(f"    Comprueba que SIGUES teniendo acceso por la IP nueva ({new_ip}) y ejecuta:")
            print(f"      python -m api.cli change_server_ip --confirm")
            print(f"    Si algo va mal, NO confirmes: volverá sola. O fuerza:")
            print(f"      python -m api.cli change_server_ip --rollback")
        else:
            print("  ✗ No se pudo aplicar la red del SO. Revirtiendo BD/DNS…")
            mig.rollback(backup_dir)
            return 2
    else:
        print()
        print("  ✓ Propagado (sin tocar la red del SO).")
        print(f"    Backup en: {backup_dir}  ·  rollback: change_server_ip --rollback")
    return 0


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
        # Solo loguear si hubo algo que hacer (evita ruido cada minuto con 0 jobs).
        if count:
            logging.getLogger("svqpanel-cli").info("run_scheduled_backups: %d jobs ejecutados", count)
        return 0
    except Exception as e:
        logging.getLogger("svqpanel-cli").error("run_scheduled_backups error: %s", e)
        return 1
    finally:
        db.close()


def cmd_sample_metrics() -> int:
    """
    Toma una muestra de métricas del sistema, la guarda en el histórico y evalúa
    las alertas configuradas (disco/servicios/carga/SSL). Lo llama el timer
    systemd svqpanel-metrics cada 5 minutos.
    """
    log = logging.getLogger("svqpanel-cli")
    db = SessionLocal()
    try:
        from scripts.metrics_collector import collect_sample
        from scripts.alerts_manager import evaluate_alerts
        from scripts.services_manager import get_system_stats

        sample = collect_sample(db)
        log.info("metrics sample: cpu=%.1f%% ram=%.1f%% disk=%.1f%%",
                 sample["cpu_percent"], sample["ram_percent"], sample["disk_percent"])

        # Evaluar alertas con el snapshot completo
        fired = evaluate_alerts(db, get_system_stats())
        if fired:
            log.info("metrics: %d alertas nuevas disparadas", fired)
        return 0
    except Exception as e:
        log.error("sample_metrics error: %s", e)
        return 1
    finally:
        db.close()


def cmd_panel_whitelist_disable() -> int:
    """
    RESCATE: desactiva la whitelist de IPs del panel. Úsalo por SSH si te has
    quedado fuera del panel web (IP cambió o mal configurada).
        python -m api.cli panel_whitelist_disable
    """
    log = logging.getLogger("svqpanel-cli")
    db = SessionLocal()
    try:
        from api.models.models_settings import Settings
        from scripts.panel_whitelist_manager import PanelWhitelistManager

        s = db.query(Settings).first()
        if s:
            s.panel_whitelist_enabled = False
            db.commit()

        PanelWhitelistManager().disable()
        print("✓ Whitelist del panel DESACTIVADA. El acceso al panel está abierto de nuevo.")
        log.info("panel_whitelist_disable ejecutado (rescate)")
        return 0
    except Exception as e:
        print(f"✗ Error: {e}")
        log.error("panel_whitelist_disable error: %s", e)
        return 1
    finally:
        db.close()


def _panel_backup_retention() -> int:
    """Lee la retención configurada (settings.panel_backup_retention) con fallback."""
    from scripts.panel_backup_manager import DEFAULT_RETENTION
    from api.models.models_settings import Settings
    db = SessionLocal()
    try:
        s = db.query(Settings).first()
        val = getattr(s, "panel_backup_retention", None) if s else None
        return int(val) if val and int(val) > 0 else DEFAULT_RETENTION
    except Exception:
        return DEFAULT_RETENTION
    finally:
        db.close()


def cmd_backup_panel() -> int:
    """
    Crea un backup del propio panel (BD panel_db + ficheros de config críticos)
    y rota los antiguos. Lo llama el timer systemd svqpanel-backup-panel a diario.
    """
    log = logging.getLogger("svqpanel-cli")
    try:
        from scripts.panel_backup_manager import PanelBackupManager
        res = PanelBackupManager().create(retention=_panel_backup_retention())
        log.info("backup_panel OK: %s (%d B) + %s (%d B)",
                 res["db_file"], res["db_size"], res["config_file"], res["config_size"])
        print(f"✓ Backup creado: {res['db_file']} + {res['config_file']}")
        return 0
    except Exception as e:
        log.error("backup_panel error: %s", e)
        print(f"✗ Error: {e}")
        return 1


def cmd_sync_panel_ssl() -> int:
    """
    Sincroniza el estado del SSL del panel en la BD con la realidad del sistema.

    Repara el caso en que el cert se emitió (p.ej. en la instalación) pero settings
    quedó con ssl_panel_enabled=false (la UI mostraría "Sin SSL" pese a tenerlo).
    Si existe el cert del hostname → marca enabled=true + fecha; si no, lo deja en
    false. Idempotente y seguro: NO emite ni renueva, solo refleja lo que hay.
    """
    log = logging.getLogger("svqpanel-cli")
    import os as _os
    from api.models.models_settings import Settings
    from scripts.panel_ssl_manager import PanelSSLManager

    db = SessionLocal()
    try:
        s = db.query(Settings).first()
        if not s:
            print("No hay settings; nada que sincronizar.")
            return 0

        hostname = (s.panel_hostname or "").strip()
        # Fallback conservador: si no hay hostname guardado, deducirlo del único
        # cert de Let's Encrypt presente (si hay exactamente uno).
        if not hostname:
            live = "/etc/letsencrypt/live"
            certs = []
            if _os.path.isdir(live):
                certs = [d for d in _os.listdir(live)
                         if _os.path.isfile(_os.path.join(live, d, "fullchain.pem"))]
            if len(certs) == 1:
                hostname = certs[0]
                s.panel_hostname = hostname

        if not hostname:
            print("Sin hostname del panel ni cert único; nada que sincronizar.")
            return 0

        cert_file = f"/etc/letsencrypt/live/{hostname}/fullchain.pem"
        if _os.path.exists(cert_file):
            expires = PanelSSLManager()._get_cert_expiry(hostname)
            s.ssl_panel_enabled = True
            s.ssl_panel_expires = expires
            db.commit()
            print(f"✓ SSL del panel sincronizado: {hostname} (caduca {expires})")
            log.info("sync_panel_ssl: enabled=True host=%s expires=%s", hostname, expires)
        else:
            if s.ssl_panel_enabled:
                s.ssl_panel_enabled = False
                s.ssl_panel_expires = None
                db.commit()
            print(f"Sin cert para {hostname}; estado dejado en 'sin SSL'.")
        return 0
    except Exception as e:
        db.rollback()
        log.error("sync_panel_ssl error: %s", e)
        print(f"✗ Error: {e}")
        return 1
    finally:
        db.close()


def cmd_restore_panel(filename: str) -> int:
    """
    RESCATE (destructivo): restaura panel_db desde un dump panel_db_*.sql.gz.
    Hace un backup de seguridad antes, restaura y reinicia el panel. Pensado para
    ejecutarse DETACHED (lo lanza el endpoint POST /settings/panel-backup/restore).
    """
    log = logging.getLogger("svqpanel-cli")
    try:
        from scripts.panel_backup_manager import PanelBackupManager
        res = PanelBackupManager().restore(filename)
        log.info("restore_panel OK: restaurado %s (seguridad: %s)",
                 res["restored_from"], res["safety_backup"])
        print(f"✓ Restaurado: {res['restored_from']}")
        return 0
    except Exception as e:
        log.error("restore_panel error: %s", e)
        print(f"✗ Error: {e}")
        return 1


def cmd_admin_recover(username: str = None, password: str = None,
                      email: str = None, list_only: bool = False) -> int:
    """RESCATE: recupera el acceso de administrador desde la consola (root).

    Pensado para cuando se ha perdido el usuario/contraseña del panel:
      - Sin argumentos o con --list: lista las cuentas de administrador.
      - Con --username + --password: resetea la contraseña de ese admin (o de
        cualquier usuario, promoviéndolo a admin si no lo era).
      - Si NO existe ningún admin, crea uno nuevo con los datos dados (o por
        defecto username='admin').

    La contraseña, si no se indica, se genera aleatoria y se imprime UNA vez.
    """
    import secrets, string

    def _gen_pw(n=16):
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(n))

    db = SessionLocal()
    try:
        admins = db.query(User).filter(
            (User.is_admin == True) | (User.role == "admin")).all()  # noqa: E712

        # Solo listar
        if list_only or (not username and not password and admins):
            print("Cuentas de administrador:")
            for u in admins:
                estado = "activa" if u.is_active else "INACTIVA"
                print(f"  • {u.username}  <{u.email or 's/email'}>  (id={u.id}, {estado})")
            if not admins:
                print("  (ninguna) — ejecuta con --username y --password para crear una.")
            print("\nPara resetear: python -m api.cli admin_recover "
                  "--username <user> --password <nueva>")
            return 0

        target = None
        if username:
            target = db.query(User).filter(User.username == username).first()

        # No hay admins y no se localizó destino → crear uno nuevo
        if target is None:
            if not username:
                username = "admin"
                target = db.query(User).filter(User.username == username).first()
            if target is None:
                pw = password or _gen_pw()
                new_admin = User(
                    username=username,
                    email=email or f"{username}@localhost",
                    role="admin",
                    is_admin=True,
                    is_active=True,
                )
                new_admin.set_password(pw)
                db.add(new_admin)
                db.commit()
                print(f"✓ Administrador creado: {username}")
                print(f"  Contraseña: {pw}")
                return 0

        # Resetear/promover el usuario destino
        pw = password or _gen_pw()
        target.set_password(pw)
        target.is_admin = True
        target.role = "admin"
        target.is_active = True
        if email:
            target.email = email
        db.commit()
        print(f"✓ Acceso de administrador restaurado para: {target.username}")
        print(f"  Contraseña: {pw}")
        print("  Inicia sesión y cámbiala desde el panel.")
        return 0
    except Exception as e:
        db.rollback()
        logger.error("admin_recover error: %s", e)
        print(f"✗ Error: {e}")
        return 1
    finally:
        db.close()


def cmd_purge_user(username: str, yes: bool = False) -> int:
    """Borra un cliente y TODOS sus recursos del sistema (root).

    Hace la misma limpieza completa que el endpoint DELETE /users/{id}:
    vhosts nginx+Apache, IPv6, correo (Postfix/Dovecot/DKIM/Rspamd), zonas DNS
    + cluster, BDs MariaDB, crontab, subcuentas SFTP, pools PHP… y luego el
    usuario del SO (userdel -r) y la fila del panel.
    """
    db = SessionLocal()
    try:
        target = db.query(User).filter(User.username == username).first()
        if not target:
            print(f"✗ Usuario no encontrado: {username}")
            return 1
        if target.is_admin:
            other = (db.query(User)
                     .filter(User.is_admin == True, User.id != target.id)  # noqa: E712
                     .count())
            if other == 0:
                print("✗ Es el único administrador del panel; no se borra.")
                return 1
        if not yes:
            print(f"Esto eliminará al cliente '{username}' y TODOS sus recursos.")
            print("Re-ejecuta con --yes para confirmar.")
            return 1

        from scripts.user_purge import purge_user_system
        from scripts.user_manager import UserManager
        warnings = purge_user_system(db, target)
        try:
            UserManager().delete_user(target.username)
        except Exception as e:
            warnings.append(f"userdel: {e}")
        db.delete(target)
        db.commit()

        print(f"✓ Cliente eliminado: {username}")
        if warnings:
            print("  Avisos durante la limpieza:")
            for w in warnings:
                print(f"   - {w}")
        return 0
    except Exception as e:
        db.rollback()
        logger.error("purge_user error: %s", e)
        print(f"✗ Error: {e}")
        return 1
    finally:
        db.close()


def cmd_clean_orphan_vhosts(yes: bool = False) -> int:
    """Detecta y elimina vhosts huérfanos de nginx/Apache (root/logs inexistentes).

    Repara instalaciones donde quedaron vhosts de dominios borrados que hacían
    fallar `nginx -t` / `apache2ctl configtest` y bloqueaban el alta de dominios.
    Sin --yes solo muestra qué borraría (dry-run). NUNCA toca el vhost del panel.
    """
    try:
        from scripts.orphan_vhosts import clean_orphans
    except Exception as e:
        print(f"✗ No se pudo cargar el saneador: {e}")
        return 1

    res = clean_orphans(dry_run=not yes)
    nginx = res["removed"]["nginx"]
    apache = res["removed"]["apache"]
    links = res["removed"].get("broken_links", [])

    if res["count"] == 0:
        print("✓ No hay vhosts huérfanos. Nada que limpiar.")
        return 0

    verbo = "Se borrarían" if not yes else "Borrados"
    print(f"{verbo} {res['count']} vhost(s) huérfano(s):")
    for p in nginx:
        print(f"  [nginx]  {p}")
    for p in apache:
        print(f"  [apache] {p}")
    for p in links:
        print(f"  [symlink roto] {p}")
    for p in res["removed"].get("php_pools", []):
        print(f"  [pool php-fpm] {p}")
    for p in res["removed"].get("dns_zones", []):
        print(f"  [zona dns] {p}")
    for p in res["removed"].get("webmail", []):
        print(f"  [webmail] {p}")
    for w in res["warnings"]:
        print(f"  aviso: {w}")
    if not yes:
        print("\nRe-ejecuta con --yes para borrarlos y recargar el webserver.")
    return 0


def cmd_migrate_canonical_domain(dry_run: bool = False) -> int:
    """Aplica el dominio canónico (por defecto: forzar www) a los dominios ya
    existentes, REGENERANDO su vhost con la redirección 301.

    DEFENSIVO: forzar www solo es seguro si 'www.<dominio>' resuelve en DNS; si
    no resuelve, redirigir dominio.com → www.dominio.com tumbaría la web. Por eso:
      - Si www.<dominio> resuelve  → canonical='www'  (default; se aplica el 301).
      - Si NO resuelve             → canonical='none' (sirve ambas, sin redirigir).
    Idempotente: respeta dominios que el cliente ya configuró a 'non-www'/'none'
    distinto del default (no los pisa). Seguro de re-ejecutar.
    """
    import socket
    from scripts.domain_manager import DomainManager

    def _resuelve(host: str) -> bool:
        try:
            socket.getaddrinfo(host, None)
            return True
        except Exception:
            return False

    db = SessionLocal()
    try:
        domains = db.query(Domain).all()
        mgr = DomainManager()
        forzados = sin_www_dns = ya_ok = fallidos = 0
        for d in domains:
            owner = db.query(User).filter(User.id == d.user_id).first()
            if not owner:
                logger.warning(f"  {d.domain_name}: sin propietario, omitido")
                continue

            actual = d.canonical_domain or "www"
            # Solo decidimos automáticamente cuando el dominio está en 'www'
            # (el default recién aplicado). Si el cliente ya eligió otra cosa
            # explícitamente, no lo tocamos.
            if actual == "www":
                if _resuelve(f"www.{d.domain_name}"):
                    objetivo = "www"
                else:
                    objetivo = "none"
                    sin_www_dns += 1
                    logger.info(
                        f"  {d.domain_name}: www no resuelve → canonical=none "
                        f"(no se fuerza www para no tumbar la web)")
            else:
                objetivo = actual  # respetar elección previa del cliente

            if dry_run:
                logger.info(f"  {d.domain_name}: quedaría canonical={objetivo} (actual={actual})")
                continue

            if d.canonical_domain != objetivo:
                d.canonical_domain = objetivo
                db.commit()

            # Regenerar el vhost para materializar el 301 en disco.
            try:
                from scripts import php_ini_manager as _phpini
                _sock = _phpini.pool_socket_path(d.domain_name) if _phpini.has_pool(d.domain_name) else None
                mgr.regenerate_vhost(
                    username=owner.username,
                    domain_name=d.domain_name,
                    php_version=d.php_version or "8.2",
                    ssl_enabled=d.ssl_enabled or False,
                    ipv6=d.ipv6,
                    fastcgi_cache_enabled=d.fastcgi_cache_enabled or False,
                    fastcgi_cache_ttl_minutes=d.fastcgi_cache_ttl_minutes or 60,
                    php_socket_override=_sock,
                    template_nginx_extra=d.template_nginx_extra,
                    custom_nginx_config=d.custom_nginx_config,
                    custom_apache_config=d.custom_apache_config,
                    redirect_to=d.redirect_to,
                    custom_docroot=d.custom_docroot,
                    ipv4=d.ipv4,
                    force_https=d.force_https or False,
                    hsts=d.hsts_enabled or False,
                    rate_limit_enabled=d.rate_limit_enabled or False,
                    rate_limit_rps=d.rate_limit_rps or 10,
                    rate_limit_burst=d.rate_limit_burst or 20,
                    readonly_mode_enabled=d.readonly_mode_enabled or False,
                    allowed_mutation_ips=d.allowed_mutation_ips,
                    blocked_user_agents=_json.loads(d.blocked_user_agents) if d.blocked_user_agents else [],
                    security_headers_enabled=d.security_headers_enabled or False,
                    http3_enabled=d.http3_enabled or False,
                    canonical_domain=objetivo,
                )
                if objetivo == "www":
                    forzados += 1
                else:
                    ya_ok += 1
            except Exception as e:
                fallidos += 1
                logger.error(f"  {d.domain_name}: regenerate_vhost falló: {e}")

        logger.info(
            f"canonical: www forzado={forzados}, sin-www-por-DNS={sin_www_dns}, "
            f"respetados={ya_ok}, fallidos={fallidos}")
        return 0
    finally:
        db.close()


def cmd_harden_tls(dry_run: bool = False) -> int:
    """Regenera los vhosts con SSL para aplicar la política TLS endurecida
    (cifrados AEAD modernos + ssl_prefer_server_ciphers on).

    Reescribe los vhosts de TODOS los dominios con SSL activo (es donde está el
    ssl_ciphers que evalúan los tests tipo internet.nl/NCSC). Idempotente: usa el
    regenerador estándar que preserva el resto del estado del dominio. El correo,
    webmail y panel toman la política nueva al regenerarse/renovar su SSL.
    """
    from api.routes.domains import _regenerate_domain_vhost

    db = SessionLocal()
    try:
        domains = db.query(Domain).filter(Domain.ssl_enabled == True).all()  # noqa: E712
        ok = fail = 0
        for d in domains:
            owner = db.query(User).filter(User.id == d.user_id).first()
            if not owner:
                continue
            if dry_run:
                logger.info(f"  {d.domain_name}: regeneraría vhost (TLS endurecido)")
                ok += 1
                continue
            try:
                _regenerate_domain_vhost(d, owner)
                ok += 1
            except Exception as e:
                fail += 1
                logger.error(f"  {d.domain_name}: regenerate_vhost falló: {e}")
        logger.info(f"harden_tls: vhosts SSL regenerados={ok}, fallidos={fail}")
        return 0
    finally:
        db.close()


def cmd_migrate_mail_out_ip(dry_run: bool = False) -> int:
    """Reaplica la IP de salida SMTP de todos los dominios con el formato nuevo
    (transporte por dominio svqout_* + mapa de config con ipv4/ipv6/pref).

    Migra instalaciones con el formato viejo (transportes smtp_X_X_X_X) y deja
    master.cf coherente. Idempotente.
    """
    from scripts.mail_manager import MailManager
    try:
        from api.models.models_mail import MailDomain
        from api.routes.mail import _apply_domain_sender_ip
    except Exception as e:
        logger.error(f"No se pudo importar correo: {e}")
        return 0

    mm = MailManager()
    if not mm.mail_available():
        logger.info("Postfix no disponible; nada que migrar.")
        return 0

    db = SessionLocal()
    try:
        mds = db.query(MailDomain).all()
        n = 0
        for md in mds:
            if dry_run:
                logger.info(f"  {md.domain_name}: reaplicaría IP salida (pref={getattr(md,'mail_out_ip_pref','ipv4')})")
                n += 1
                continue
            _apply_domain_sender_ip(md, db)
            n += 1
        logger.info(f"migrate_mail_out_ip: dominios procesados={n}")
        return 0
    finally:
        db.close()


def cmd_backfill_caa(dry_run: bool = False) -> int:
    """Añade registros CAA (issue+issuewild Let's Encrypt) a las zonas DNS
    existentes que no los tengan. Idempotente: no duplica si ya hay CAA.
    """
    from api.routes.dns import CAA_TEMPLATE_RECORDS, _sync_zone_to_bind, _bump_serial
    from api.models.models_dns import DnsZone, DnsRecord

    db = SessionLocal()
    try:
        zonas = db.query(DnsZone).all()
        added = 0
        for z in zonas:
            ya = db.query(DnsRecord).filter(
                DnsRecord.zone_id == z.id, DnsRecord.record_type == "CAA"
            ).count()
            if ya:
                continue  # ya tiene CAA, no tocar
            if dry_run:
                logger.info(f"  {z.domain_name}: añadiría CAA (issue+issuewild LE)")
                added += 1
                continue
            for r in CAA_TEMPLATE_RECORDS():
                db.add(DnsRecord(zone_id=z.id, **r))
            z.serial = _bump_serial(z.serial)
            db.commit()
            _sync_zone_to_bind(z, db)
            added += 1
        logger.info(f"backfill CAA: zonas actualizadas={added}")
        return 0
    finally:
        db.close()


def cmd_setup_spam_learning() -> int:
    """Configura el aprendizaje de spam de Rspamd: IMAPSieve (learn al mover a/
    desde Junk) + autolearn + Bayes global. Idempotente. Requiere dovecot-sieve.
    """
    try:
        from scripts.spam_learning import SpamLearningManager
        mgr = SpamLearningManager()
    except PermissionError:
        logger.error("Requiere root")
        return 1
    except Exception as e:
        logger.error(f"No se pudo cargar SpamLearningManager: {e}")
        return 0
    res = mgr.install()
    if not res.get("success"):
        logger.warning(f"setup_spam_learning: {res.get('reason')}")
        return 0
    logger.info("setup_spam_learning: aprendizaje de spam configurado")
    return 0


def cmd_fix_mail_folders() -> int:
    """Suscribe las carpetas estándar (Sent/Drafts/Trash/Junk) en TODOS los
    buzones existentes, para que clientes como Thunderbird las muestren (no solo
    INBOX+Trash). Idempotente: doveadm subscribe no falla si ya están. El drop-in
    99-svqpanel-mailboxes.conf (auto=subscribe) cubre los buzones NUEVOS; esto
    arregla los que ya existían con auto=no.
    """
    import os
    import subprocess
    USERS = "/etc/dovecot/users"
    if not os.path.exists(USERS):
        logger.info("fix_mail_folders: sin /etc/dovecot/users (correo no instalado)")
        return 0
    folders = ["INBOX", "Sent", "Drafts", "Trash", "Junk"]
    emails = []
    try:
        with open(USERS) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "@" in line:
                    emails.append(line.split(":", 1)[0])
    except Exception as e:
        logger.error(f"fix_mail_folders: no se pudo leer {USERS}: {e}")
        return 0
    fixed = 0
    for email in emails:
        # Crear (por si falta) y suscribir. check=False / errores ignorados:
        # idempotente y no debe romper la cadena de updates.
        subprocess.run(["doveadm", "mailbox", "create", "-u", email,
                        "Sent", "Drafts", "Trash", "Junk"],
                       capture_output=True)
        r = subprocess.run(["doveadm", "mailbox", "subscribe", "-u", email] + folders,
                           capture_output=True)
        # Fusionar la antigua "Spam" (duplicada) en "Junk": mover sus mensajes a
        # Junk (sin perder nada, y así el antispam los conserva) y desuscribirla
        # para que no aparezca duplicada en el cliente. Solo si Spam existe.
        chk = subprocess.run(["doveadm", "mailbox", "status", "-u", email,
                              "messages", "Spam"], capture_output=True)
        if chk.returncode == 0:
            subprocess.run(["doveadm", "move", "-u", email, "Junk",
                            "mailbox", "Spam", "ALL"], capture_output=True)
            subprocess.run(["doveadm", "mailbox", "unsubscribe", "-u", email, "Spam"],
                           capture_output=True)
        if r.returncode == 0:
            fixed += 1
    logger.info(f"fix_mail_folders: carpetas suscritas en {fixed}/{len(emails)} buzones")
    return 0


def cmd_rebuild_mail_ratelimit() -> int:
    """Reconstruye la config de rate-limit de Rspamd desde la BD, incluyendo el
    NUEVO límite del correo NO autenticado (PHP/localhost) por usuario de sistema.
    Cierra el agujero por el que un sitio web hackeado podía enviar sin tope.
    """
    from api.models.database import get_db
    try:
        from api.routes.mail import _rebuild_rspamd
    except Exception as e:
        logger.error(f"No se pudo importar _rebuild_rspamd: {e}")
        return 0
    db = SessionLocal()
    try:
        _rebuild_rspamd(db)
        logger.info("rebuild_mail_ratelimit: config de Rspamd regenerada (incl. no-auth)")
        return 0
    finally:
        db.close()


def cmd_fix_home_perms(dry_run: bool = False) -> int:
    """Normaliza los permisos del home de los usuarios del panel a 711.

    El home DEBE ser 711: el dueño entra, 'other' NO lista el contenido, pero
    www-data/Apache SÍ puede ATRAVESARLO para servir la web. Casos anómalos que
    corrige:
      - 750 → 711 (bug del revert de SFTP; con 750 'other' no atraviesa → 403)
      - 755 → 711 (homes creados por useradd -m sin chmod; otros podían listar)
    NO toca homes con SFTP-only activo (root:root 755, requisito del chroot):
    se excluyen por owner root. Idempotente.
    """
    import os as _os, subprocess as _sp

    db = SessionLocal()
    try:
        users = db.query(User).all()
        fixed = 0
        for u in users:
            home = f"/home/{u.username}"
            if not _os.path.isdir(home):
                continue
            st = _os.stat(home)
            mode = st.st_mode & 0o777
            # Si el home es de root (SFTP-only chroot activo), no tocar.
            if st.st_uid == 0:
                continue
            if mode != 0o711:
                if dry_run:
                    logger.info(f"  {u.username}: home {oct(mode)[2:]} → 711")
                else:
                    _sp.run(["chmod", "711", home], capture_output=True)
                fixed += 1
        logger.info(f"fix_home_perms: homes normalizados a 711={fixed}")
        return 0
    finally:
        db.close()


def cmd_fix_mail_vhosts(dry_run: bool = False) -> int:
    """Regenera los vhosts de webmail.* y mail.* para quitar el 'listen <IP>'
    atado a la IPv4, que los hacía default de la IP y capturaba tráfico de otros
    server_name (causaba la asimetría IPv4/IPv6 y que www.dominio acabara en
    webmail). Idempotente.
    """
    from scripts.webmail_manager import WebmailManager
    from scripts.mail_tls_manager import MailTLSManager
    try:
        from api.models.models_mail import MailDomain
    except Exception as e:
        logger.error(f"No se pudo importar MailDomain: {e}")
        return 0

    db = SessionLocal()
    try:
        mail_domains = db.query(MailDomain).all()
        wm = WebmailManager()
        web_ok = 0
        for md in mail_domains:
            dom = md.domain_name
            if wm.is_enabled(dom):
                if dry_run:
                    logger.info(f"  {dom}: regeneraría vhost webmail")
                else:
                    try:
                        wm.enable(dom)
                        web_ok += 1
                    except Exception as e:
                        logger.error(f"  {dom}: webmail enable falló: {e}")
        # Vhosts de mail.* (TLS SNI + redirect): rebuild_from_db los reescribe.
        if not dry_run:
            try:
                MailTLSManager().rebuild_from_db(mail_domains)
            except Exception as e:
                logger.error(f"rebuild_from_db (mail vhosts) falló: {e}")
        logger.info(f"fix_mail_vhosts: webmail regenerados={web_ok}, mail rebuild=ok")
        return 0
    finally:
        db.close()


def cmd_backfill_dns_ipv6(dry_run: bool = False) -> int:
    """Backfill de zonas DNS existentes:
      - Rellena DnsZone.ip_address si está NULL (la lista mostraba '—').
      - Para dominios con IPv6 asignada: asegura AAAA + ip6 en el SPF.
    Idempotente y seguro de re-ejecutar.
    """
    from api.routes.dns import sync_aaaa_records_for_domain, _get_server_ipv4
    from api.models.models_dns import DnsZone

    db = SessionLocal()
    try:
        zonas = db.query(DnsZone).all()
        ip_fix = aaaa_fix = 0
        for z in zonas:
            dom = db.query(Domain).filter(Domain.domain_name == z.domain_name).first()
            # 1) ip_address NULL → poner la IPv4 del dominio o la del servidor
            if not z.ip_address:
                ipv4 = (dom.ipv4 if dom and dom.ipv4 else None) or _get_server_ipv4(db)
                if ipv4:
                    if dry_run:
                        logger.info(f"  {z.domain_name}: rellenaría ip_address={ipv4}")
                    else:
                        z.ip_address = ipv4
                        db.commit()
                    ip_fix += 1
            # 2) dominio con IPv6 → asegurar AAAA + ip6 en SPF
            if dom and dom.ipv6 and not dry_run:
                res = sync_aaaa_records_for_domain(z.domain_name, dom.ipv6, db)
                if res.get("added") or res.get("spf_updated"):
                    aaaa_fix += 1
            elif dom and dom.ipv6 and dry_run:
                logger.info(f"  {z.domain_name}: sincronizaría AAAA+SPF para {dom.ipv6}")
                aaaa_fix += 1
        logger.info(f"backfill DNS: ip_address={ip_fix}, AAAA/SPF={aaaa_fix}")
        return 0
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(prog="api.cli", description="SVQPanel CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sample_metrics", help="Toma muestra de métricas y evalúa alertas")
    sub.add_parser("panel_whitelist_disable", help="RESCATE: desactiva la whitelist de IPs del panel")
    sub.add_parser("backup_panel", help="Backup de la BD y config del propio panel")
    sub.add_parser("sync_panel_ssl", help="Sincroniza el estado SSL del panel en la BD con el cert real")

    p_restore = sub.add_parser("restore_panel",
        help="RESCATE: restaura panel_db desde un backup (destructivo; reinicia el panel)")
    p_restore.add_argument("filename", help="Nombre del dump (panel_db_FECHA.sql.gz)")

    p_admin = sub.add_parser("admin_recover",
        help="RESCATE: recupera/crea acceso de administrador (ejecutar como root)")
    p_admin.add_argument("--username", default=None, help="Usuario admin a resetear o crear")
    p_admin.add_argument("--password", default=None, help="Nueva contraseña (si se omite, se genera)")
    p_admin.add_argument("--email", default=None, help="Email (al crear un admin nuevo)")
    p_admin.add_argument("--list", action="store_true", dest="list_only",
                         help="Solo listar las cuentas de administrador")

    p_purge = sub.add_parser("purge_user",
        help="Borra un cliente y TODOS sus recursos del sistema (vhosts, correo, DNS, BDs, cron, SFTP…)")
    p_purge.add_argument("username", help="Usuario del panel a eliminar")
    p_purge.add_argument("--yes", action="store_true", help="Confirmar el borrado (sin esto solo avisa)")

    p_moi = sub.add_parser("migrate_mail_out_ip",
        help="Reaplica la IP de salida SMTP por dominio (formato nuevo svqout_* + ipv6/pref)")
    p_moi.add_argument("--dry-run", action="store_true", help="Solo muestra qué haría")

    p_caa = sub.add_parser("backfill_caa",
        help="Añade CAA (issue+issuewild Let's Encrypt) a las zonas DNS que no lo tengan")
    p_caa.add_argument("--dry-run", action="store_true", help="Solo muestra qué haría")

    sub.add_parser("rebuild_mail_ratelimit",
        help="Regenera rate-limit Rspamd (incl. límite del correo no autenticado de PHP/web)")
    sub.add_parser("setup_spam_learning",
        help="Configura el aprendizaje de spam (IMAPSieve + autolearn Bayes)")
    sub.add_parser("fix_mail_folders",
        help="Suscribe Sent/Drafts/Trash/Junk en buzones existentes (Thunderbird los muestra)")

    p_fhp = sub.add_parser("fix_home_perms",
        help="Repara homes en 750 → 711 (traverse de www-data; arregla 403 Forbidden)")
    p_fhp.add_argument("--dry-run", action="store_true", help="Solo muestra qué haría")

    p_fmv = sub.add_parser("fix_mail_vhosts",
        help="Regenera vhosts webmail.*/mail.* quitando el listen atado a IP (asimetría IPv4/IPv6)")
    p_fmv.add_argument("--dry-run", action="store_true", help="Solo muestra qué haría")

    p_htls = sub.add_parser("harden_tls",
        help="Regenera los vhosts SSL con la política TLS endurecida (cifrados modernos)")
    p_htls.add_argument("--dry-run", action="store_true", help="Solo muestra qué haría")

    p_bf = sub.add_parser("backfill_dns_ipv6",
        help="Rellena ip_address NULL de zonas y añade AAAA+ip6(SPF) a dominios con IPv6")
    p_bf.add_argument("--dry-run", action="store_true", help="Solo muestra qué haría")

    p_canon = sub.add_parser("migrate_canonical_domain",
        help="Aplica el dominio canónico (forzar www por defecto) a dominios existentes; defensivo si www no resuelve")
    p_canon.add_argument("--dry-run", action="store_true", help="Solo muestra qué haría")

    p_orphan = sub.add_parser("clean_orphan_vhosts",
        help="Detecta/elimina vhosts huérfanos de nginx/Apache (root o logs inexistentes)")
    p_orphan.add_argument("--yes", action="store_true", help="Borrar de verdad (sin esto solo muestra)")

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

    p_ip = sub.add_parser("change_server_ip",
        help="PELIGROSO: cambia la IP principal del servidor (propaga a DNS/vhosts/correo y opc. red del SO)")
    p_ip.add_argument("old_ip", nargs="?", help="IP actual")
    p_ip.add_argument("new_ip", nargs="?", help="IP nueva")
    p_ip.add_argument("--dry-run", action="store_true", help="Solo muestra qué cambiaría, no toca nada")
    p_ip.add_argument("--no-os-network", action="store_true", help="Propaga BD/DNS/vhosts pero NO toca la red del SO")
    p_ip.add_argument("--yes", action="store_true", help="No preguntar (para automatización). PELIGROSO.")
    p_ip.add_argument("--revert-timeout", type=int, default=10, help="Minutos para auto-reversión de red si no se confirma (default 10)")
    p_ip.add_argument("--confirm", action="store_true", help="Confirma un cambio en curso (cancela la auto-reversión)")
    p_ip.add_argument("--rollback", action="store_true", help="Revierte el último cambio (red + BD + zonas)")
    p_ip.add_argument("--autorevert-check", action="store_true", help="(interno) lo ejecuta el timer de auto-reversión")

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
    if args.cmd == "change_server_ip":
        sys.exit(cmd_change_server_ip(args))
    if args.cmd == "run_scheduled_backups":
        sys.exit(cmd_run_scheduled_backups())
    if args.cmd == "sample_metrics":
        sys.exit(cmd_sample_metrics())
    if args.cmd == "panel_whitelist_disable":
        sys.exit(cmd_panel_whitelist_disable())
    if args.cmd == "admin_recover":
        sys.exit(cmd_admin_recover(username=args.username, password=args.password,
                                   email=args.email, list_only=args.list_only))
    if args.cmd == "backup_panel":
        sys.exit(cmd_backup_panel())
    if args.cmd == "sync_panel_ssl":
        sys.exit(cmd_sync_panel_ssl())
    if args.cmd == "restore_panel":
        sys.exit(cmd_restore_panel(args.filename))
    if args.cmd == "purge_user":
        sys.exit(cmd_purge_user(args.username, yes=args.yes))
    if args.cmd == "clean_orphan_vhosts":
        sys.exit(cmd_clean_orphan_vhosts(yes=args.yes))
    if args.cmd == "migrate_canonical_domain":
        sys.exit(cmd_migrate_canonical_domain(dry_run=args.dry_run))
    if args.cmd == "backfill_dns_ipv6":
        sys.exit(cmd_backfill_dns_ipv6(dry_run=args.dry_run))
    if args.cmd == "harden_tls":
        sys.exit(cmd_harden_tls(dry_run=args.dry_run))
    if args.cmd == "fix_mail_vhosts":
        sys.exit(cmd_fix_mail_vhosts(dry_run=args.dry_run))
    if args.cmd == "fix_home_perms":
        sys.exit(cmd_fix_home_perms(dry_run=args.dry_run))
    if args.cmd == "rebuild_mail_ratelimit":
        sys.exit(cmd_rebuild_mail_ratelimit())
    if args.cmd == "setup_spam_learning":
        sys.exit(cmd_setup_spam_learning())
    if args.cmd == "fix_mail_folders":
        sys.exit(cmd_fix_mail_folders())
    if args.cmd == "backfill_caa":
        sys.exit(cmd_backfill_caa(dry_run=args.dry_run))
    if args.cmd == "migrate_mail_out_ip":
        sys.exit(cmd_migrate_mail_out_ip(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
