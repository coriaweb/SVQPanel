"""IPv6 address management"""

import logging
import subprocess
import ipaddress
from pathlib import Path
from .base import SystemManager
from .utils import validate_ipv6

logger = logging.getLogger(__name__)

NETPLAN_FILE = Path("/etc/netplan/61-ipv6.yaml")


def _netplan_add(interface: str, cidr: str):
    """Añade una dirección CIDR al archivo netplan de IPs adicionales y aplica."""
    import yaml

    if NETPLAN_FILE.exists():
        data = yaml.safe_load(NETPLAN_FILE.read_text()) or {}
    else:
        data = {}

    # Estructura mínima si el archivo estaba vacío
    data.setdefault("network", {})
    data["network"].setdefault("version", 2)
    data["network"].setdefault("ethernets", {})
    data["network"]["ethernets"].setdefault(interface, {})
    iface = data["network"]["ethernets"][interface]
    iface.setdefault("dhcp6", False)
    iface.setdefault("addresses", [])

    # Normalizar a forma expandida para comparar sin duplicados
    addr_only = cidr.split("/")[0]
    prefix = cidr.split("/")[1] if "/" in cidr else "64"
    normalized = f"{ipaddress.IPv6Address(addr_only)}/{prefix}"

    existing = [str(a) for a in iface["addresses"]]
    if normalized not in existing:
        iface["addresses"].append(normalized)
        NETPLAN_FILE.write_text(yaml.dump(data, default_flow_style=False))
        logger.info(f"Netplan: añadida {normalized} a {interface}")

    _netplan_apply()


def _netplan_remove(interface: str, addr_only: str):
    """Elimina una dirección (sin prefijo) del archivo netplan y aplica."""
    import yaml

    if not NETPLAN_FILE.exists():
        return

    data = yaml.safe_load(NETPLAN_FILE.read_text()) or {}
    try:
        addresses = data["network"]["ethernets"][interface]["addresses"]
    except KeyError:
        return

    normalized = str(ipaddress.IPv6Address(addr_only))
    new_list = [a for a in addresses if str(ipaddress.IPv6Address(a.split("/")[0])) != normalized]
    if len(new_list) == len(addresses):
        return  # no estaba

    data["network"]["ethernets"][interface]["addresses"] = new_list
    NETPLAN_FILE.write_text(yaml.dump(data, default_flow_style=False))
    logger.info(f"Netplan: eliminada {addr_only} de {interface}")
    _netplan_apply()


def _netplan_apply():
    """Ejecuta netplan apply para activar los cambios sin cortar la conexión."""
    try:
        result = subprocess.run(
            ["netplan", "apply"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            logger.warning(f"netplan apply devolvió error: {result.stderr[:200]}")
        else:
            logger.info("netplan apply ejecutado correctamente")
    except Exception as e:
        logger.error(f"netplan apply falló: {e}")


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
