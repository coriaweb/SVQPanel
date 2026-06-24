"""
Endurecimiento de servicios: ocultar versiones y anti-enumeración.

Pequeños ajustes de hardening detectados por auditorías (tipo Lynis), de bajo
riesgo y alto valor en hosting compartido:

  - Postfix: banner SMTP genérico (no revelar versión/OS) + deshabilitar VRFY
    (evita enumeración de buzones por spammers).
  - BIND: `version "none"` (no revelar la versión del servidor DNS).

Idempotente. Cada función comprueba antes de actuar y recarga el servicio.
"""
import logging
import os
import re

from scripts.base import SystemManager

logger = logging.getLogger(__name__)

# Banner genérico: solo el hostname + "ESMTP", sin software ni SO.
SMTP_BANNER = "$myhostname ESMTP"
NAMED_OPTIONS = "/etc/bind/named.conf.options"


class ServiceHardeningManager(SystemManager):

    def harden_all(self) -> dict:
        res = {}
        res["postfix"] = self.harden_postfix()
        res["bind"] = self.harden_bind()
        return res

    def harden_postfix(self) -> dict:
        """Banner SMTP genérico + VRFY deshabilitado. Idempotente."""
        if not os.path.exists("/usr/sbin/postconf") and not os.path.exists("/usr/bin/postconf"):
            return {"changed": False, "reason": "postfix no instalado"}
        changed = False
        rc, out, _ = self.execute_command(["postconf", "-h", "smtpd_banner"], check=False)
        if (out or "").strip() != SMTP_BANNER:
            self.execute_command(["postconf", "-e", f"smtpd_banner={SMTP_BANNER}"], check=False)
            changed = True
        rc, out, _ = self.execute_command(["postconf", "-h", "disable_vrfy_command"], check=False)
        if (out or "").strip().lower() != "yes":
            self.execute_command(["postconf", "-e", "disable_vrfy_command=yes"], check=False)
            changed = True
        if changed:
            self.execute_command(["systemctl", "reload", "postfix"], check=False)
            logger.info("Postfix endurecido (banner genérico + VRFY off)")
        return {"changed": changed}

    def harden_bind(self) -> dict:
        """Añade `version "none";` al bloque options de BIND. Idempotente."""
        if not os.path.exists(NAMED_OPTIONS):
            return {"changed": False, "reason": "bind no instalado"}
        try:
            with open(NAMED_OPTIONS) as f:
                content = f.read()
        except OSError as e:
            return {"changed": False, "reason": str(e)}
        if re.search(r"version\s+", content):
            return {"changed": False}  # ya tiene version definida
        # Insertar justo después de "options {".
        new = re.sub(r"(options\s*\{)",
                     r'\1\n\tversion "none";', content, count=1)
        if new == content:
            return {"changed": False, "reason": "no se encontró el bloque options"}
        try:
            with open(NAMED_OPTIONS, "w") as f:
                f.write(new)
        except OSError as e:
            return {"changed": False, "reason": str(e)}
        # Validar antes de recargar; si falla, revertir.
        rc, _, err = self.execute_command(["named-checkconf"], check=False)
        if rc != 0:
            with open(NAMED_OPTIONS, "w") as f:
                f.write(content)
            return {"changed": False, "reason": f"named-checkconf falló: {err}"}
        self.execute_command(["systemctl", "reload", "named"], check=False) \
            if os.path.exists("/usr/sbin/named") else \
            self.execute_command(["systemctl", "reload", "bind9"], check=False)
        logger.info('BIND endurecido (version "none")')
        return {"changed": True}
