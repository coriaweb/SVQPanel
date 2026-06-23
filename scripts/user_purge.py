"""
user_purge — borrado COMPLETO de un cliente del panel.

Al eliminar un usuario no basta con `userdel -r` + el cascade de SQLAlchemy:
el cascade borra las FILAS de domains/mail_domains/databases/cron…, pero NO
ejecuta la limpieza de sistema que cada recurso necesita. Eso dejaba basura:

  - vhosts nginx y Apache (sites-available + symlink), pools PHP-FPM, FastCGI cache
  - IPv6 colgando en la interfaz de red
  - dominios de correo (mapas Postfix, /etc/dovecot/users, Maildir, DKIM, webmail)
  - zonas DNS (zone file, named.conf.zones y la zona en el SLAVE del cluster)
  - bases de datos y usuarios MariaDB huérfanos
  - crontab en /var/spool/cron/crontabs/{username} (userdel -r NO lo borra)
  - subcuentas SFTP (usuarios Linux + bind-mounts + ACLs)

Este módulo recoge TODA esa limpieza en un único sitio, reutilizable desde el
endpoint DELETE /users/{id} y desde la CLI. Es **best-effort**: intenta todos
los pasos, acumula los fallos y NO aborta por uno; devuelve la lista de avisos
para que el caller decida (igual criterio que delete_database).

IMPORTANTE: hay que llamar a purge_user_system() ANTES de borrar al usuario de
la BD, porque necesita los nombres de dominio, BDs, jaulas SFTP, etc. que el
cascade está a punto de eliminar.
"""

