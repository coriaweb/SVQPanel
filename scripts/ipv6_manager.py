"""IPv6 address management"""

import logging
from .base import SystemManager
from .utils import validate_ipv6

logger = logging.getLogger(__name__)


class IPv6Manager(SystemManager):
    """Manage IPv6 addresses"""

    def __init__(self):
        super().__init__(require_root=True)

    def assign_ipv6(self, interface: str, ipv6_address: str) -> dict:
        """
        Assign IPv6 address to interface

        Args:
            interface: Network interface (eth0, ens0, etc)
            ipv6_address: IPv6 address with prefix (2001:db8::1/64)

        Returns:
            {'success': True, 'interface': 'eth0', 'ipv6': '2001:db8::1/64'}
        """
        if not validate_ipv6(ipv6_address.split("/")[0]):
            raise ValueError(f"Invalid IPv6 address: {ipv6_address}")

        try:
            logger.info(f"Assigning IPv6 {ipv6_address} to {interface}")

            # Add IPv6 address
            self.execute_command([
                "ip",
                "addr",
                "add",
                ipv6_address,
                "dev",
                interface
            ])

            logger.info(f"IPv6 assigned: {ipv6_address} on {interface}")
            return {
                "success": True,
                "interface": interface,
                "ipv6": ipv6_address
            }

        except Exception as e:
            logger.error(f"Failed to assign IPv6: {str(e)}")
            raise

    def remove_ipv6(self, interface: str, ipv6_address: str) -> dict:
        """
        Remove IPv6 address from interface

        Args:
            interface: Network interface
            ipv6_address: IPv6 address

        Returns:
            {'success': True, 'removed_ipv6': '2001:db8::1/64'}
        """
        if not validate_ipv6(ipv6_address.split("/")[0]):
            raise ValueError(f"Invalid IPv6 address: {ipv6_address}")

        try:
            logger.info(f"Removing IPv6 {ipv6_address} from {interface}")

            self.execute_command([
                "ip",
                "addr",
                "del",
                ipv6_address,
                "dev",
                interface
            ])

            logger.info(f"IPv6 removed: {ipv6_address}")
            return {
                "success": True,
                "removed_ipv6": ipv6_address
            }

        except Exception as e:
            logger.error(f"Failed to remove IPv6: {str(e)}")
            raise

    @staticmethod
    def list_ipv6_addresses(interface: str = None) -> list:
        """List IPv6 addresses on interface"""
        try:
            import subprocess
            result = subprocess.run(
                ["ip", "-6", "addr", "show"],
                capture_output=True,
                text=True,
                check=True
            )
            # Simple parsing - could be improved
            lines = result.stdout.split("\n")
            ipv6_addrs = [
                line.strip() for line in lines
                if "inet6" in line
            ]
            return ipv6_addrs
        except Exception as e:
            logger.error(f"Failed to list IPv6: {str(e)}")
            return []
