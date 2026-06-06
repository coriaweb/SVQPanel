"""SSL certificate management with Let's Encrypt"""

import logging
import os
import socket
import subprocess
from datetime import datetime, timezone
from .base import SystemManager
from .utils import validate_domain

logger = logging.getLogger(__name__)


class SSLManager(SystemManager):
    """Manage SSL certificates with Let's Encrypt"""

    def __init__(self):
        super().__init__(require_root=True)

    def _validate_dns(self, domain: str, timeout: int = 5) -> bool:
        """
        Valida que el dominio resuelve en DNS.
        Si no resuelve, raise ValueError con mensaje claro.
        """
        old_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(timeout)
            socket.getaddrinfo(domain, None)
            logger.info(f"DNS validation passed for {domain}")
            return True
        except socket.gaierror as e:
            msg = f"DNS validation failed for {domain}: {e}. Asegúrate de que apunta a la IP correcta."
            logger.error(msg)
            raise ValueError(msg) from e
        finally:
            socket.setdefaulttimeout(old_timeout)

    def _get_certbot_path(self) -> str:
        """
        Retorna la ruta a certbot snap. Si no existe, intenta apt.
        IMPORTANTE: certbot 2.1.0 (apt) rompe TODO con Python 3.11+.
        Solo usar snap (5.x+) o más nueva.
        """
        # Preferir snap
        snap_certbot = "/snap/bin/certbot"
        if os.path.isfile(snap_certbot):
            logger.info("Using certbot from snap")
            return snap_certbot
        # Fallback a apt, pero avisar si es <2.1.0
        apt_certbot = "/usr/bin/certbot"
        if os.path.isfile(apt_certbot):
            logger.warning("Using certbot from apt (NOT snap). If version <2.1.0, SSL will fail!")
            return apt_certbot
        raise RuntimeError("certbot not found. Install with: snap install certbot --classic")

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

            # Validar DNS antes de intentar certbot
            self._validate_dns(domain_name)

            # Construir lista de dominios: principal + www si resuelve
            domains = [domain_name]
            try:
                self._validate_dns(f"www.{domain_name}", timeout=3)
                domains.append(f"www.{domain_name}")
                logger.info(f"www.{domain_name} resuelve, añadiendo al certificado")
            except ValueError:
                logger.info(f"www.{domain_name} no resuelve, omitiendo SAN")

            certbot_path = self._get_certbot_path()
            cmd = [certbot_path, "certonly", "--nginx", "--non-interactive", "--agree-tos",
                   "-m", "admin@svqpanel.local"]  # fallback — usar create_ssl_with_email siempre
            for d in domains:
                cmd += ["-d", d]

            # Run certbot con captura de stderr para debugging
            rc, stdout, stderr = self.execute_command(cmd, check=False)

            if rc != 0:
                error_msg = stderr.strip() if stderr else f"certbot exit code {rc}"
                logger.error(f"certbot failed: {error_msg}")
                logger.error(f"stdout: {stdout}")
                # Propagar el error real de certbot
                raise RuntimeError(f"certbot failed: {error_msg}")

            # Set up auto-renewal
            self.execute_command([
                "systemctl",
                "enable",
                "certbot.timer"
            ])

            logger.info(f"SSL cert created successfully: {domain_name} + {domains[1:]}")
            return {
                "success": True,
                "domain": domain_name,
                "status": f"Certificate created for {', '.join(domains)}"
            }

        except Exception as e:
            logger.error(f"Failed to create SSL: {str(e)}")
            raise

    def create_ssl_with_email(self, domain_name: str, email: str,
                              extra_domains: list = None) -> dict:
        """
        Igual que create_ssl pero con email configurable y SANs extra opcionales.
        """
        if not validate_domain(domain_name):
            raise ValueError(f"Invalid domain: {domain_name}")

        try:
            logger.info(f"Creating SSL cert (with email) for: {domain_name}")

            # Validar DNS
            self._validate_dns(domain_name)

            domains = [domain_name]
            try:
                self._validate_dns(f"www.{domain_name}", timeout=3)
                domains.append(f"www.{domain_name}")
            except ValueError:
                logger.info(f"www.{domain_name} no resuelve, omitiendo SAN")

            certbot_path = self._get_certbot_path()
            cmd = [certbot_path, "certonly", "--nginx"]
            for d in domains:
                cmd += ["-d", d]
            for d in (extra_domains or []):
                if validate_domain(d):
                    try:
                        self._validate_dns(d, timeout=3)
                        cmd += ["-d", d]
                    except ValueError:
                        logger.warning(f"Skipping extra domain {d} (DNS validation failed)")
            cmd += ["--non-interactive", "--agree-tos", "-m", email, "--expand"]

            rc, stdout, stderr = self.execute_command(cmd, check=False)
            if rc != 0:
                error_msg = stderr.strip() if stderr else f"certbot exit code {rc}"
                logger.error(f"certbot failed: {error_msg}")
                raise RuntimeError(f"certbot failed: {error_msg}")

            self.execute_command(["systemctl", "enable", "certbot.timer"], check=False)
            logger.info(f"SSL cert created: {domain_name} + {domains[1:]} + {extra_domains or []}")
            return {"success": True, "domain": domain_name}
        except Exception as e:
            logger.error(f"Failed to create SSL: {str(e)}")
            raise

    def expand_for_webmail(self, domain_name: str, email: str) -> dict:
        """
        Expande el cert del dominio principal para incluir webmail.{dominio} como SAN.
        Usar --expand evita el problema de SNI con nginx (cert compartido = un solo
        fichero, nginx no necesita elegir entre varios certs para la misma IP:puerto).
        """
        webmail_host = f"webmail.{domain_name}"

        # Validar DNS
        self._validate_dns(webmail_host)

        certbot_path = self._get_certbot_path()
        cmd = [
            certbot_path, "certonly", "--nginx",
            "--expand",
            "-d", domain_name,
            "-d", webmail_host,
            "--non-interactive", "--agree-tos", "-m", email,
        ]

        rc, stdout, stderr = self.execute_command(cmd, check=False)
        if rc != 0:
            error_msg = stderr.strip() if stderr else f"certbot exit code {rc}"
            logger.error(f"certbot expand failed for webmail: {error_msg}")
            raise RuntimeError(f"certbot failed: {error_msg}")

        logger.info(f"Cert expanded with webmail SAN: {webmail_host}")
        # El cert expandido vive en el directorio del dominio principal
        return {"success": True, "domain": webmail_host,
                "cert": f"/etc/letsencrypt/live/{domain_name}/fullchain.pem"}

    def expand_for_mail(self, domain_name: str, email: str) -> dict:
        """
        Emite un certificado independiente para mail.{dominio} usando --webroot.
        """
        import os
        from pathlib import Path

        mail_host = f"mail.{domain_name}"
        acme_root = "/var/www/svqpanel-acme"

        logger.info(f"Creating mail SSL cert for: {mail_host}")

        # Validar DNS
        self._validate_dns(mail_host)

        os.makedirs(f"{acme_root}/.well-known/acme-challenge", exist_ok=True)

        # Detectar IP pública del servidor
        srv_ip = None
        try:
            r = subprocess.run(
                ["ip", "-4", "addr", "show", "scope", "global"],
                capture_output=True, text=True, timeout=5,
            )
            for line in r.stdout.splitlines():
                line = line.strip()
                if line.startswith("inet "):
                    srv_ip = line.split()[1].split("/")[0]
                    break
        except Exception as e:
            logger.warning(f"Could not detect server IP: {e}")

        # Vhost temporal solo para el challenge ACME
        tmp_vhost_path = f"/etc/nginx/sites-available/svqpanel-acme-{domain_name}"
        tmp_link_path  = f"/etc/nginx/sites-enabled/svqpanel-acme-{domain_name}"
        ip_listen = f"    listen {srv_ip}:80;\n" if srv_ip else ""
        tmp_conf = (
            f"server {{\n"
            f"    listen 80;\n"
            f"{ip_listen}"
            f"    listen [::]:80;\n"
            f"    server_name {mail_host};\n"
            f"    location ^~ /.well-known {{\n"
            f"        root {acme_root};\n"
            f"        allow all;\n"
            f"    }}\n"
            f"    location / {{ return 444; }}\n"
            f"}}\n"
        )
        Path(tmp_vhost_path).write_text(tmp_conf)
        try:
            self.execute_command(["ln", "-sf", tmp_vhost_path, tmp_link_path], check=False)
            self.execute_command(["nginx", "-s", "reload"], check=False)

            certbot_path = self._get_certbot_path()
            cmd = [
                certbot_path, "certonly", "--webroot",
                "-w", acme_root,
                "-d", mail_host,
                "--non-interactive", "--agree-tos", "-m", email,
            ]

            rc, stdout, stderr = self.execute_command(cmd, check=False)
            if rc != 0:
                error_msg = stderr.strip() if stderr else f"certbot exit code {rc}"
                logger.error(f"certbot failed for mail: {error_msg}")
                raise RuntimeError(f"certbot failed: {error_msg}")

            logger.info(f"Mail TLS cert issued: {mail_host}")
            return {"success": True, "domain": mail_host,
                    "cert": f"/etc/letsencrypt/live/{mail_host}/fullchain.pem"}
        except Exception as e:
            logger.error(f"Failed to issue mail TLS cert: {e}")
            raise
        finally:
            # Limpiar vhost temporal siempre
            Path(tmp_link_path).unlink(missing_ok=True)
            Path(tmp_vhost_path).unlink(missing_ok=True)
            self.execute_command(["nginx", "-s", "reload"], check=False)

    def renew_ssl(self, domain_name: str) -> dict:
        """
        Renueva un certificado existente con certbot --force-renew.
        No necesita email — certbot lo tiene guardado de la emisión anterior.
        """
        if not validate_domain(domain_name):
            raise ValueError(f"Invalid domain: {domain_name}")

        certbot_path = self._get_certbot_path()
        cmd = [certbot_path, "renew", "--cert-name", domain_name, "--force-renew", "--non-interactive"]
        rc, stdout, stderr = self.execute_command(cmd, check=False)
        if rc != 0:
            error_msg = stderr.strip() if stderr else f"certbot exit code {rc}"
            logger.error(f"certbot renew failed: {error_msg}")
            raise RuntimeError(f"certbot renew failed: {error_msg}")

        logger.info(f"SSL cert renewed: {domain_name}")
        return {"success": True, "domain": domain_name}

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

            certbot_path = self._get_certbot_path()
            self.execute_command([
                certbot_path,
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