import logging
from typing import List

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def purge_user_system(db: Session, user) -> List[str]:
    """
    Limpia del SISTEMA todos los recursos de `user` (un objeto User de la BD).

    NO toca la BD del panel (eso lo hace el caller con db.delete(user) +
    el cascade). Devuelve la lista de avisos de los pasos que fallaron.
    """
    warnings: List[str] = []
    username = user.username

    # Cargar modelos relacionados de forma perezosa para no crear ciclos de import.
    from api.models.models_domain import Domain
    from api.models.models_mail import MailDomain
    from api.models.models_client_db import ClientDatabase
    from api.models.models_dns import DnsZone
    from api.models.models_sftp_account import SftpAccount

    # ── 1. Subcuentas SFTP (usuarios Linux propios + bind-mounts) ────────────
    # Se borran primero: son usuarios del sistema enjaulados dentro del home
    # del cliente; si no se desmontan, el rm -rf del home podría tocar el mount.
    try:
        from scripts import sftp_account_manager
        for acc in db.query(SftpAccount).filter(SftpAccount.owner_id == user.id).all():
            try:
                sftp_account_manager.delete_account(
                    owner=username, username=acc.username,
                    jail=acc.jail_path, target=acc.target_path,
                    mount_name=acc.mount_name)
            except Exception as e:
                warnings.append(f"sftp[{acc.username}]: {e}")
    except Exception as e:
        warnings.append(f"sftp: {e}")

    # ── 2. Dominios de correo (Postfix + Dovecot + Maildir + DKIM + webmail) ──
    mail_domains = db.query(MailDomain).filter(MailDomain.user_id == user.id).all()
    for md in mail_domains:
        dname = md.domain_name
        selector = getattr(md, "dkim_selector", "mail")
        try:
            from scripts.mail_manager import MailManager
            MailManager().delete_mail_domain(dname, username)
        except Exception as e:
            warnings.append(f"mail[{dname}]: {e}")
        try:
            from scripts.dkim_manager import DkimManager
            DkimManager().remove_key(dname, selector)
        except Exception as e:
            warnings.append(f"dkim[{dname}]: {e}")
        try:
            from scripts.rspamd_manager import RspamdManager
            RspamdManager().remove_domain(dname)
        except Exception:
            pass

    # ── 3. Bases de datos MariaDB (DROP DATABASE + DROP USER) ─────────────────
    databases = db.query(ClientDatabase).filter(ClientDatabase.user_id == user.id).all()
    if databases:
        try:
            from api.routes.databases import _run_mariadb
            for cdb in databases:
                safe_db = cdb.db_name.replace("`", "``")
                safe_user = cdb.db_user.replace("'", "''")
                try:
                    _run_mariadb(f"DROP DATABASE IF EXISTS `{safe_db}`;")
                except Exception as e:
                    warnings.append(f"db_drop[{cdb.db_name}]: {e}")
                try:
                    _run_mariadb(f"DROP USER IF EXISTS '{safe_user}'@'localhost';")
                except Exception as e:
                    warnings.append(f"db_user[{cdb.db_user}]: {e}")
                # Usuarios adicionales y hosts remotos de esa BD
                for du in list(getattr(cdb, "db_users", []) or []):
                    safe_extra = du.username.replace("'", "''")
                    try:
                        _run_mariadb(f"DROP USER IF EXISTS '{safe_extra}'@'localhost';")
                    except Exception as e:
                        warnings.append(f"db_user[{du.db_user}]: {e}")
                for rh in list(getattr(cdb, "remote_hosts", []) or []):
                    safe_host = str(rh.ip).replace("'", "''")
                    try:
                        _run_mariadb(f"DROP USER IF EXISTS '{safe_user}'@'{safe_host}';")
                    except Exception:
                        pass
            try:
                _run_mariadb("FLUSH PRIVILEGES;")
            except Exception:
                pass
        except Exception as e:
            warnings.append(f"db: {e}")

    # ── 4. Dominios web: IPv6, vhost (nginx + Apache), pool PHP, cache ────────
    domains = db.query(Domain).filter(Domain.user_id == user.id).all()
    for d in domains:
        # IPv6 fuera de la interfaz
        if d.ipv6:
            try:
                from scripts.ipv6_manager import IPv6Manager
                from api.models.models_settings import Settings
                settings = db.query(Settings).filter(Settings.id == 1).first()
                interface = (settings.network_interface
                             if settings and settings.network_interface else "eth0")
                IPv6Manager().remove_ipv6(interface, d.ipv6)
            except Exception as e:
                warnings.append(f"ipv6[{d.domain_name}]: {e}")
        # vhost (nginx + Apache), directorio, pool PHP-FPM
        try:
            from scripts.domain_manager import DomainManager
            DomainManager().delete_domain(d.domain_name, username=username)
        except Exception as e:
            warnings.append(f"domain[{d.domain_name}]: {e}")
        # zona FastCGI cache (delete_domain de la ruta la limpia aparte)
        try:
            from scripts.utils import remove_fastcgi_cache_zone
            remove_fastcgi_cache_zone(d.domain_name)
        except Exception:
            pass

    # ── 5. Zonas DNS (zone file + named.conf.zones + slave del cluster) ───────
    # Las zonas no tienen user_id: se asocian por nombre de dominio del usuario.
    domain_names = {d.domain_name for d in domains}
    if domain_names:
        user_zones = (db.query(DnsZone)
                        .filter(DnsZone.domain_name.in_(domain_names)).all())
        for zone in user_zones:
            dname = zone.domain_name
            from api.models.models_dns import DnsRecord
            db.query(DnsRecord).filter(DnsRecord.zone_id == zone.id).delete()
            db.delete(zone)
        db.commit()

        if user_zones:
            remaining = [z.domain_name for z in db.query(DnsZone)
                         .filter(DnsZone.is_active == True).all()]  # noqa: E712
            removed_in_cluster = False
            try:
                from scripts.dns_cluster import load_cluster, DNSCluster, all_zones_meta
                cluster = load_cluster(db)
                if cluster:
                    slave = cluster["slave"] or cluster["master"]
                    for zone in user_zones:
                        DNSCluster(panel_id=cluster["panel_id"]).remove_zone(
                            cluster["master"], slave, cluster["tsig"],
                            zone.domain_name, all_zones_meta(db))
                    removed_in_cluster = True
            except Exception as e:
                warnings.append(f"dns_cluster: {e}")
            if not removed_in_cluster:
                try:
                    from scripts.dns_manager import DNSManager
                    for zone in user_zones:
                        DNSManager().delete_zone(zone.domain_name, remaining)
                except PermissionError:
                    pass
                except Exception as e:
                    warnings.append(f"dns: {e}")

    # ── 6. Crontab del sistema (/var/spool/cron/crontabs/{username}) ──────────
    # userdel -r NO lo borra. Lo vaciamos por completo con `crontab -r`.
    try:
        from scripts.base import SystemManager  # ejecutor con root
        SystemManager(require_root=True).execute_command(
            ["crontab", "-u", username, "-r"], check=False)
    except Exception as e:
        warnings.append(f"crontab: {e}")

    return warnings
