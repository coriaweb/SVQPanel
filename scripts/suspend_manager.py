"""
Suspensión administrativa: usuario (en cascada) y granular (dominio de correo,
buzón, base de datos). El dominio/web se suspende con DomainSuspendManager.

Filosofía: SUSPENDER no borra nada — corta el acceso/servicio y se puede revertir.
- Web/dominio  → página "Sitio suspendido" (DomainSuspendManager).
- Buzón        → se quita de Postfix+Dovecot (no login IMAP/SMTP); los emails
                 quedan en disco. Reactivar lo re-añade con su hash.
- Dominio mail → suspende todos sus buzones.
- Base de datos→ REVOKE ALL del usuario MariaDB (datos intactos); reactivar
                 re-GRANT los permisos guardados.
- Usuario      → cascada de todo lo anterior + bloquea login al panel (is_active)
                 + bloquea la cuenta del sistema (SSH/FTP) con usermod -L.

Estas funciones reciben la sesión de BD y los objetos; actualizan tanto el
sistema como el flag is_suspended en la BD.
"""
import json
import logging

from scripts.base import SystemManager

logger = logging.getLogger(__name__)


# ── Buzón individual ──────────────────────────────────────────────────────────
def suspend_mailbox(mb, panel_username: str, suspend: bool) -> dict:
    """Suspende/reactiva un buzón (Dovecot/Postfix). `mb` es el Mailbox."""
    from scripts.mail_manager import MailManager
    mgr = MailManager()
    domain = mb.mail_domain.domain_name
    if suspend:
        mgr.set_mailbox_active(panel_username, domain, mb.username, is_active=False)
    else:
        mgr.set_mailbox_active(panel_username, domain, mb.username, is_active=True,
                               password_hash=mb.password_hash, quota_mb=mb.quota_mb or 1024)
    return {"success": True}


# ── Dominio de correo entero (todos sus buzones) ──────────────────────────────
def suspend_mail_domain(md, panel_username: str, suspend: bool, db) -> dict:
    """Suspende/reactiva TODOS los buzones de un dominio de correo."""
    n = 0
    for mb in md.mailboxes:
        try:
            suspend_mailbox(mb, panel_username, suspend)
            mb.is_suspended = suspend
            n += 1
        except Exception as e:
            logger.warning(f"No se pudo {'suspender' if suspend else 'reactivar'} "
                           f"{mb.username}@{md.domain_name}: {e}")
    md.is_suspended = suspend
    db.commit()
    return {"success": True, "mailboxes": n}


# ── Base de datos ─────────────────────────────────────────────────────────────
def suspend_database(client_db, suspend: bool, db) -> dict:
    """Suspende (REVOKE ALL) o reactiva (GRANT ALL) el acceso a una BD de cliente.
    No borra datos. Usa el usuario MariaDB principal de la BD."""
    from api.routes.databases import _run_mariadb
    safe_db = client_db.db_name.replace("`", "``")
    safe_user = client_db.db_user.replace("'", "''")
    try:
        if suspend:
            _run_mariadb(f"REVOKE ALL PRIVILEGES ON `{safe_db}`.* "
                         f"FROM '{safe_user}'@'localhost';")
        else:
            _run_mariadb(f"GRANT ALL PRIVILEGES ON `{safe_db}`.* "
                         f"TO '{safe_user}'@'localhost';")
        _run_mariadb("FLUSH PRIVILEGES;")
    except Exception as e:
        logger.warning(f"REVOKE/GRANT en BD {client_db.db_name} con incidencias: {e}")
    client_db.is_suspended = suspend
    db.commit()
    return {"success": True}


# ── Cuenta del sistema (SSH/FTP) ──────────────────────────────────────────────
class SystemUserLock(SystemManager):
    def lock(self, username: str) -> dict:
        # usermod -L bloquea la contraseña; -s /usr/sbin/nologin corta el shell.
        self.execute_command(["usermod", "-L", username], check=False)
        self.execute_command(["usermod", "-s", "/usr/sbin/nologin", username], check=False)
        return {"success": True}

    def unlock(self, username: str, shell: str = "/bin/bash") -> dict:
        self.execute_command(["usermod", "-U", username], check=False)
        self.execute_command(["usermod", "-s", shell, username], check=False)
        return {"success": True}


# ── Usuario completo (cascada) ────────────────────────────────────────────────
def suspend_user(user, suspend: bool, db) -> dict:
    """Suspende o reactiva TODO lo de un usuario: webs + correo + BDs + cuenta del
    sistema + acceso al panel. Idempotente."""
    from api.models.models_domain import Domain
    from api.models.models_mail import MailDomain
    from api.models.models_client_db import ClientDatabase

    report = {"domains": 0, "mail_domains": 0, "databases": 0}

    # 1) Webs / dominios
    try:
        from scripts.domain_suspend_manager import DomainSuspendManager
        dmgr = DomainSuspendManager()
        for d in db.query(Domain).filter(Domain.user_id == user.id).all():
            try:
                if suspend:
                    dmgr.suspend_domain(d.domain_name)
                else:
                    dmgr.unsuspend_domain(d.domain_name)
                d.is_suspended = suspend
                report["domains"] += 1
            except Exception as e:
                logger.warning(f"Dominio {d.domain_name}: {e}")
    except Exception as e:
        logger.warning(f"Suspensión de dominios con incidencias: {e}")

    # 2) Correo (dominios + buzones)
    for md in db.query(MailDomain).filter(MailDomain.user_id == user.id).all():
        try:
            suspend_mail_domain(md, user.username, suspend, db)
            report["mail_domains"] += 1
        except Exception as e:
            logger.warning(f"Mail dominio {md.domain_name}: {e}")

    # 3) Bases de datos
    for cdb in db.query(ClientDatabase).filter(ClientDatabase.user_id == user.id).all():
        try:
            suspend_database(cdb, suspend, db)
            report["databases"] += 1
        except Exception as e:
            logger.warning(f"BD {cdb.db_name}: {e}")

    # 4) Cuenta del sistema (SSH/FTP)
    try:
        lock = SystemUserLock()
        if suspend:
            lock.lock(user.username)
        else:
            shell = getattr(user, "shell_path", None) or "/bin/bash"
            lock.unlock(user.username, shell)
    except Exception as e:
        logger.warning(f"Lock de cuenta del sistema con incidencias: {e}")

    # 5) Acceso al panel + flags
    user.is_suspended = suspend
    user.is_active = not suspend
    db.commit()

    logger.info(f"Usuario {user.username} {'suspendido' if suspend else 'reactivado'}: {report}")
    return {"success": True, "report": report}
