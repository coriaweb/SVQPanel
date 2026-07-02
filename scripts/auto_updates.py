"""
Actualizaciones automáticas de SEGURIDAD del sistema operativo (Debian).

Configura `unattended-upgrades` para aplicar SOLO los parches del repositorio de
seguridad (no dist-upgrades que puedan romper servicios), de forma desatendida.
Pensado para una flota de servidores: cierra vulnerabilidades del SO sin que el
admin tenga que entrar a cada máquina.

Política aplicada (drop-in propio, reversible borrándolo):
  - Solo origin de seguridad (Debian-Security).
  - NO reinicio automático del servidor (Automatic-Reboot "false"): el admin
    decide cuándo reiniciar si un paquete lo pide (kernel, libc).
  - Limpieza de dependencias y paquetes viejos.
  - Log en /var/log/unattended-upgrades/.

El panel solo escribe drop-ins PROPIOS (50-svqpanel-*), nunca toca los de Debian.
"""
import logging
import os
import re
from typing import Dict

from scripts.base import SystemManager

logger = logging.getLogger(__name__)

APT_PERIODIC = "/etc/apt/apt.conf.d/20svqpanel-auto-upgrades"
UU_DROPIN    = "/etc/apt/apt.conf.d/52svqpanel-unattended"
UU_LOG_DIR   = "/var/log/unattended-upgrades"

# Activa la descarga + aplicación automática diaria (solo seguridad).
_PERIODIC_CONF = """// SVQPanel — actualizaciones automáticas de seguridad. NO editar a mano.
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
"""

# Restringe a origin de seguridad y desactiva el reinicio automático.
_UU_CONF = """// SVQPanel — política de unattended-upgrades. NO editar a mano.
Unattended-Upgrade::Origins-Pattern {
    "origin=Debian,codename=${distro_codename},label=Debian-Security";
    "origin=Debian,codename=${distro_codename}-security,label=Debian-Security";
};
// NO reiniciar el servidor automáticamente: lo decide el admin.
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Mail "";
"""


class AutoUpdatesManager(SystemManager):

    def available(self) -> bool:
        return os.path.exists("/etc/debian_version")

    def install(self) -> Dict:
        """Instala y configura unattended-upgrades (idempotente)."""
        if not self.available():
            return {"success": False, "reason": "no es Debian"}
        # 1) Paquete.
        self.execute_command(
            ["apt-get", "install", "-y", "-qq", "unattended-upgrades"], check=False)
        # 2) Config (drop-ins propios).
        self._write(APT_PERIODIC, _PERIODIC_CONF)
        self._write(UU_DROPIN, _UU_CONF)
        # 3) Habilitar el servicio/timer.
        self.execute_command(["systemctl", "enable", "--now",
                              "unattended-upgrades"], check=False)
        logger.info("unattended-upgrades configurado (solo seguridad, sin reboot auto)")
        return {"success": True}

    def disable(self) -> Dict:
        """Desactiva la aplicación automática (deja el paquete instalado)."""
        self._write(APT_PERIODIC,
                    '// SVQPanel — auto-updates DESACTIVADO.\n'
                    'APT::Periodic::Unattended-Upgrade "0";\n')
        return {"success": True}

    def _write(self, path: str, content: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)

    def status(self) -> Dict:
        """Estado actual para el panel."""
        if not self.available():
            return {"available": False}
        enabled = self._is_enabled()
        return {
            "available": True,
            "installed": os.path.exists("/usr/bin/unattended-upgrade"),
            "enabled": enabled,
            "security_only": os.path.exists(UU_DROPIN),
            "auto_reboot": self._auto_reboot(),
            "pending_security": self.count_pending_security(),
            "last_run": self._last_run(),
        }

    def _is_enabled(self) -> bool:
        try:
            with open(APT_PERIODIC) as f:
                return 'Unattended-Upgrade "1"' in f.read()
        except OSError:
            return False

    def _auto_reboot(self) -> bool:
        try:
            with open(UU_DROPIN) as f:
                return 'Automatic-Reboot "true"' in f.read()
        except OSError:
            return False

    def count_pending_security(self) -> int:
        """Nº de paquetes con actualización de seguridad pendiente."""
        rc, out, _ = self.execute_command(
            ["apt-get", "-s", "upgrade"], check=False)
        if rc != 0 or not out:
            return 0
        return count_security_upgrades(out)

    def _last_run(self) -> str:
        """Fecha de la última ejecución (de la marca de stamp de apt)."""
        for stamp in ("/var/lib/apt/periodic/unattended-upgrades-stamp",
                      "/var/lib/apt/periodic/upgrade-stamp"):
            try:
                import datetime
                ts = os.path.getmtime(stamp)
                # Con zona explícita (+00:00): el frontend asume UTC en las
                # fechas naive, y esta viene de un mtime (epoch), no de la BD.
                return datetime.datetime.fromtimestamp(
                    ts, tz=datetime.timezone.utc).isoformat(timespec="seconds")
            except OSError:
                continue
        return None

    def run_now(self) -> Dict:
        """Lanza una pasada de unattended-upgrade ahora (bajo demanda)."""
        rc, out, err = self.execute_command(
            ["unattended-upgrade", "-v"], check=False)
        return {"success": rc == 0, "output": (out or err or "")[-2000:]}


def count_security_upgrades(apt_simulate_output: str) -> int:
    """Cuenta paquetes de seguridad en la salida de `apt-get -s upgrade`. PURA.

    Las líneas relevantes empiezan por "Inst " e incluyen el origen de seguridad
    entre paréntesis (Debian-Security). Función separada para poder testearla.
    """
    n = 0
    for line in apt_simulate_output.splitlines():
        if line.startswith("Inst ") and re.search(r"Debian-Security|-security", line):
            n += 1
    return n
