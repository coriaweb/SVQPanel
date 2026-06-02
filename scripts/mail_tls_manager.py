"""
TLS por dominio de correo con SNI (estilo Hestia).

Cada dominio de correo puede presentar SU propio certificado en el hostname
mail.{dominio} cuando un cliente conecta por IMAP/POP3 (Dovecot) o SMTP
(Postfix). El servidor elige el certificado según el hostname pedido (SNI):

  - Dovecot 2.3+:  bloques `local_name mail.dominio { ssl_cert/ssl_key }`
                   en /etc/dovecot/conf.d/99-svqpanel-sni.conf
  - Postfix 3.4+:  tls_server_sni_maps = hash:/etc/postfix/svqpanel_sni
                   (mail.dominio → cert+key concatenados), generado con
                   `postmap -F` para que lea ficheros.

El certificado es el del dominio (Let's Encrypt) que ya incluye mail.{dominio}
como SAN; lo emite/expande ssl_manager. Sin cert válido, no se añade el dominio
a la config SNI (se cae al certificado por defecto del servidor).

La config se REGENERA por completo desde la lista de dominios con TLS activado,
igual que rspamd_manager: una sola fuente de verdad (la BD).
"""

import logging
import os
from typing import List, Tuple

from .base import SystemManager

logger = logging.getLogger(__name__)

DOVECOT_SNI_CONF = "/etc/dovecot/conf.d/99-svqpanel-sni.conf"
POSTFIX_SNI_MAP  = "/etc/postfix/svqpanel_sni"


def mail_host(domain: str) -> str:
    return f"mail.{domain}"


def cert_paths(domain: str) -> Tuple[str, str]:
    """Rutas del fullchain y la key del cert Let's Encrypt del dominio."""
    base = f"/etc/letsencrypt/live/{domain}"
    return f"{base}/fullchain.pem", f"{base}/privkey.pem"


def cert_includes_mail(domain: str) -> bool:
    """¿El certificado del dominio cubre mail.{dominio} como SAN?"""
    cert = f"/etc/letsencrypt/live/{domain}/cert.pem"
    if not os.path.exists(cert):
        return False
    try:
        import subprocess
        r = subprocess.run(
            ["/usr/bin/openssl", "x509", "-noout", "-text", "-in", cert],
            capture_output=True, text=True, timeout=10,
        )
        return f"DNS:{mail_host(domain)}" in r.stdout
    except Exception:
        return False


class MailTLSManager(SystemManager):
    """Configura SNI de Dovecot y Postfix para mail.{dominio}."""

    def __init__(self):
        super().__init__(require_root=True)

    def _dovecot_sni_conf(self, domains: List[str]) -> str:
        """
        local_name por dominio. Dovecot presenta el cert correcto según el
        hostname TLS (SNI) que pide el cliente.
        """
        out = ["# SVQPanel — TLS por dominio (SNI). Generado automáticamente. NO editar.\n"]
        for d in domains:
            full, key = cert_paths(d)
            host = mail_host(d)
            out.append(
                f'local_name {host} {{\n'
                f'  ssl_cert = <{full}\n'
                f'  ssl_key = <{key}\n'
                f'}}\n'
            )
        return "\n".join(out)

    def _postfix_sni_lines(self, domains: List[str]) -> List[str]:
        """
        Líneas del mapa SNI de Postfix: "hostname  keyfile  certfile".
        Se carga con `postmap -F` (formato file). Postfix concatena key+cert.
        """
        lines = []
        for d in domains:
            full, key = cert_paths(d)
            lines.append(f"{mail_host(d)} {key} {full}")
        return lines

    def rebuild_from_db(self, mail_domains, reload=True) -> dict:
        """
        Regenera la config SNI (Dovecot + Postfix) desde la BD. mail_domains:
        lista de MailDomain. Solo incluye los que tienen mail_tls_enabled Y un
        cert que realmente cubre mail.{dominio} (si no, se omiten para no romper
        la config con rutas inexistentes).
        """
        active = []
        skipped = []
        for md in mail_domains:
            if not getattr(md, "mail_tls_enabled", False):
                continue
            full, key = cert_paths(md.domain_name)
            if os.path.exists(full) and os.path.exists(key) and cert_includes_mail(md.domain_name):
                active.append(md.domain_name)
            else:
                skipped.append(md.domain_name)

        # ── Dovecot ──
        os.makedirs(os.path.dirname(DOVECOT_SNI_CONF), exist_ok=True)
        tmp = DOVECOT_SNI_CONF + ".tmp"
        with open(tmp, "w") as f:
            f.write(self._dovecot_sni_conf(active))
        os.replace(tmp, DOVECOT_SNI_CONF)

        # ── Postfix ──
        lines = self._postfix_sni_lines(active)
        tmp = POSTFIX_SNI_MAP + ".tmp"
        with open(tmp, "w") as f:
            f.write("# SVQPanel — SNI map. Generado automáticamente. NO editar.\n")
            f.write("\n".join(lines) + ("\n" if lines else ""))
        os.replace(tmp, POSTFIX_SNI_MAP)
        # postmap -F: el valor son rutas de fichero (key+cert), no texto
        self.execute_command(["postmap", "-F", f"hash:{POSTFIX_SNI_MAP}"], check=False)
        # Asegurar la directiva (idempotente)
        self.execute_command(
            ["postconf", "-e", f"tls_server_sni_maps = hash:{POSTFIX_SNI_MAP}"],
            check=False)

        if reload:
            self.execute_command(["systemctl", "reload", "dovecot"], check=False)
            self.execute_command(["systemctl", "reload", "postfix"], check=False)

        logger.info(f"mail SNI rebuild: {len(active)} activos, {len(skipped)} omitidos (sin cert)")
        return {"active": active, "skipped": skipped}
