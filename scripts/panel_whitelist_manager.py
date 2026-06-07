"""
Whitelist de IPs para el acceso al panel.

Restringe el acceso al panel (su puerto dedicado) a una lista de IPs/CIDR.
Se implementa con un fichero de include de nginx que contiene directivas
allow/deny, cargado dentro de los `location` del panel. Activar/desactivar o
cambiar las IPs solo reescribe ese fichero pequeño y recarga nginx — no hay que
regenerar el vhost completo.

Anti-bloqueo:
  - El .well-known/acme-challenge NUNCA se filtra (certbot debe poder renovar
    el SSL del panel aunque tu IP no esté en la lista). Eso se respeta porque
    el include solo se aplica en el `location /` y `location /api/`, no en el
    location del ACME.
  - Rescate por SSH: `python -m api.cli panel_whitelist_disable` borra el
    include y desactiva el flag en BD.

Formato del include cuando está ACTIVO:
    allow 1.2.3.4;
    allow 10.0.0.0/8;
    deny all;

Cuando está INACTIVO, el fichero queda vacío (nginx no filtra nada).
"""

import ipaddress
import logging
import os

from .base import SystemManager

logger = logging.getLogger(__name__)

# Fichero de include cargado por el vhost del panel dentro de sus location.
WHITELIST_INCLUDE = "/etc/nginx/snippets/svqpanel-whitelist.conf"


def parse_ip_entries(raw: str) -> list[str]:
    """
    Valida y normaliza las entradas (una IP/CIDR por línea o separadas por coma).
    Devuelve la lista de entradas válidas. Lanza ValueError si alguna es inválida.
    """
    if not raw:
        return []
    entries = []
    for token in raw.replace(",", "\n").splitlines():
        token = token.strip()
        if not token:
            continue
        try:
            # Acepta IP suelta (la convierte a /32 o /128 implícito) o CIDR
            if "/" in token:
                ipaddress.ip_network(token, strict=False)
            else:
                ipaddress.ip_address(token)
        except ValueError:
            raise ValueError(f"Entrada de IP no válida: '{token}'")
        entries.append(token)
    return entries


class PanelWhitelistManager(SystemManager):
    """Gestiona el include nginx de la whitelist del panel."""

    def __init__(self):
        super().__init__(require_root=True)

    def _reload_nginx(self) -> None:
        rc, _, err = self.execute_command(["nginx", "-t"], check=False)
        if rc != 0:
            raise RuntimeError(f"nginx -t falló: {err.strip()}")
        self.execute_command(["nginx", "-s", "reload"], check=False)

    def apply(self, enabled: bool, ips: list[str]) -> dict:
        """
        Escribe el include con las directivas allow/deny y recarga nginx.
        Si enabled=False, el include queda vacío (sin filtrado).
        """
        os.makedirs(os.path.dirname(WHITELIST_INCLUDE), exist_ok=True)

        if enabled and ips:
            lines = ["# SVQPanel — whitelist de acceso al panel (generado)\n"]
            for ip in ips:
                lines.append(f"allow {ip};\n")
            lines.append("deny all;\n")
            content = "".join(lines)
        else:
            content = "# SVQPanel — whitelist desactivada (sin filtrado)\n"

        with open(WHITELIST_INCLUDE, "w") as f:
            f.write(content)

        self._reload_nginx()
        logger.info("Whitelist del panel %s (%d IPs)",
                    "activada" if (enabled and ips) else "desactivada", len(ips))
        return {"success": True, "enabled": bool(enabled and ips), "count": len(ips)}

    def disable(self) -> dict:
        """Desactiva la whitelist (rescate). Vacía el include y recarga."""
        return self.apply(enabled=False, ips=[])

    def ensure_include_exists(self) -> None:
        """
        Garantiza que el fichero de include existe (aunque vacío), para que el
        vhost que hace `include` no falle si nunca se configuró la whitelist.
        """
        if not os.path.exists(WHITELIST_INCLUDE):
            os.makedirs(os.path.dirname(WHITELIST_INCLUDE), exist_ok=True)
            with open(WHITELIST_INCLUDE, "w") as f:
                f.write("# SVQPanel — whitelist desactivada (sin filtrado)\n")
