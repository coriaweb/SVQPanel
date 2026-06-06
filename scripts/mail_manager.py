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
import re
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
    SENDER_TRANSPORT_MAP  = "sender_dependent_transport"
    # SMTP relay (smarthost): credenciales y relayhost por remitente.
    RELAY_PASSWORD_MAP    = "svqpanel_relay_passwd"   # "[host]:port  user:pass"
    RELAY_SENDER_MAP      = "svqpanel_relay_sender"   # "@dominio  [host]:port"
    POSTFIX_MAIN_CF       = "/etc/postfix/main.cf"
    POSTFIX_MASTER_CF     = "/etc/postfix/master.cf"
    _MASTER_START = "# BEGIN SVQPANEL_SMTP_BIND"
    _MASTER_END   = "# END SVQPANEL_SMTP_BIND"

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
        import subprocess, threading, os
        env = os.environ.copy()
        env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        def _do():
            subprocess.run(["systemctl", "reload-or-restart", "postfix"],
                           capture_output=True, env=env)
        threading.Thread(target=_do, daemon=True).start()

    def _reload_dovecot(self):
        import subprocess, threading, os
        env = os.environ.copy()
        env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        def _do():
            subprocess.run(["systemctl", "reload-or-restart", "dovecot"],
                           capture_output=True, env=env)
        threading.Thread(target=_do, daemon=True).start()

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

        # Crear estructura Maildir (INBOX) y carpetas estándar IMAP
        for subdir in ("cur", "new", "tmp"):
            os.makedirs(os.path.join(maildir, subdir), exist_ok=True)
        for folder in ("Sent", "Drafts", "Trash", "Spam"):
            for subdir in ("cur", "new", "tmp"):
                os.makedirs(os.path.join(maildir, f".{folder}", subdir), exist_ok=True)
        self.execute_command(["chown", "-R", "vmail:vmail", maildir], check=False)
        # Crear carpetas y suscripciones vía doveadm (más fiable que Maildir manual)
        self.execute_command(
            ["doveadm", "mailbox", "create", "-u", email, "Sent", "Drafts", "Trash", "Spam"],
            check=False)
        self.execute_command(
            ["doveadm", "mailbox", "subscribe", "-u", email, "INBOX", "Sent", "Drafts", "Trash", "Spam"],
            check=False)
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
    # Reenvío de buzón (forward)
    # ─────────────────────────────────────────────────────────────────────

    def set_forward(self, domain_name: str, mailbox_username: str,
                    forward_to: list, keep_copy: bool = True):
        """
        Configura reenvío para un buzón.
        - forward_to: lista de emails destino
        - keep_copy: si True, se entrega también en el buzón local
        Usa virtual_alias de Postfix.
        """
        email = f"{mailbox_username}@{domain_name}"
        if not forward_to:
            # Sin destinos → eliminar alias de reenvío
            self._map_remove("virtual_alias", email)
            self._reload_postfix()
            return {"success": True}

        destinations = [d.strip() for d in forward_to if d.strip()]
        if keep_copy:
            # Incluir el buzón local en la lista de destinos
            destinations = [email] + [d for d in destinations if d != email]

        self._map_set("virtual_alias", email, ", ".join(destinations))
        self._reload_postfix()
        return {"success": True}

    def remove_forward(self, domain_name: str, mailbox_username: str):
        """Elimina el reenvío de un buzón"""
        email = f"{mailbox_username}@{domain_name}"
        self._map_remove("virtual_alias", email)
        self._reload_postfix()
        return {"success": True}

    # ─────────────────────────────────────────────────────────────────────
    # Auto-respuesta (Dovecot Sieve)
    # ─────────────────────────────────────────────────────────────────────

    def _sieve_path(self, panel_username: str, domain_name: str, mailbox_username: str) -> str:
        maildir = self.maildir_path(panel_username, domain_name, mailbox_username)
        return os.path.join(maildir, ".dovecot.sieve")

    def set_autoreply(self, panel_username: str, domain_name: str,
                      mailbox_username: str, subject: str, body: str):
        """
        Activa auto-respuesta creando un script Sieve en el Maildir del buzón.
        Usa la extensión 'vacation' de Sieve (estándar Dovecot).
        """
        email = f"{mailbox_username}@{domain_name}"
        sieve_path = self._sieve_path(panel_username, domain_name, mailbox_username)

        # Escapar comillas en subject y body para el script Sieve
        safe_subject = subject.replace('"', '\\"') if subject else f"Re: (Respuesta automática)"
        safe_body    = body.replace('"', '\\"') if body else "Estoy fuera de la oficina. Te responderé en cuanto pueda."

        sieve_script = f'''require ["vacation"];

vacation
  :days 1
  :subject "{safe_subject}"
  :from "{email}"
  "{safe_body}";
'''
        try:
            with open(sieve_path, "w") as f:
                f.write(sieve_script)
            os.chown(sieve_path, 5000, 5000)  # vmail:vmail
            # Compilar el script Sieve
            self.execute_command(["sievec", sieve_path], check=False)
            logger.info(f"Auto-respuesta activada para {email}")
        except Exception as e:
            logger.error(f"Error creando script Sieve para {email}: {e}")
            raise
        return {"success": True}

    def remove_autoreply(self, panel_username: str, domain_name: str, mailbox_username: str):
        """Desactiva la auto-respuesta eliminando el script Sieve"""
        sieve_path = self._sieve_path(panel_username, domain_name, mailbox_username)
        sieve_compiled = sieve_path + "c"
        for path in (sieve_path, sieve_compiled):
            if os.path.exists(path):
                os.remove(path)
        logger.info(f"Auto-respuesta eliminada para {mailbox_username}@{domain_name}")
        return {"success": True}

    # ─────────────────────────────────────────────────────────────────────
    # IP de salida SMTP por dominio (sender_dependent_default_transport_maps)
    # ─────────────────────────────────────────────────────────────────────

    def _transport_name(self, ipv4: str) -> str:
        """smtp_185_104_188_71 para 185.104.188.71"""
        return "smtp_" + ipv4.replace(".", "_")

    def _ensure_main_cf_sender_transport(self):
        """
        Garantiza que main.cf tiene sender_dependent_default_transport_maps
        apuntando a nuestro hash. Solo escribe si no existe ya.
        """
        map_path = self._map_path(self.SENDER_TRANSPORT_MAP)
        directive = f"sender_dependent_default_transport_maps = hash:{map_path}"
        try:
            with open(self.POSTFIX_MAIN_CF, "r", encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            return
        if "sender_dependent_default_transport_maps" not in content:
            with open(self.POSTFIX_MAIN_CF, "a", encoding="utf-8") as f:
                f.write(f"\n# SVQPanel: IP de salida por dominio\n{directive}\n")
            logger.info("main.cf: sender_dependent_default_transport_maps añadido")

    def _rebuild_master_cf_smtp_binds(self):
        """
        Regenera la sección marcada en master.cf con un transporte smtp_X_X_X_X
        por cada IP única presente en sender_dependent_transport.
        Si no quedan entradas, elimina la sección.
        """
        entries = self._read_map(self.SENDER_TRANSPORT_MAP)
        # Extraer IPs únicas de los valores  "smtp_X_X_X_X:"
        unique: dict[str, str] = {}
        for val in entries.values():
            name = val.rstrip(":")
            if name.startswith("smtp_") and "_" in name[5:]:
                ip = name[5:].replace("_", ".")
                unique[name] = ip

        # Construir bloque
        lines = [self._MASTER_START]
        for name in sorted(unique):
            ip = unique[name]
            lines.append(f"{name} unix  -       -       n       -       -       smtp")
            lines.append(f"  -o smtp_bind_address={ip}")
            lines.append(f"  -o smtp_bind_address6=")
        lines.append(self._MASTER_END)
        new_block = "\n".join(lines) + "\n"

        try:
            with open(self.POSTFIX_MASTER_CF, "r", encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            return

        pattern = re.escape(self._MASTER_START) + r".*?" + re.escape(self._MASTER_END) + r"\n?"
        if re.search(pattern, content, flags=re.DOTALL):
            if unique:
                content = re.sub(pattern, new_block, content, flags=re.DOTALL)
            else:
                # Sin IPs: eliminar bloque completo
                content = re.sub(r"\n?" + pattern, "", content, flags=re.DOTALL)
        elif unique:
            content += "\n" + new_block

        tmp = self.POSTFIX_MASTER_CF + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, self.POSTFIX_MASTER_CF)
        logger.info("master.cf: sección SVQPANEL_SMTP_BIND actualizada")

    def set_domain_sender_ip(self, domain_name: str, ipv4: str):
        """
        Configura la IP de salida SMTP para un dominio.
        - Añade @domain → smtp_X_X_X_X: en sender_dependent_transport
        - Garantiza el transporte en master.cf y la directiva en main.cf
        """
        if not self.mail_available():
            return {"success": False, "reason": "postfix_not_installed"}
        transport = self._transport_name(ipv4)
        self._map_set(self.SENDER_TRANSPORT_MAP, f"@{domain_name}", f"{transport}:")
        self._ensure_main_cf_sender_transport()
        self._rebuild_master_cf_smtp_binds()
        self._reload_postfix()
        logger.info(f"set_domain_sender_ip: {domain_name} → {ipv4}")
        return {"success": True, "domain": domain_name, "ip": ipv4}

    def remove_domain_sender_ip(self, domain_name: str):
        """
        Elimina la IP de salida SMTP personalizada de un dominio.
        El dominio pasará a usar la IP por defecto del servidor.
        """
        if not self.mail_available():
            return {"success": False, "reason": "postfix_not_installed"}
        self._map_remove(self.SENDER_TRANSPORT_MAP, f"@{domain_name}")
        self._rebuild_master_cf_smtp_binds()
        self._reload_postfix()
        logger.info(f"remove_domain_sender_ip: {domain_name} → IP por defecto")
        return {"success": True, "domain": domain_name}

    # ─────────────────────────────────────────────────────────────────────
    # SMTP relay / smarthost (global + override por dominio)
    # ─────────────────────────────────────────────────────────────────────
    # Postfix:
    #   relayhost = [host]:port                          (relay GLOBAL)
    #   sender_dependent_relayhost_maps = hash:relay_sender  (override por dominio)
    #   smtp_sasl_password_maps = hash:relay_passwd      (credenciales por host)
    # El password map se escribe SIN postmap de logging del valor (credenciales).

    @staticmethod
    def _relay_target(host: str, port: int) -> str:
        """'[host]:port' — los corchetes evitan que Postfix busque MX del host."""
        return f"[{host.strip()}]:{int(port)}"

    def _ensure_relay_main_cf(self):
        """
        Garantiza en main.cf las directivas base del relay con SASL. Idempotente.
        No fija relayhost aquí (lo gestiona set_global_relay para poder quitarlo).
        """
        passwd = self._map_path(self.RELAY_PASSWORD_MAP)
        sender = self._map_path(self.RELAY_SENDER_MAP)
        directives = {
            "smtp_sasl_auth_enable": "yes",
            "smtp_sasl_password_maps": f"hash:{passwd}",
            "smtp_sasl_security_options": "noanonymous",
            "smtp_tls_security_level": "may",
            "sender_dependent_relayhost_maps": f"hash:{sender}",
        }
        for k, v in directives.items():
            self.execute_command(["postconf", "-e", f"{k} = {v}"])

    def _write_relay_password_map(self, entries: dict):
        """
        Escribe el password map (host → user:pass) con permisos 0600 y postmap.
        entries: {'[host]:port': 'user:pass'}.
        """
        path = self._map_path(self.RELAY_PASSWORD_MAP)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("# SVQPanel relay — credenciales SMTP, NO editar a mano\n")
            for target in sorted(entries):
                f.write(f"{target} {entries[target]}\n")
        os.replace(tmp, path)
        os.chmod(path, 0o600)
        self.execute_command(["postmap", path])
        try:
            os.chmod(path + ".db", 0o600)
        except OSError:
            pass

    def _read_relay_password_map(self) -> dict:
        out = {}
        path = self._map_path(self.RELAY_PASSWORD_MAP)
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        out[parts[0]] = parts[1]
        except FileNotFoundError:
            pass
        return out

    def set_global_relay(self, host: str, port: int,
                         username: str = "", password: str = "") -> dict:
        """Configura el relayhost GLOBAL del servidor (con credenciales opcionales)."""
        if not self.mail_available():
            return {"success": False, "reason": "postfix_not_installed"}
        target = self._relay_target(host, port)
        self._ensure_relay_main_cf()
        self.execute_command(["postconf", "-e", f"relayhost = {target}"])
        if username:
            pw = self._read_relay_password_map()
            pw[target] = f"{username}:{password}"
            self._write_relay_password_map(pw)
        self._reload_postfix()
        logger.info(f"set_global_relay: {target} (auth={'sí' if username else 'no'})")
        return {"success": True, "relayhost": target}

    def remove_global_relay(self) -> dict:
        """Quita el relayhost global; el correo vuelve a envío directo."""
        if not self.mail_available():
            return {"success": False, "reason": "postfix_not_installed"}
        self.execute_command(["postconf", "-e", "relayhost ="])
        self._reload_postfix()
        logger.info("remove_global_relay")
        return {"success": True}

    def set_domain_relay(self, domain_name: str, host: str, port: int,
                         username: str = "", password: str = "") -> dict:
        """
        Configura un relay SOLO para el correo de este dominio (override del
        global). El correo de @dominio sale por host:port; el resto sigue su ruta.
        """
        if not self.mail_available():
            return {"success": False, "reason": "postfix_not_installed"}
        target = self._relay_target(host, port)
        self._ensure_relay_main_cf()
        # @dominio → [host]:port
        self._map_set(self.RELAY_SENDER_MAP, f"@{domain_name}", target)
        # credenciales del host (si las hay)
        if username:
            pw = self._read_relay_password_map()
            pw[target] = f"{username}:{password}"
            self._write_relay_password_map(pw)
        self._reload_postfix()
        logger.info(f"set_domain_relay: {domain_name} → {target}")
        return {"success": True, "domain": domain_name, "relayhost": target}

    def remove_domain_relay(self, domain_name: str) -> dict:
        """Quita el relay propio del dominio; vuelve al relay global o envío directo."""
        if not self.mail_available():
            return {"success": False, "reason": "postfix_not_installed"}
        self._map_remove(self.RELAY_SENDER_MAP, f"@{domain_name}")
        self._reload_postfix()
        logger.info(f"remove_domain_relay: {domain_name}")
        return {"success": True, "domain": domain_name}

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
