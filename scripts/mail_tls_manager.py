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
import re
import subprocess
from typing import Dict, List, Optional, Tuple

from .base import SystemManager
from .utils import SSL_PROTOCOLS, SSL_CIPHERS, SSL_SIGN_ALGS

try:
    from scripts.dovecot_version import is_dovecot_24_plus
except ImportError:  # ejecución directa fuera del paquete
    from dovecot_version import is_dovecot_24_plus

logger = logging.getLogger(__name__)

DOVECOT_SNI_CONF  = "/etc/dovecot/conf.d/99-svqpanel-sni.conf"
POSTFIX_SNI_MAP   = "/etc/postfix/svqpanel_sni"
SITES_AVAILABLE   = "/etc/nginx/sites-available"
SITES_ENABLED     = "/etc/nginx/sites-enabled"
ACME_ROOT         = "/var/www/svqpanel-acme"
RENEWAL_HOOK      = "/etc/letsencrypt/renewal-hooks/deploy/svqpanel-reload.sh"

# Deploy-hook de certbot: se ejecuta tras CADA certificado renovado.
#
# Por qué existe: `postmap -F` COPIA el contenido de key+cert dentro de
# svqpanel_sni.db, así que Postfix no ve un cert renovado hasta que se regenera
# el mapa. Y certbot renueva por --webroot, que no recarga nada. Sin este hook,
# Postfix (465/587) servía certs CADUCADOS aunque certbot hubiera renovado bien
# (sep 2026: 7 dominios caducados en SMTP y 24 más a punto). Dovecot y nginx
# leen el fichero al recargar, así que también se recargan aquí.
RENEWAL_HOOK_CONTENT = """#!/bin/bash
# SVQPanel — deploy-hook de certbot. Generado por scripts/mail_tls_manager.py.
# NO editar: se reescribe al instalar/actualizar el panel.
# Tras renovar un cert: regenera el mapa SNI de Postfix (postmap -F incrusta el
# cert en el .db) y recarga Postfix, Dovecot, nginx y Apache.
MAP=/etc/postfix/svqpanel_sni
logger -t svqpanel-cert-hook "cert renovado: ${RENEWED_DOMAINS:-?}" 2>/dev/null || true
if [ -f "$MAP" ] && command -v postmap >/dev/null 2>&1; then
    postmap -F "hash:$MAP" && systemctl reload postfix 2>/dev/null
fi
systemctl is-active --quiet dovecot && systemctl reload dovecot 2>/dev/null
if systemctl is-active --quiet nginx && nginx -t >/dev/null 2>&1; then
    systemctl reload nginx 2>/dev/null
fi
if systemctl is-active --quiet apache2 && apache2ctl configtest >/dev/null 2>&1; then
    systemctl reload apache2 2>/dev/null
fi
exit 0
"""


def install_renewal_hook() -> bool:
    """
    Instala (idempotente) el deploy-hook de certbot. Devuelve True si lo
    escribió/cambió, False si ya estaba igual. Lo llaman install.sh y el update.
    """
    try:
        with open(RENEWAL_HOOK) as f:
            if f.read() == RENEWAL_HOOK_CONTENT and os.access(RENEWAL_HOOK, os.X_OK):
                return False
    except FileNotFoundError:
        pass
    os.makedirs(os.path.dirname(RENEWAL_HOOK), exist_ok=True)
    tmp = RENEWAL_HOOK + ".tmp"
    with open(tmp, "w") as f:
        f.write(RENEWAL_HOOK_CONTENT)
    os.chmod(tmp, 0o755)
    os.replace(tmp, RENEWAL_HOOK)
    return True


def _fingerprint(pem: str) -> Optional[str]:
    """SHA256 del primer certificado de un PEM (None si no se puede leer)."""
    try:
        r = subprocess.run(
            ["/usr/bin/openssl", "x509", "-noout", "-fingerprint", "-sha256"],
            input=pem, capture_output=True, text=True, timeout=10,
        )
        m = re.search(r"=([0-9A-F:]+)", r.stdout)
        return m.group(1) if m else None
    except Exception:
        return None


