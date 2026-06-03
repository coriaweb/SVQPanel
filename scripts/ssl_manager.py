"""SSL certificate management with Let's Encrypt"""

import logging
import os
import subprocess
from datetime import datetime, timezone
from .base import SystemManager
from .utils import validate_domain

logger = logging.getLogger(__name__)


class SSLManager(SystemManager):
    """Manage SSL certificates with Let's Encrypt"""

    def __init__(self):
        super().__init__(require_root=True)

    def create_ssl(self, domain_name: str) -> dict:
        """
        Create SSL certificate with Let's Encrypt

        Args:
            domain_name: Domain name

        Returns:
            {'success': True, 'domain': 'example.com', 'expires': '2024-...'}
        """
        if not validate_domain(domain_name):
            raise ValueError(f"Invalid domain: {domain_name}")

        try:
            logger.info(f"Creating SSL cert for: {domain_name}")

            # Verificar si www.dominio resuelve en DNS antes de añadirlo
            import socket
            domains = [domain_name]
            try:
                socket.getaddrinfo(f"www.{domain_name}", None)
                domains.append(f"www.{domain_name}")
            except socket.gaierror:
                logger.info(f"www.{domain_name} no resuelve en DNS, omitiendo SAN")

            cmd = ["certbot", "certonly", "--nginx", "--non-interactive", "--agree-tos",
                   "-m", "admin@example.com"]  # TODO: from config
            for d in domains:
                cmd += ["-d", d]

            # Run certbot
            self.execute_command(cmd)

            # Set up auto-renewal
            self.execute_command([
                "systemctl",
                "enable",
                "certbot.timer"
            ])

            logger.info(f"SSL cert created: {domain_name}")
            return {
                "success": True,
                "domain": domain_name,
                "status": "Certificate created and renewal enabled"
            }

        except Exception as e:
            logger.error(f"Failed to create SSL: {str(e)}")
            raise

    def create_ssl_with_email(self, domain_name: str, email: str,
                              extra_domains: list = None) -> dict:
        """
        Igual que create_ssl pero con email configurable y SANs extra opcionales
        (p. ej. webmail.{dominio} para el webmail por dominio).
        """
        if not validate_domain(domain_name):
            raise ValueError(f"Invalid domain: {domain_name}")
        import socket
        domains = [domain_name]
        try:
            socket.getaddrinfo(f"www.{domain_name}", None)
            domains.append(f"www.{domain_name}")
        except socket.gaierror:
            logger.info(f"www.{domain_name} no resuelve en DNS, omitiendo SAN")
        cmd = ["certbot", "certonly", "--nginx"]
        for d in domains:
            cmd += ["-d", d]
        for d in (extra_domains or []):
            if validate_domain(d):
                cmd += ["-d", d]
        cmd += ["--non-interactive", "--agree-tos", "-m", email, "--expand"]
        try:
            self.execute_command(cmd)
            self.execute_command(["systemctl", "enable", "certbot.timer"])
            logger.info(f"SSL cert (with email) created: {domain_name} +{extra_domains or []}")
            return {"success": True, "domain": domain_name}
        except Exception as e:
            logger.error(f"Failed to create SSL: {str(e)}")
            raise

    def expand_for_webmail(self, domain_name: str, email: str) -> dict:
        """
        Emite un certificado independiente para webmail.{dominio} usando --webroot
        con /var/www/webmail. No toca el cert del dominio principal.
        El vhost del webmail debe tener location ^~ /.well-known accesible en HTTP.
        """
        webmail_host = f"webmail.{domain_name}"
        webroot = "/var/www/webmail"
        import os
        os.makedirs(f"{webroot}/.well-known/acme-challenge", exist_ok=True)
        cmd = [
            "certbot", "certonly", "--webroot",
            "-w", webroot,
            "-d", webmail_host,
            "--non-interactive", "--agree-tos", "-m", email,
        ]
        try:
            self.execute_command(cmd)
            logger.info(f"Webmail SSL cert emitido para {webmail_host}")
            return {"success": True, "domain": webmail_host,
                    "cert": f"/etc/letsencrypt/live/{webmail_host}/fullchain.pem"}
        except Exception as e:
            logger.error(f"Failed to issue webmail SSL: {e}")
            raise

    def expand_for_mail(self, domain_name: str, email: str) -> dict:
        """
        Reemite (expand) el certificado del dominio añadiendo mail.{dominio} como
        SAN, para presentar TLS válido en IMAP/POP3/SMTP (SNI). Requiere que
        mail.{dominio} ya resuelva hacia este servidor (validación ACME).
        """
        return self.create_ssl_with_email(
            domain_name, email, extra_domains=[f"mail.{domain_name}"])

    def revoke_ssl(self, domain_name: str) -> dict:
        """
        Revoke SSL certificate

        Args:
            domain_name: Domain name

        Returns:
            {'success': True, 'revoked_domain': 'example.com'}
        """
        if not validate_domain(domain_name):
            raise ValueError(f"Invalid domain: {domain_name}")

        try:
            logger.info(f"Revoking SSL: {domain_name}")

            self.execute_command([
                "certbot",
                "revoke",
                "--cert-name", domain_name,
                "--non-interactive"
            ], check=False)

            # Delete cert
            self.execute_command([
                "rm", "-rf",
                f"/etc/letsencrypt/live/{domain_name}"
            ])

            logger.info(f"SSL revoked: {domain_name}")
            return {
                "success": True,
                "revoked_domain": domain_name
            }

        except Exception as e:
            logger.error(f"Failed to revoke SSL: {str(e)}")
            raise

    def get_cert_info(self, domain_name: str) -> dict:
        """
        Lee el certificado de /etc/letsencrypt/live/{domain}/cert.pem
        y devuelve un dict con: issued_to, sans, not_before, not_after,
        signature_alg, key_size, issuer, key_type, pem (cert completo).
        Devuelve None si el cert no existe.
        """
        cert_path = f"/etc/letsencrypt/live/{domain_name}/fullchain.pem"
        if not os.path.isfile(cert_path):
            return None
        try:
            result = subprocess.run(
                ["openssl", "x509", "-noout", "-text", "-in", cert_path],
                capture_output=True, text=True, timeout=10
            )
            text = result.stdout

            # subject CN
            issued_to = None
            for line in text.splitlines():
                if "Subject:" in line and "CN" in line:
                    parts = line.split("CN =")
                    if len(parts) > 1:
                        issued_to = parts[-1].strip().split(",")[0]
                    break

            # SANs
            sans = []
            in_san = False
            for line in text.splitlines():
                if "Subject Alternative Name:" in line:
                    in_san = True
                    continue
                if in_san:
                    sans = [s.replace("DNS:", "").strip()
                            for s in line.split(",")
                            if "DNS:" in s]
                    break

            # Fechas  (formato: May 25 23:34:19 2026 GMT)
            not_before = not_after = None
            for line in text.splitlines():
                if "Not Before" in line:
                    not_before = line.split(":", 1)[1].strip()
                elif "Not After" in line:
                    not_after = line.split(":", 1)[1].strip()

            # Firma
            signature_alg = None
            for line in text.splitlines():
                if "Signature Algorithm:" in line and signature_alg is None:
                    signature_alg = line.split(":", 1)[1].strip()

            # Tamaño de clave
            key_result = subprocess.run(
                ["openssl", "x509", "-noout", "-text", "-in", cert_path],
                capture_output=True, text=True, timeout=10
            )
            key_size = None
            key_type = None
            for line in key_result.stdout.splitlines():
                if "Public Key Algorithm:" in line:
                    key_type = line.split(":", 1)[1].strip()
                if "Public-Key:" in line or "RSA Public-Key:" in line:
                    key_size = line.strip().strip("(").strip(")").split("(")[-1].split(" ")[0]

            # Emisor
            issuer = None
            for line in text.splitlines():
                if "Issuer:" in line:
                    issuer = line.split(":", 1)[1].strip()
                    break

            # Cert PEM completo
            with open(cert_path, "r") as f:
                pem = f.read()

            return {
                "issued_to":     issued_to or domain_name,
                "sans":          sans,
                "not_before":    not_before,
                "not_after":     not_after,
                "signature_alg": signature_alg,
                "key_size":      key_size,
                "key_type":      key_type,
                "issuer":        issuer,
                "pem":           pem,
            }
        except Exception as e:
            logger.warning(f"get_cert_info failed for {domain_name}: {e}")
            return None
