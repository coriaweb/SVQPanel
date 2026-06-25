"""IPv6 address management"""

import logging
import subprocess
import ipaddress
from pathlib import Path
from .base import SystemManager
from .utils import validate_ipv6

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Persistencia de las IPv6 de dominios vía systemd-networkd (NO netplan).
#
# El enfoque antiguo escribía un netplan (62-svqpanel-ipv6.yaml) que REDEFINÍA
# eth0 con solo `addresses:`. Al fusionarse con la config principal de eth0,
# netplan (systemd 252) entraba en conflicto de declaraciones → `netplan
# generate` fallaba → al reiniciar, eth0 NO se configuraba y el servidor se
# quedaba SIN RED. Bug crítico.
#
# Ahora usamos un DROP-IN de systemd-networkd: networkd FUSIONA los [Network] de
# los drop-ins con la config base de la interfaz, SIN el conflicto de "redefinir
# eth0". Las direcciones se añaden de forma aditiva y reversible.
# ─────────────────────────────────────────────────────────────────────────────

# Antiguo archivo netplan (defectuoso): si existe, lo eliminamos al migrar.
LEGACY_NETPLAN_FILE = Path("/etc/netplan/62-svqpanel-ipv6.yaml")
# Drop-in de networkd con las IPv6 de dominios. El nombre del .network base de
# netplan es 10-netplan-eth0.network; los drop-ins van en su carpeta .d/.
NETWORKD_DIR = Path("/etc/systemd/network")


def _dropin_path(interface: str) -> Path:
    """Drop-in de networkd para las IPv6 de dominios de una interfaz."""
    return NETWORKD_DIR / f"10-netplan-{interface}.network.d" / "svqpanel-ipv6.conf"


def _read_managed_ips(interface: str) -> list:
    """Lee las IPs en CIDR que SVQPanel gestiona actualmente (del drop-in)."""
    p = _dropin_path(interface)
    if not p.exists():
        return []
    ips = []
    for line in p.read_text().splitlines():
        s = line.strip()
        if s.startswith("Address=") and not s.startswith("#"):
            ips.append(s.split("=", 1)[1].strip())
    return ips


def build_dropin(addresses: list) -> str:
    """Genera el contenido del drop-in de networkd. Función PURA (testeable)."""
    lines = [
        "# Generado por SVQPanel — IPv6 de dominios. NO editar manualmente.",
        "# Drop-in aditivo de systemd-networkd (no redefine la interfaz).",
        "[Network]",
    ]
    for addr in addresses:
        lines.append(f"Address={addr}")
    return "\n".join(lines) + "\n"


def _write_dropin(interface: str, addresses: list):
    """Escribe (o elimina) el drop-in de networkd con la lista de IPs dada."""
    p = _dropin_path(interface)
    if not addresses:
        if p.exists():
            p.unlink()
            logger.info("networkd: drop-in IPv6 eliminado (sin IPs)")
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(build_dropin(addresses))
    logger.info(f"networkd: {len(addresses)} IPv6 escritas en {p}")


def _normalize_cidr(cidr: str) -> str:
    addr = cidr.split("/")[0]
    prefix = cidr.split("/")[1] if "/" in cidr else "64"
    return f"{ipaddress.IPv6Address(addr)}/{prefix}"


def _netplan_add(interface: str, cidr: str):
    """Añade una CIDR al drop-in de networkd y recarga (sin cortar la conexión)."""
    normalized = _normalize_cidr(cidr)
    current = []
    for a in _read_managed_ips(interface):
        try:
            current.append(_normalize_cidr(a))
        except Exception:
            current.append(a)
    if normalized not in current:
        current.append(normalized)
        _write_dropin(interface, current)
    _netplan_apply()


def _netplan_remove(interface: str, addr_only: str):
    """Elimina una IP (sin prefijo) del drop-in de networkd y recarga."""
    normalized = str(ipaddress.IPv6Address(addr_only))
    current = _read_managed_ips(interface)
    new_list = [
        a for a in current
        if str(ipaddress.IPv6Address(a.split("/")[0])) != normalized
    ]
    if len(new_list) == len(current):
        return  # no estaba gestionada por nosotros
    _write_dropin(interface, new_list)
    _netplan_apply()


def _netplan_apply():
    """Recarga systemd-networkd para activar los cambios sin cortar la conexión.

    (Mantiene el nombre por compatibilidad con los callers internos.)
    """
    try:
        result = subprocess.run(
            ["networkctl", "reload"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            logger.warning(f"networkctl reload devolvió error: {result.stderr[:200]}")
        else:
            logger.info("networkctl reload ejecutado correctamente")
    except Exception as e:
        logger.error(f"networkctl reload falló: {e}")


class IPv6Manager(SystemManager):
    """Manage IPv6 addresses"""

    def __init__(self):
        super().__init__(require_root=True)

    def assign_ipv6(self, interface: str, ipv6_address: str) -> dict:
        """
        Asigna una IPv6 a la interfaz en caliente y la persiste en netplan.
        ipv6_address debe incluir el prefijo: 2001:db8::1/64
        """
        addr_only = ipv6_address.split("/")[0]
        if not validate_ipv6(addr_only):
            raise ValueError(f"Invalid IPv6 address: {ipv6_address}")

        logger.info(f"Assigning IPv6 {ipv6_address} to {interface}")

        # 1. Añadir en caliente (idempotente)
        try:
            self.execute_command(["ip", "addr", "add", ipv6_address, "dev", interface])
        except Exception as e:
            err = str(e)
            if "exit status 2" in err or "File exists" in err or "RTNETLINK" in err or "already assigned" in err:
                logger.warning(f"IPv6 {ipv6_address} ya existía en {interface}, continuando")
            else:
                raise

        # 2. Persistir en netplan
        try:
            _netplan_add(interface, ipv6_address)
        except Exception as e:
            logger.warning(f"No se pudo persistir en netplan: {e}")

        logger.info(f"IPv6 assigned: {ipv6_address} on {interface}")
        return {"success": True, "interface": interface, "ipv6": ipv6_address}

    def remove_ipv6(self, interface: str, ipv6_address: str) -> dict:
        """
        Elimina una IPv6 de la interfaz en caliente y la quita de netplan.
        ipv6_address puede llevar o no prefijo.
        """
        addr_only = ipv6_address.split("/")[0]
        if not validate_ipv6(addr_only):
            raise ValueError(f"Invalid IPv6 address: {ipv6_address}")

        logger.info(f"Removing IPv6 {ipv6_address} from {interface}")

        # 1. Quitar en caliente
        try:
            self.execute_command(["ip", "addr", "del", ipv6_address, "dev", interface])
        except Exception as e:
            logger.warning(f"No se pudo quitar {ipv6_address} de la interfaz: {e}")

        # 2. Quitar de netplan
        try:
            _netplan_remove(interface, addr_only)
        except Exception as e:
            logger.warning(f"No se pudo eliminar de netplan: {e}")

        logger.info(f"IPv6 removed: {ipv6_address}")
        return {"success": True, "removed_ipv6": ipv6_address}

    @staticmethod
    def list_ipv6_addresses(interface: str = None) -> list:
        """Lista las IPv6 asignadas a las interfaces."""
        try:
            result = subprocess.run(
                ["ip", "-6", "addr", "show"],
                capture_output=True, text=True, check=True
            )
            lines = result.stdout.split("\n")
            return [line.strip() for line in lines if "inet6" in line]
        except Exception as e:
            logger.error(f"Failed to list IPv6: {str(e)}")
            return []