def _served_fingerprint(host: str, port: int) -> Optional[str]:
    """Fingerprint del cert que sirve el servicio local en `port` para el SNI `host`."""
    try:
        r = subprocess.run(
            ["/usr/bin/openssl", "s_client", "-connect", f"127.0.0.1:{port}",
             "-servername", host],
            input="", capture_output=True, text=True, timeout=6,
        )
    except Exception:
        return None
    m = re.search(r"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----",
                  r.stdout, re.S)
    return _fingerprint(m.group(0)) if m else None


def served_cert_mismatches() -> List[Dict]:
    """
    Compara, para cada mail.{dominio} del mapa SNI, el certificado que SIRVEN
    Postfix (465) y Dovecot (993) con el que hay en disco. Devuelve la lista de
    desfases [{host, port}]. Un puerto que no responde se ignora (y tras 3
    fallos seguidos se deja de probar: no está escuchando en este servidor).
    """
    try:
        with open(POSTFIX_SNI_MAP) as f:
            entries = [l.split() for l in f if l.strip() and not l.startswith("#")]
    except FileNotFoundError:
        return []

    out = []
    dead = {465: 0, 993: 0}
    for parts in entries:
        if len(parts) < 3:
            continue
        host, full = parts[0], parts[2]
        try:
            with open(full) as f:
                disk = _fingerprint(f.read())
        except OSError:
            continue
        if not disk:
            continue
        for port in (465, 993):
            if dead[port] >= 3:
                continue
            served = _served_fingerprint(host, port)
            if served is None:
                dead[port] += 1
                continue
            dead[port] = 0
            if served != disk:
                out.append({"host": host, "port": port})
    return out


def run_renewal_hook() -> None:
    """Ejecuta el deploy-hook a mano (regenera SNI + recarga servicios)."""
    install_renewal_hook()
    subprocess.run(["/bin/bash", RENEWAL_HOOK], capture_output=True, timeout=120)


def mail_host(domain: str) -> str:
    return f"mail.{domain}"


def cert_paths(domain: str) -> Tuple[str, str]:
    """
    Rutas del fullchain y la key del cert para mail.{dominio}.
    Prefiere el cert PROPIO de mail.{dominio} (emitido con --webroot
    independiente); si no existe, cae al cert del dominio padre (legacy --expand).
    """
    host = mail_host(domain)
    own = f"/etc/letsencrypt/live/{host}"
    if os.path.exists(f"{own}/fullchain.pem"):
        return f"{own}/fullchain.pem", f"{own}/privkey.pem"
    base = f"/etc/letsencrypt/live/{domain}"
    return f"{base}/fullchain.pem", f"{base}/privkey.pem"


