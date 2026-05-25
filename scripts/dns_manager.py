"""
DNS management — gestión de zonas BIND9
Genera zone files a partir de los registros en BD y recarga named.
"""

import os
import re
import logging
from datetime import datetime
from typing import List, Dict, Optional
from .base import SystemManager

logger = logging.getLogger(__name__)

ZONES_DIR       = "/etc/bind/zones"
NAMED_CONF_ZONES = "/etc/bind/named.conf.zones"   # incluido desde named.conf.local


class DNSManager(SystemManager):
    """Gestión de zonas BIND9"""

    def __init__(self):
        super().__init__(require_root=True)

    # ─────────────────────── helpers ────────────────────────────────────────

    def zone_file_path(self, domain: str) -> str:
        return f"{ZONES_DIR}/db.{domain}"

    def _next_serial(self, current_serial: Optional[int] = None) -> int:
        """Genera serial YYYYMMDDNN incrementando si ya existía uno hoy"""
        today = datetime.utcnow().strftime("%Y%m%d")
        base  = int(today) * 100    # p.ej. 2026052500

        if current_serial and current_serial >= base:
            # Mismo día: incrementar contador (NN)
            return current_serial + 1
        return base + 1

    def _write_named_conf_zones(self, domains: List[str]):
        """Regenera /etc/bind/named.conf.zones con todas las zonas activas"""
        lines = ["# Generado automáticamente por SVQPanel — no editar a mano\n\n"]
        for domain in sorted(domains):
            zone_file = self.zone_file_path(domain)
            lines.append(
                f'zone "{domain}" IN {{\n'
                f'    type master;\n'
                f'    file "{zone_file}";\n'
                f'    allow-transfer {{ none; }};\n'
                f'    allow-update {{ none; }};\n'
                f'}};\n\n'
            )
        with open(NAMED_CONF_ZONES, "w") as f:
            f.writelines(lines)
        logger.info(f"named.conf.zones actualizado con {len(domains)} zona(s)")

    def _reload_bind(self) -> bool:
        """Test + reload named"""
        try:
            self.execute_command(["named-checkconf"], check=False)
            self.execute_command(["rndc", "reload"])
            logger.info("BIND9 recargado correctamente")
            return True
        except Exception as e:
            logger.error(f"Error recargando BIND9: {e}")
            return False

    # ─────────────────────── zona ───────────────────────────────────────────

    def create_zone(
        self,
        domain: str,
        ipv4: Optional[str],
        ipv6: Optional[str] = None,
        ns1: Optional[str] = None,
        ns2: Optional[str] = None,
        serial: int = None,
    ) -> int:
        """
        Crea zone file con plantilla Hestia-style.
        Devuelve el serial generado.
        """
        os.makedirs(ZONES_DIR, exist_ok=True)

        serial = serial or self._next_serial()
        hostname = ns1 or "ns1.svqpanel.local"
        ns2_host = ns2 or "ns2.svqpanel.local"

        records = []

        # SOA
        records.append(
            f"$TTL 14400\n"
            f"@\tIN\tSOA\t{hostname}. hostmaster.{domain}. (\n"
            f"\t\t\t{serial}\t; serial\n"
            f"\t\t\t28800\t\t; refresh\n"
            f"\t\t\t7200\t\t; retry\n"
            f"\t\t\t604800\t\t; expire\n"
            f"\t\t\t86400 )\t\t; minimum TTL\n"
        )

        # NS
        records.append(f"\n; Nameservers\n")
        records.append(f"@\tIN\tNS\t{hostname}.\n")
        records.append(f"@\tIN\tNS\t{ns2_host}.\n")

        # A / AAAA
        if ipv4:
            records.append(f"\n; A records\n")
            records.append(f"@\tIN\tA\t{ipv4}\n")
            records.append(f"www\tIN\tA\t{ipv4}\n")
            records.append(f"mail\tIN\tA\t{ipv4}\n")
            records.append(f"ftp\tIN\tA\t{ipv4}\n")

        if ipv6:
            records.append(f"\n; AAAA records\n")
            records.append(f"@\tIN\tAAAA\t{ipv6}\n")
            records.append(f"www\tIN\tAAAA\t{ipv6}\n")

        # MX
        records.append(f"\n; Mail\n")
        records.append(f"@\tIN\tMX\t10\tmail.{domain}.\n")

        # TXT SPF
        records.append(f"\n; TXT\n")
        records.append(f'@\tIN\tTXT\t"v=spf1 a mx ~all"\n')

        zone_content = "".join(records)

        with open(self.zone_file_path(domain), "w") as f:
            f.write(zone_content)

        logger.info(f"Zone file creado: {self.zone_file_path(domain)}")
        return serial

    def write_zone_from_records(
        self,
        domain: str,
        serial: int,
        records: List[Dict],
        ns1: Optional[str] = None,
    ) -> bool:
        """
        Regenera zone file completo desde la lista de registros de BD.
        Cada dict: {record_type, name, content, ttl, priority}
        """
        os.makedirs(ZONES_DIR, exist_ok=True)
        hostname = ns1 or "ns1.svqpanel.local"

        lines = [
            f"$TTL 14400\n",
            f"@\tIN\tSOA\t{hostname}. hostmaster.{domain}. (\n",
            f"\t\t\t{serial}\t; serial\n",
            f"\t\t\t28800\t\t; refresh\n",
            f"\t\t\t7200\t\t; retry\n",
            f"\t\t\t604800\t\t; expire\n",
            f"\t\t\t86400 )\t\t; minimum TTL\n",
            f"\n; Registros generados por SVQPanel\n",
        ]

        for r in records:
            name    = r["name"]
            rtype   = r["record_type"]
            content = r["content"]
            ttl     = r.get("ttl", 14400)
            prio    = r.get("priority", 0)

            if rtype == "MX":
                lines.append(f"{name}\t{ttl}\tIN\t{rtype}\t{prio}\t{content}\n")
            elif rtype == "SRV":
                lines.append(f"{name}\t{ttl}\tIN\t{rtype}\t{prio}\t{content}\n")
            elif rtype == "TXT":
                # TXT content debe ir entre comillas si no las tiene ya
                if not content.startswith('"'):
                    content = f'"{content}"'
                lines.append(f"{name}\t{ttl}\tIN\t{rtype}\t{content}\n")
            else:
                lines.append(f"{name}\t{ttl}\tIN\t{rtype}\t{content}\n")

        with open(self.zone_file_path(domain), "w") as f:
            f.writelines(lines)

        logger.info(f"Zone file regenerado: {domain} ({len(records)} registros)")
        return True

    def delete_zone(self, domain: str, all_domains: List[str] = None):
        """Elimina zone file y actualiza named.conf.zones"""
        zone_file = self.zone_file_path(domain)
        if os.path.exists(zone_file):
            os.remove(zone_file)
            logger.info(f"Zone file eliminado: {zone_file}")

        # Regenerar named.conf.zones sin este dominio
        remaining = [d for d in (all_domains or []) if d != domain]
        self._write_named_conf_zones(remaining)
        self._reload_bind()

    def reload_zone(self, domain: str, all_domains: List[str] = None):
        """Actualiza named.conf.zones y recarga BIND9"""
        domains_to_write = list(all_domains or [domain])
        if domain not in domains_to_write:
            domains_to_write.append(domain)
        self._write_named_conf_zones(domains_to_write)
        self._reload_bind()

    # ─────────────────────── setup inicial ──────────────────────────────────

    def setup_bind(self):
        """
        Configura BIND9 para SVQPanel:
        - Crea /etc/bind/zones/
        - Crea named.conf.zones vacío
        - Añade include a named.conf.local si no existe
        """
        os.makedirs(ZONES_DIR, exist_ok=True)
        self.execute_command(["chown", "root:bind", ZONES_DIR])
        self.execute_command(["chmod", "775", ZONES_DIR])

        if not os.path.exists(NAMED_CONF_ZONES):
            with open(NAMED_CONF_ZONES, "w") as f:
                f.write("# SVQPanel DNS zones — generado automáticamente\n")
            logger.info(f"Creado {NAMED_CONF_ZONES}")

        # Añadir include a named.conf.local si no está ya
        named_local = "/etc/bind/named.conf.local"
        include_line = f'include "{NAMED_CONF_ZONES}";\n'
        if os.path.exists(named_local):
            with open(named_local, "r") as f:
                content = f.read()
            if NAMED_CONF_ZONES not in content:
                with open(named_local, "a") as f:
                    f.write(f"\n{include_line}")
                logger.info("Include añadido a named.conf.local")

        self._reload_bind()
        logger.info("BIND9 configurado para SVQPanel")
