"""
Servicio de ruta default IPv6 (persistente) para SVQPanel.

systemd-networkd 252 (Debian 12) NO instala de forma fiable una ruta default
IPv6 con gateway "onlink" fuera de la subred local (caso típico de muchos
proveedores: gateway tipo 2001:678:ff4:ffff:: que no está en el /64 del
servidor). El resultado: tras reiniciar, hay IPv6 asignada pero SIN salida.

Solución robusta e independiente del bug de networkd: un servicio systemd
oneshot que aplica `ip -6 route ... onlink` al arrancar, después de la red.

Idempotente: detecta el gateway IPv6 desde la config y solo instala el servicio
si hay gateway que aplicar.
"""
import logging
import os
import re

from scripts.base import SystemManager

logger = logging.getLogger(__name__)

SERVICE_PATH = "/etc/systemd/system/svqpanel-ipv6-route.service"
NETPLAN_MAIN = "/etc/netplan/01-svqpanel-net.yaml"


def _service_unit(gateway: str, interface: str = "eth0") -> str:
    """Unit del servicio. `gateway` es la IPv6 del router (onlink)."""
    return f"""[Unit]
Description=SVQPanel - ruta default IPv6 (onlink) tras levantar la red
After=systemd-networkd.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
# Idempotente: replace no falla si la ruta ya existe.
ExecStart=/bin/sh -c 'ip -6 route replace default via {gateway} dev {interface} onlink'

[Install]
WantedBy=multi-user.target
"""


def detect_ipv6_gateway() -> str:
    """Intenta deducir el gateway IPv6 del netplan principal (via: ... en la
    ruta ::/0). Devuelve la IPv6 del gateway o None."""
    try:
        with open(NETPLAN_MAIN) as f:
            content = f.read()
    except OSError:
        return None
    # Buscar el bloque de la ruta default IPv6: to: "::/0" ... via: "<gw>"
    m = re.search(r'to:\s*["\']?::/0["\']?.*?via:\s*["\']?([0-9a-fA-F:]+)["\']?',
                  content, re.DOTALL)
    if m:
        return m.group(1)
    return None


class IPv6RouteService(SystemManager):

    def install(self, gateway: str = None, interface: str = "eth0") -> dict:
        """Instala (o actualiza) el servicio de ruta IPv6. Si no se da gateway,
        intenta detectarlo del netplan principal. Idempotente."""
        gw = gateway or detect_ipv6_gateway()
        if not gw:
            logger.info("IPv6RouteService: sin gateway IPv6 detectado, nada que hacer")
            return {"success": True, "installed": False, "reason": "sin gateway IPv6"}
        with open(SERVICE_PATH, "w") as f:
            f.write(_service_unit(gw, interface))
        self.execute_command(["systemctl", "daemon-reload"], check=False)
        self.execute_command(
            ["systemctl", "enable", "--now", "svqpanel-ipv6-route.service"],
            check=False)
        logger.info(f"IPv6RouteService: instalado (gateway {gw} via {interface})")
        return {"success": True, "installed": True, "gateway": gw}


def cleanup_legacy_netplan() -> dict:
    """Elimina el netplan defectuoso 62-svqpanel-ipv6.yaml si existe (el que
    redefinía eth0 y rompía la red). Devuelve si se quitó algo."""
    legacy = "/etc/netplan/62-svqpanel-ipv6.yaml"
    removed = False
    if os.path.exists(legacy):
        try:
            os.remove(legacy)
            removed = True
            logger.info("Eliminado netplan defectuoso 62-svqpanel-ipv6.yaml")
        except OSError as e:
            logger.warning(f"No se pudo eliminar {legacy}: {e}")
    return {"removed": removed}