def cert_includes_mail(domain: str) -> bool:
    """
    ¿Hay un cert SSL válido para mail.{dominio}?
    Comprueba el cert propio de mail.{dominio} o un SAN en el cert del padre.
    """
    host = mail_host(domain)
    # 1. Cert propio de mail.{dominio}
    if os.path.exists(f"/etc/letsencrypt/live/{host}/cert.pem"):
        return True
    # 2. SAN en el cert del dominio padre
    cert = f"/etc/letsencrypt/live/{domain}/cert.pem"
    if not os.path.exists(cert):
        return False
    try:
        import subprocess
        r = subprocess.run(
            ["/usr/bin/openssl", "x509", "-noout", "-text", "-in", cert],
            capture_output=True, text=True, timeout=10,
        )
        return f"DNS:{host}" in r.stdout
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
        # Dovecot 2.4 renombró ssl_cert/ssl_key → ssl_server_cert_file/key_file
        # y ya no usan el prefijo '<' (toman directamente la ruta del fichero).
        v24 = is_dovecot_24_plus()
        for d in domains:
            full, key = cert_paths(d)
            host = mail_host(d)
            if v24:
                out.append(
                    f'local_name {host} {{\n'
                    f'  ssl_server_cert_file = {full}\n'
                    f'  ssl_server_key_file = {key}\n'
                    f'}}\n'
                )
            else:
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

    def _nginx_vhost_name(self, domain: str) -> str:
        return f"svqpanel-mail-{domain}"

    def _ensure_nginx_vhost(self, domain: str) -> None:
        """
        Crea un vhost nginx para mail.{dominio} con su propio cert.
        Sirve con el cert correcto (sin ERR_CERT_COMMON_NAME_INVALID) y
        redirige al webmail del dominio. Necesario aunque mail. sea un host
        de correo: HSTS del padre bloquea el acceso sin un vhost válido.
        """
        import subprocess, socket as _sock
        host = mail_host(domain)
        full, key = cert_paths(domain)
        webmail = f"webmail.{domain}"
        vhost_name = self._nginx_vhost_name(domain)
        avail = f"{SITES_AVAILABLE}/{vhost_name}"
        link  = f"{SITES_ENABLED}/{vhost_name}"

        # listen GENÉRICO (sin atar a la IP). Atar a la IP (listen <IP>:443) hace
        # que este vhost capture el tráfico de otros server_name de esa IP y crea
        # asimetría IPv4/IPv6. nginx enruta por server_name y elige el cert por SNI.
        conf = (
            f"# SVQPanel — vhost mail.{domain} (TLS correo + redirect webmail)\n"
            f"server {{\n"
            f"    listen 80;\n"
            f"    listen [::]:80;\n"
            f"    server_name {host};\n"
            f"    location ^~ /.well-known {{\n"
            f"        root {ACME_ROOT};\n"
            f"        allow all;\n"
            f"    }}\n"
            f"    location / {{ return 301 https://$host$request_uri; }}\n"
            f"}}\n"
            f"server {{\n"
            f"    listen 443 ssl;\n"
            f"    listen [::]:443 ssl;\n"
            f"    http2 on;\n"
            f"    server_name {host};\n"
            f"    ssl_certificate     {full};\n"
            f"    ssl_certificate_key {key};\n"
            f"    ssl_protocols {SSL_PROTOCOLS};\n"
            f"    ssl_ciphers {SSL_CIPHERS};\n"
            f"    ssl_prefer_server_ciphers on;\n"
            f"    ssl_conf_command SignatureAlgorithms {SSL_SIGN_ALGS};\n"
            f"    return 301 https://{webmail}$request_uri;\n"
            f"}}\n"
        )
        import pathlib
        pathlib.Path(ACME_ROOT).mkdir(parents=True, exist_ok=True)
        pathlib.Path(avail).write_text(conf)
        if not pathlib.Path(link).exists():
            self.execute_command(["ln", "-sf", avail, link], check=False)

    def _remove_nginx_vhost(self, domain: str) -> None:
        """Elimina el vhost nginx de mail.{dominio} al desactivar TLS."""
        import pathlib
        vhost_name = self._nginx_vhost_name(domain)
        for p in [f"{SITES_ENABLED}/{vhost_name}", f"{SITES_AVAILABLE}/{vhost_name}"]:
            pathlib.Path(p).unlink(missing_ok=True)

    def rebuild_from_db(self, mail_domains, reload=True) -> dict:
        """
        Regenera la config SNI (Dovecot + Postfix) desde la BD. mail_domains:
        lista de MailDomain. Solo incluye los que tienen mail_tls_enabled Y un
        cert que realmente cubre mail.{dominio} (si no, se omiten para no romper
        la config con rutas inexistentes).
        """
        active = []
        skipped = []
        inactive_domains = []
        for md in mail_domains:
            if not getattr(md, "mail_tls_enabled", False):
                inactive_domains.append(md.domain_name)
                continue
            full, key = cert_paths(md.domain_name)
            if os.path.exists(full) and os.path.exists(key) and cert_includes_mail(md.domain_name):
                active.append(md.domain_name)
                self._ensure_nginx_vhost(md.domain_name)
            else:
                skipped.append(md.domain_name)

        # Borrar vhosts nginx de dominios desactivados
        for d in inactive_domains + skipped:
            self._remove_nginx_vhost(d)

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
            self.execute_command(["nginx", "-s", "reload"], check=False)

        logger.info(f"mail SNI rebuild: {len(active)} activos, {len(skipped)} omitidos (sin cert)")
        return {"active": active, "skipped": skipped}
