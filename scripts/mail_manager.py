"""
Mail Manager — gestión de correo virtual con Postfix + Dovecot.

Estructura de almacenamiento (estilo Hestia):
  /home/{panel_username}/mail/{domain_name}/{mailbox_username}/
    cur/   new/   tmp/   ← formato Maildir

Ficheros gestionados:
  /etc/postfix/virtual_domains   → dominios de correo aceptados
  /etc/postfix/virtual_mailbox   → buzones virtuales
  /etc/postfix/virtual_alias     → alias y catch-all
  /etc/dovecot/users             → usuarios + hashes + rutas (passwd-file)
"""

import os
import shutil
import logging
from .base import SystemManager

logger = logging.getLogger(__name__)


class MailManager(SystemManager):
    """Gestiona buzones de correo virtuales (Postfix + Dovecot)"""

    VMAIL_UID   = 5000
    VMAIL_GID   = 5000
    POSTFIX_DIR = "/etc/postfix"
    DOVECOT_USERS = "/etc/dovecot/users"

    def __init__(self):
        super().__init__(require_root=True)

    # ─────────────────────────────────────────────────────────────────────
    # Rutas
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def mail_root(panel_username):
        """Directorio raíz de correo del usuario del panel"""
        return f"/home/{panel_username}/mail"

    @staticmethod
    def mail_domain_dir(panel_username, domain_name):
        """Directorio del dominio de correo"""
        return f"/home/{panel_username}/mail/{domain_name}"

    @staticmethod
    def maildir_path(panel_username, domain_name, mailbox_username):
        """Ruta completa del Maildir de un buzón"""
        return f"/home/{panel_username}/mail/{domain_name}/{mailbox_username}"

    # ─────────────────────────────────────────────────────────────────────
    # Utilidades: contraseñas
    # ─────────────────────────────────────────────────────────────────────

    def hash_password(self, password):
        """
        Genera hash SHA512-CRYPT compatible con Dovecot usando openssl.
        Devuelve la cadena con prefijo de esquema: {SHA512-CRYPT}$6$...
        """
        code, out, err = self.execute_command(
            ["openssl", "passwd", "-6", password], check=False
        )
        if code != 0 or not out.strip():
            raise RuntimeError(f"Error al generar hash de contraseña: {err}")
        return f"{{SHA512-CRYPT}}{out.strip()}"

    # ─────────────────────────────────────────────────────────────────────
    # Postfix maps (lectura / escritura atómica)
    # ─────────────────────────────────────────────────────────────────────

    def _map_path(self, map_name):
        return os.path.join(self.POSTFIX_DIR, map_name)

    def _read_map(self, map_name):
        """Lee un fichero de mapa Postfix → dict {key: value}"""
        result = {}
        path = self._map_path(map_name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split(None, 1)
                    result[parts[0]] = parts[1] if len(parts) == 2 else ""
        except FileNotFoundError:
            pass
        return result

    def _write_map(self, map_name, entries):
        """Escribe un fichero de mapa Postfix desde dict"""
        path = self._map_path(map_name)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("# SVQPanel — gestionado automáticamente, no editar manualmente\n")
            for key in sorted(entries):
                f.write(f"{key}\t{entries[key]}\n")
        os.replace(tmp, path)  # escritura atómica

    def _postmap(self, map_name):
        """Reconstruye el hash .db de un mapa Postfix"""
        self.execute_command(["postmap", self._map_path(map_name)])
        logger.info(f"postmap: {map_name} actualizado")

    def _map_set(self, map_name, key, value):
        entries = self._read_map(map_name)
        entries[key] = value
        self._write_map(map_name, entries)
        self._postmap(map_name)

    def _map_remove(self, map_name, key):
        entries = self._read_map(map_name)
        if key in entries:
            del entries[key]
            self._write_map(map_name, entries)
            self._postmap(map_name)

    def _map_remove_by_domain(self, map_name, domain_name):
        """Elimina todas las entradas de un dominio de un mapa"""
        entries = self._read_map(map_name)
        suffix = f"@{domain_name}"
        keys_to_remove = [k for k in entries
                          if k.endswith(suffix) or k == f"@{domain_name}"]
        if not keys_to_remove:
            return
        for k in keys_to_remove:
            del entries[k]
        self._write_map(map_name, entries)
        self._postmap(map_name)

    # ─────────────────────────────────────────────────────────────────────
    # Dovecot passwd-file
    # ─────────────────────────────────────────────────────────────────────

    def _read_dovecot_users(self):
        """Lee /etc/dovecot/users → dict {email: línea_completa}"""
        result = {}
        try:
            with open(self.DOVECOT_USERS, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    email = stripped.split(":")[0]
                    result[email] = stripped
        except FileNotFoundError:
            pass
        return result

    def _write_dovecot_users(self, entries):
        """Escribe /etc/dovecot/users de forma atómica"""
        tmp = self.DOVECOT_USERS + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("# SVQPanel — gestionado automáticamente, no editar manualmente\n")
            for email in sorted(entries):
                f.write(entries[email] + "\n")
        os.replace(tmp, self.DOVECOT_USERS)
        os.chmod(self.DOVECOT_USERS, 0o640)
        try:
            shutil.chown(self.DOVECOT_USERS, "root", "dovecot")
        except Exception:
            pass  # dovecot puede no existir en entorno de desarrollo

    def _dovecot_line(self, email, password_hash,
                      panel_username, domain_name, mailbox_username, quota_mb):
        """
        Construye una línea del passwd-file de Dovecot:
        user@domain:{SHA512-CRYPT}hash:5000:5000::/home/user/mail/domain/mailbox::quota_rule
        """
        home = self.maildir_path(panel_username, domain_name, mailbox_username)
        extra = ""
        if quota_mb and quota_mb > 0:
            extra = f"userdb_quota_rule=*:storage={quota_mb}M"
        return (f"{email}:{password_hash}:{self.VMAIL_UID}:{self.VMAIL_GID}"
                f"::{home}::{extra}")

    def _dovecot_set(self, email, password_hash,
                     panel_username, domain_name, mailbox_username, quota_mb=1024):
        users = self._read_dovecot_users()
        users[email] = self._dovecot_line(
            email, password_hash, panel_username, domain_name, mailbox_username, quota_mb
        )
        self._write_dovecot_users(users)

    def _dovecot_remove(self, email):
        users = self._read_dovecot_users()
        if email in users:
            del users[email]
            self._write_dovecot_users(users)

    def _dovecot_remove_by_domain(self, domain_name):
        users = self._read_dovecot_users()
        suffix = f"@{domain_name}"
        keys = [k for k in users if k.endswith(suffix)]
        if not keys:
            return
        for k in keys:
            del users[k]
        self._write_dovecot_users(users)

    # ─────────────────────────────────────────────────────────────────────
    # Recarga de servicios
    # ─────────────────────────────────────────────────────────────────────

    def _reload_postfix(self):
        self.execute_command(
            ["systemctl", "reload-or-restart", "postfix"], check=False
        )

    def _reload_dovecot(self):
        self.execute_command(
            ["systemctl", "reload-or-restart", "dovecot"], check=False
        )

    # ─────────────────────────────────────────────────────────────────────
    # Dominios de correo
    # ─────────────────────────────────────────────────────────────────────

    def create_mail_domain(self, domain_name, panel_username):
        """
        Registra un dominio de correo:
        1. Crea /home/{panel_username}/mail/{domain_name}/
        2. Añade el dominio a /etc/postfix/virtual_domains
        3. Recarga Postfix
        """
        domain_dir = self.mail_domain_dir(panel_username, domain_name)
        os.makedirs(domain_dir, exist_ok=True)
        self.execute_command(
            ["chown", f"vmail:vmail", domain_dir], check=False
        )
        logger.info(f"Directorio de correo creado: {domain_dir}")

        # El valor "OK" es el estándar para virtual_mailbox_domains hash
        self._map_set("virtual_domains", domain_name, "OK")
        self._reload_postfix()

        return {"success": True, "domain": domain_name, "path": domain_dir}

    def delete_mail_domain(self, domain_name, panel_username):
        """
        Elimina un dominio de correo:
        1. Elimina todas sus entradas de los mapas de Postfix
        2. Elimina todas sus entradas de /etc/dovecot/users
        3. Recarga servicios
        4. Borra el directorio de correo del disco
        """
        self._map_remove("virtual_domains", domain_name)
        self._map_remove_by_domain("virtual_mailbox", domain_name)
        self._map_remove_by_domain("virtual_alias",   domain_name)
        self._dovecot_remove_by_domain(domain_name)

        self._reload_postfix()
        self._reload_dovecot()

        # Eliminar árbol de directorios del disco
        domain_dir = self.mail_domain_dir(panel_username, domain_name)
        if os.path.exists(domain_dir):
            shutil.rmtree(domain_dir)
            logger.info(f"Directorio de correo eliminado: {domain_dir}")

        return {"success": True}

    # ─────────────────────────────────────────────────────────────────────
    # Buzones
    # ─────────────────────────────────────────────────────────────────────

    def create_mailbox(self, panel_username, domain_name,
                       mailbox_username, password, quota_mb=1024):
        """
        Crea un buzón virtual:
        1. Estructura Maildir en /home/{panel}/mail/{domain}/{user}/cur|new|tmp
        2. Añade entrada a /etc/postfix/virtual_mailbox
        3. Añade entrada a /etc/dovecot/users (con hash SHA512-CRYPT)
        4. Recarga Dovecot
        """
        email   = f"{mailbox_username}@{domain_name}"
        maildir = self.maildir_path(panel_username, domain_name, mailbox_username)

        # Crear estructura Maildir
        for subdir in ("cur", "new", "tmp"):
            os.makedirs(os.path.join(maildir, subdir), exist_ok=True)
        self.execute_command(["chown", "-R", "vmail:vmail", maildir], check=False)
        logger.info(f"Maildir creado: {maildir}")

        # Hash de contraseña
        pwd_hash = self.hash_password(password)

        # Postfix: ruta relativa a virtual_mailbox_base (/home)
        postfix_path = f"{panel_username}/mail/{domain_name}/{mailbox_username}/"
        self._map_set("virtual_mailbox", email, postfix_path)

        # Dovecot
        self._dovecot_set(email, pwd_hash, panel_username,
                          domain_name, mailbox_username, quota_mb)

        self._reload_dovecot()

        return {"success": True, "email": email, "maildir": maildir}

    def delete_mailbox(self, panel_username, domain_name, mailbox_username):
        """
        Elimina un buzón:
        1. Elimina de Postfix + Dovecot
        2. Borra el Maildir del disco
        """
        email   = f"{mailbox_username}@{domain_name}"
        maildir = self.maildir_path(panel_username, domain_name, mailbox_username)

        self._map_remove("virtual_mailbox", email)
        self._dovecot_remove(email)

        if os.path.exists(maildir):
            shutil.rmtree(maildir)
            logger.info(f"Maildir eliminado: {maildir}")

        self._reload_dovecot()

        return {"success": True}

    def change_mailbox_password(self, panel_username, domain_name,
                                mailbox_username, new_password, quota_mb=1024):
        """Actualiza la contraseña de un buzón en /etc/dovecot/users"""
        email    = f"{mailbox_username}@{domain_name}"
        pwd_hash = self.hash_password(new_password)
        self._dovecot_set(email, pwd_hash, panel_username,
                          domain_name, mailbox_username, quota_mb)
        self._reload_dovecot()
        return {"success": True}

    def set_mailbox_active(self, panel_username, domain_name, mailbox_username,
                           is_active, password_hash=None, quota_mb=1024):
        """
        Activa o suspende un buzón.
        - Suspendido: se elimina de Postfix + Dovecot (datos en disco intactos)
        - Activado:   se re-añade con el hash almacenado en la BD
        """
        email = f"{mailbox_username}@{domain_name}"

        if is_active:
            if not password_hash:
                raise ValueError("Se necesita password_hash para reactivar el buzón")
            postfix_path = f"{panel_username}/mail/{domain_name}/{mailbox_username}/"
            self._map_set("virtual_mailbox", email, postfix_path)
            self._dovecot_set(email, password_hash, panel_username,
                              domain_name, mailbox_username, quota_mb)
        else:
            self._map_remove("virtual_mailbox", email)
            self._dovecot_remove(email)

        self._reload_postfix()
        self._reload_dovecot()
        return {"success": True}

    def update_mailbox_quota(self, panel_username, domain_name,
                             mailbox_username, quota_mb, password_hash):
        """Actualiza la cuota de un buzón en /etc/dovecot/users"""
        email = f"{mailbox_username}@{domain_name}"
        self._dovecot_set(email, password_hash, panel_username,
                          domain_name, mailbox_username, quota_mb)
        self._reload_dovecot()
        return {"success": True}

    # ─────────────────────────────────────────────────────────────────────
    # Alias
    # ─────────────────────────────────────────────────────────────────────

    def create_alias(self, domain_name, source_username, destination):
        """
        Crea un alias: source@domain → destination.
        source_username es solo el prefijo (sin @domain).
        """
        source_email = f"{source_username}@{domain_name}"
        self._map_set("virtual_alias", source_email, destination)
        self._reload_postfix()
        return {"success": True, "source": source_email, "destination": destination}

    def delete_alias(self, domain_name, source_username):
        """Elimina un alias"""
        source_email = f"{source_username}@{domain_name}"
        self._map_remove("virtual_alias", source_email)
        self._reload_postfix()
        return {"success": True}

    def set_catch_all(self, domain_name, destination):
        """
        Configura catch-all: @domain → destination.
        Todo correo sin buzón explícito se redirige a destination.
        """
        self._map_set("virtual_alias", f"@{domain_name}", destination)
        self._reload_postfix()
        return {"success": True}

    def remove_catch_all(self, domain_name):
        """Elimina el catch-all del dominio"""
        self._map_remove("virtual_alias", f"@{domain_name}")
        self._reload_postfix()
        return {"success": True}

    # ─────────────────────────────────────────────────────────────────────
    # Utilidades de estado
    # ─────────────────────────────────────────────────────────────────────

    def mail_available(self):
        """Comprueba si Postfix está instalado en el servidor"""
        return os.path.isdir(self.POSTFIX_DIR)

    def get_mailbox_disk_usage(self, panel_username, domain_name, mailbox_username):
        """Devuelve el uso de disco del buzón en MB (0 si no existe)"""
        maildir = self.maildir_path(panel_username, domain_name, mailbox_username)
        if not os.path.exists(maildir):
            return 0
        total = 0
        for dirpath, _, filenames in os.walk(maildir):
            for fname in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, fname))
                except OSError:
                    pass
        return round(total / (1024 * 1024), 2)
