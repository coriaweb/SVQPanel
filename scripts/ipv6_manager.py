"""IPv6 address management"""

import logging
import subprocess
import ipaddress
from pathlib import Path
from .base import SystemManager
from .utils import validate_ipv6

logger = logging.getLogger(__name__)

# Archivo netplan exclusivo para IPs de dominios gestionados por SVQPanel.
# Se escribe completamente en cada operación — no se toca el 61-ipv6.yaml del sistema.
NETPLAN_FILE = Path("/etc/netplan/62-svqpanel-ipv6.yaml")


def _read_managed_ips(interface: str) -> list:
    """Lee las IPs en CIDR que SVQPanel gestiona actualmente."""
    if not NETPLAN_FILE.exists():
        return []
    lines = NETPLAN_FILE.read_text().splitlines()
    ips = []
    in_addresses = False
    for line in lines:
        stripped = line.strip()
        if stripped == "addresses:":
            in_addresses = True
            continue
        if in_addresses:
            if stripped.startswith("- "):
                ips.append(stripped[2:].strip())
            elif stripped and not stripped.startswith("#"):
                in_addresses = False
    return ips


def _write_netplan(interface: str, addresses: list):
    """Escribe el archivo netplan de SVQPanel con la lista de IPs dada."""
    if not addresses:
        # Sin IPs que gestionar: eliminar el archivo si existe
        if NETPLAN_FILE.exists():
            NETPLAN_FILE.unlink()
            logger.info("Netplan SVQPanel: archivo eliminado (sin IPs)")
        return

    lines = [
        "# Generado por SVQPanel — no editar manualmente",
        "network:",
        "  version: 2",
        "  ethernets:",
        f"    {interface}:",
        "      addresses:",
    ]
    for addr in addresses:
        lines.append(f"        - {addr}")
    NETPLAN_FILE.write_text("\n".join(lines) + "\n")
    logger.info(f"Netplan SVQPanel: {len(addresses)} IPs escritas en {NETPLAN_FILE}")


def _netplan_add(interface: str, cidr: str):
    """Añade una CIDR al archivo netplan de SVQPanel y aplica."""
    addr_only = cidr.split("/")[0]
    prefix = cidr.split("/")[1] if "/" in cidr else "64"
    normalized = f"{ipaddress.IPv6Address(addr_only)}/{prefix}"

    current = _read_managed_ips(interface)
    # Normalizar las existentes para comparar sin duplicados
    current_normalized = []
    for a in current:
        try:
            p = a.split("/")[1] if "/" in a else "64"
            current_normalized.append(f"{ipaddress.IPv6Address(a.split('/')[0])}/{p}")
        except Exception:
            current_normalized.append(a)

    if normalized not in current_normalized:
        current_normalized.append(normalized)
        _write_netplan(interface, current_normalized)

    _netplan_apply()


def _netplan_remove(interface: str, addr_only: str):
    """Elimina una IP (sin prefijo) del archivo netplan de SVQPanel y aplica."""
    normalized = str(ipaddress.IPv6Address(addr_only))
    current = _read_managed_ips(interface)
    new_list = [
        a for a in current
        if str(ipaddress.IPv6Address(a.split("/")[0])) != normalized
    ]
    if len(new_list) == len(current):
        return  # no estaba gestionada por nosotros
    _write_netplan(interface, new_list)
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
