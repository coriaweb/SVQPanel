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

    def _run_certbot(self, cmd: list, line_cb=None):
        """
        Ejecuta certbot. Con line_cb, streama la salida (stdout+stderr mezclados)
        línea a línea llamando line_cb(línea) — es lo que permite a la UI enseñar
        el progreso real durante la emisión. Devuelve (rc, salida_completa).
        """
        if line_cb is None:
            rc, stdout, stderr = self.execute_command(cmd, check=False)
            return rc, (stderr or "").strip() or (stdout or "").strip()
        env = os.environ.copy()
        env["PATH"] = self._SYSTEM_PATH
        logger.info(f"Executing (streaming): {' '.join(cmd)}")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1, env=env)
        lines = []
        for raw in proc.stdout:
            line = raw.rstrip()
            if line.strip():
                lines.append(line)
                try:
                    line_cb(line)
                except Exception:
                    pass
        proc.wait()
        return proc.returncode, "\n".join(lines)

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
                              extra_domains: list = None, line_cb=None,
                              include_www: bool = True) -> dict:
        """
        Igual que create_ssl pero con email configurable y SANs extra opcionales.
        line_cb (opcional): recibe cada línea de salida de certbot en vivo.
        include_www=False para SUBDOMINIOS (y staging): su vhost no sirve www y,
        si www.<sub> resolvía al emitir (comodín, DNS del hosting anterior),
        entraba en el cert y la renovación fallaba ENTERA cuando dejaba de
        existir (certbot renueva con la lista de SAN guardada).
        """
        if not validate_domain(domain_name):
            raise ValueError(f"Invalid domain: {domain_name}")

        try:
            logger.info(f"Creating SSL cert (with email) for: {domain_name}")

            # Validar DNS
            self._validate_dns(domain_name)

            domains = [domain_name]
            if include_www:
                try:
                    self._validate_dns(f"www.{domain_name}", timeout=3)
                    domains.append(f"www.{domain_name}")
                except ValueError:
                    logger.info(f"www.{domain_name} no resuelve, omitiendo SAN")

            certbot_path = self._get_certbot_path()
            # --cert-name fija el lineage: sin él, quitar el www de un cert que
            # lo tenía crea "{dominio}-0001" en vez de reemitir el bueno.
            cmd = [certbot_path, "certonly", "--nginx", "--cert-name", domain_name]
            for d in domains:
                cmd += ["-d", d]
            # Dominios alias (y su www.) entran en el certificado del dominio
            # solo si ya apuntan aquí; los que no, se añaden cuando apunten.
            alias_names = [n for n in self._alias_cert_names(domain_name)
                           if n not in domains and self.points_here(n)]
            domains += alias_names
            for d in alias_names:
                cmd += ["-d", d]
            for d in (extra_domains or []):
                if d in domains:
                    continue
                if validate_domain(d):
                    try:
                        self._validate_dns(d, timeout=3)
                        cmd += ["-d", d]
                    except ValueError:
                        logger.warning(f"Skipping extra domain {d} (DNS validation failed)")
            cmd += ["--non-interactive", "--agree-tos", "-m", email, "--expand"]

            rc, output = self._run_certbot(cmd, line_cb=line_cb)
            if rc != 0:
                error_msg = output.strip() or f"certbot exit code {rc}"
                logger.error(f"certbot failed: {error_msg}")
                raise RuntimeError(f"certbot failed: {error_msg}")

            self.execute_command(["systemctl", "enable", "certbot.timer"], check=False)
            logger.info(f"SSL cert created: {domain_name} + {domains[1:]} + {extra_domains or []}")
            return {"success": True, "domain": domain_name}
        except Exception as e:
            logger.error(f"Failed to create SSL: {str(e)}")
            raise

    @staticmethod
    def _local_ips() -> set:
        """IPs globales configuradas en este servidor (IPv4 e IPv6)."""
        import ipaddress
        ips = set()
        try:
            r = subprocess.run(["ip", "-o", "addr", "show", "scope", "global"],
                               capture_output=True, text=True, timeout=5)
            for line in r.stdout.splitlines():
                parts = line.split()
                if "inet" in parts or "inet6" in parts:
                    i = parts.index("inet") if "inet" in parts else parts.index("inet6")
                    ips.add(str(ipaddress.ip_address(parts[i + 1].split("/")[0])))
        except Exception:
            pass
        return ips

    def points_here(self, name: str, timeout: int = 3) -> bool:
        """¿TODAS las IPs (A y AAAA) de `name` son de este servidor?

        Más estricto que _validate_dns (que solo mira que resuelva): un alias
        recién añadido suele apuntar aún al hosting anterior, y si entra en la
        petición a Let's Encrypt el reto falla y tumba la emisión ENTERA. Let's
        Encrypt prueba también por IPv6: un AAAA que apunte fuera también la tumba.
        """
        import ipaddress
        old = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(timeout)
            addrs = {str(ipaddress.ip_address(ai[4][0].split("%")[0]))
                     for ai in socket.getaddrinfo(name, None)}
        except (socket.gaierror, ValueError, OSError):
            return False
        finally:
            socket.setdefaulttimeout(old)
        local = self._local_ips()
        return bool(addrs) and bool(local) and addrs <= local

    @staticmethod
    def _auth_args(domain_name: str) -> list:
        """Cómo valida certbot el certificado de este dominio: por DNS (wildcard,
        con el hook del panel) o por HTTP con nginx. Ampliar o reducir un
        wildcard con --nginx fallaría: *.dominio solo se valida por DNS."""
        from scripts import acme_dns
        return acme_dns.hook_args() if acme_dns.is_dns_lineage(domain_name) else ["--nginx"]

    def create_wildcard(self, domain_name: str, email: str, line_cb=None) -> dict:
        """Certificado dominio + *.dominio validado por DNS (TXT en la zona del
        panel). Cubre www., mail., webmail. y cualquier subdominio de un nivel.
        Mismo lineage (--cert-name) que el normal: el vhost no cambia de ruta.
        Los alias entran solo si su zona también está en el panel."""
        from scripts import acme_dns
        from api.models.database import SessionLocal, load_all_models
        if not validate_domain(domain_name):
            raise ValueError(f"Invalid domain: {domain_name}")
        load_all_models()
        db = SessionLocal()
        try:
            if not acme_dns.can_validate(db, domain_name):
                raise ValueError(
                    f"La zona DNS de {domain_name} no está en este panel. El certificado wildcard se "
                    "valida creando un registro TXT, así que el dominio tiene que usar nuestros DNS.")
            aliases = [n for n in self._alias_cert_names(domain_name)
                       if acme_dns.can_validate(db, n)]
        finally:
            db.close()
        names = [domain_name, f"*.{domain_name}"] + [n for n in aliases if n not in (domain_name,)]
        cmd = [self._get_certbot_path(), "certonly", *acme_dns.hook_args(),
               "--cert-name", domain_name]
        for d in dict.fromkeys(names):
            cmd += ["-d", d]
        cmd += ["--non-interactive", "--agree-tos", "-m", email, "--expand"]
        rc, output = self._run_certbot(cmd, line_cb=line_cb)
        if rc != 0:
            raise RuntimeError(f"certbot failed: {output.strip()[-600:] or f'exit code {rc}'}")
        self.execute_command(["systemctl", "enable", "certbot.timer"], check=False)
        logger.info(f"Wildcard SSL emitido: {names}")
        return {"success": True, "domain": domain_name, "names": names}

    @staticmethod
    def _alias_cert_names(domain_name: str) -> list:
        """Nombres de los alias del dominio para su certificado (alias + www.alias)."""
        try:
            from api.models.database import SessionLocal
            from api.models.models_domain import Domain
            from api.models.models_domain_alias import DomainAlias
            db = SessionLocal()
            try:
                d = db.query(Domain).filter(Domain.domain_name == domain_name).first()
                if not d:
                    return []
                names = []
                for a in db.query(DomainAlias).filter(DomainAlias.domain_id == d.id).all():
                    names += [a.alias_name, f"www.{a.alias_name}"]
                return names
            finally:
                db.close()
        except Exception:
            return []

    def sync_cert_names(self, domain_name: str, add: list = None,
                        remove: list = None, line_cb=None) -> dict:
        """Amplía o reduce el certificado VIGENTE del dominio (alias).

        Conserva todos los nombres actuales (www, webmail…), añade los de `add`
        que resuelvan aquí y quita los de `remove`. Quitar es tan importante como
        añadir: si un alias borrado se queda en el certificado, la renovación
        falla ENTERA cuando deja de apuntar aquí (certbot renueva con la lista
        guardada). Sin certificado, no hace nada (se incluirán al emitirlo).
        Devuelve {"changed", "names", "skipped"}.
        """
        from scripts import ssl_paths, acme_dns
        cert = f"/etc/letsencrypt/live/{domain_name}/cert.pem"
        # Certificado propio (subido): sus nombres los decide quien lo compró.
        if ssl_paths.has_custom(domain_name) or not os.path.exists(cert):
            return {"changed": False, "names": [], "skipped": list(add or [])}
        dns_mode = acme_dns.is_dns_lineage(domain_name)
        existing = self._cert_domains(cert)
        if not existing:
            return {"changed": False, "names": [], "skipped": list(add or [])}
        drop = set(remove or [])
        wanted = [n for n in existing if n not in drop]
        skipped = []
        for n in (add or []):
            if n in wanted:
                continue
            ok = self.points_here(n)
            if dns_mode:   # wildcard: se valida por DNS, hace falta la zona aquí
                from api.models.database import SessionLocal
                _db = SessionLocal()
                try:
                    ok = acme_dns.can_validate(_db, n)
                finally:
                    _db.close()
            if ok:
                wanted.append(n)
            else:
                skipped.append(n)
        if wanted == existing:
            return {"changed": False, "names": existing, "skipped": skipped}
        cmd = [self._get_certbot_path(), "certonly", *self._auth_args(domain_name), "--expand",
               "--cert-name", domain_name]
        for d in wanted:
            cmd += ["-d", d]
        cmd += ["--non-interactive", "--agree-tos"]
        rc, output = self._run_certbot(cmd, line_cb=line_cb)
        if rc != 0:
            raise RuntimeError(f"certbot: {output.strip()[-400:] or f'exit code {rc}'}")
        logger.info(f"Cert {domain_name}: SAN {existing} → {wanted}")
        return {"changed": True, "names": wanted, "skipped": skipped}

    def _cert_domains(self, cert_path: str) -> list:
        """Devuelve la lista de dominios (SAN) de un certificado. [] si falla."""
        try:
            rc, out, err = self.execute_command(
                ["openssl", "x509", "-in", cert_path, "-noout", "-ext", "subjectAltName"],
                check=False)
            doms = []
            for tok in (out or "").replace(",", " ").split():
                tok = tok.strip()
                if tok.startswith("DNS:"):
                    doms.append(tok[4:])
            return doms
        except Exception:
            return []

    def expand_for_webmail(self, domain_name: str, email: str, line_cb=None) -> dict:
        """
        Emite o expande el cert para webmail.{dominio}:
        - Si ya existe cert del dominio principal → --expand añadiendo webmail como SAN
          (evita conflicto SNI en nginx: un solo cert para la misma IP:443)
        - Si no existe cert del dominio (solo correo, sin web) → cert independiente
          para webmail.{dominio} (no hay conflicto porque tampoco hay vhost web con SSL)
        """
        webmail_host = f"webmail.{domain_name}"
        from scripts import ssl_paths
        if ssl_paths.covers(ssl_paths.names_of(domain_name), webmail_host):
            # Ya cubierto (wildcard *.dominio, o un certificado propio que lo incluye)
            return {"success": True, "domain": webmail_host,
                    "cert": ssl_paths.existing_cert(domain_name)}
        self._validate_dns(webmail_host)

        certbot_path = self._get_certbot_path()
        domain_cert = f"/etc/letsencrypt/live/{domain_name}/fullchain.pem"

        if os.path.exists(domain_cert):
            # Dominio tiene cert web → expandir para incluir webmail como SAN.
            # IMPORTANTE: hay que pasar TODOS los SAN actuales + webmail. Si solo
            # se pasan -d dominio -d webmail, certbot genera un cert SIN www (ni
            # los demás SAN), rompiendo la web canónica y dejando webmail con un
            # cert que no le sirve. Leemos los SAN del cert vigente y los unimos.
            existing = self._cert_domains(domain_cert)
            wanted = list(dict.fromkeys(existing + [domain_name, webmail_host]))
            # --cert-name fija el lineage al del dominio: sin esto, certbot puede
            # crear un cert duplicado "{dominio}-0001" en vez de expandir el bueno
            # (deja el vhost apuntando al viejo, sin webmail → candado rojo).
            cmd = [certbot_path, "certonly", *self._auth_args(domain_name), "--expand",
                   "--cert-name", domain_name]
            for d in wanted:
                cmd += ["-d", d]
            cmd += ["--non-interactive", "--agree-tos", "-m", email]
            rc, output = self._run_certbot(cmd, line_cb=line_cb)
            if rc != 0:
                raise RuntimeError(f"certbot expand failed: {output.strip() or f'exit code {rc}'}")
            logger.info(f"Cert expanded (SANs={wanted}) with webmail: {webmail_host}")
            return {"success": True, "domain": webmail_host,
                    "cert": domain_cert}
        else:
            # Solo correo, sin web → cert independiente para webmail
            webroot = "/var/www/webmail"
            os.makedirs(f"{webroot}/.well-known/acme-challenge", exist_ok=True)
            cmd = [
                certbot_path, "certonly", "--webroot", "-w", webroot,
                "-d", webmail_host,
                "--non-interactive", "--agree-tos", "-m", email,
            ]
            rc, output = self._run_certbot(cmd, line_cb=line_cb)
            if rc != 0:
                raise RuntimeError(f"certbot failed: {output.strip() or f'exit code {rc}'}")
            logger.info(f"Webmail standalone cert issued: {webmail_host}")
            return {"success": True, "domain": webmail_host,
                    "cert": f"/etc/letsencrypt/live/{webmail_host}/fullchain.pem"}

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

        # Vhost temporal solo para el challenge ACME. listen GENÉRICO (sin atar a
        # la IP): atarlo haría a este vhost efímero el default de la IP durante la
        # emisión y podría capturar tráfico de otros server_name. Enruta por name.
        tmp_vhost_path = f"/etc/nginx/sites-available/svqpanel-acme-{domain_name}"
        tmp_link_path  = f"/etc/nginx/sites-enabled/svqpanel-acme-{domain_name}"
        tmp_conf = (
            f"server {{\n"
            f"    listen 80;\n"
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
        from scripts import ssl_paths, acme_dns
        cert_path = ssl_paths.existing_cert(domain_name)   # propio o Let's Encrypt
        if not cert_path:
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

            src = ssl_paths.source(domain_name)
            return {
                # custom = subido (no se renueva solo); letsencrypt (wildcard = por DNS)
                "source":        src,
                "wildcard":      any(n.startswith("*.") for n in sans),
                "auto_renew":    src == "letsencrypt",
                "dns_validated": src == "letsencrypt" and acme_dns.is_dns_lineage(domain_name),
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
