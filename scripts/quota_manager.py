"""
Gestión de cuotas de disco por usuario con el sistema de cuotas del kernel
Linux (setquota / repquota), al estilo cPanel.

ARQUITECTURA:
  - El kernel impide físicamente que un usuario escriba más de su límite
    (el write falla con "Disk quota exceeded"). No hay margen de fraude.
  - Requiere que el filesystem de /home (o /) esté montado con la opción
    `usrquota` en /etc/fstab y las cuotas activadas (quotaon). Esto lo prepara
    install.sh en instalaciones nuevas; en servidores existentes se puede
    activar con enable_quota_system() (puede requerir remontar).
  - La cuota se fija sobre el UID del usuario del sistema (el mismo que crea
    user_manager al dar de alta un usuario del panel).

UNIDADES:
  - setquota trabaja en bloques de 1KB. Aquí la API es en MB para encajar con
    el modelo Plan (disk_quota_mb). 1 MB = 1024 bloques de 1KB.
  - Límite 0 = ilimitado (sin cuota).

Solo opera si el sistema de cuotas está activo; si no lo está, las funciones
de consulta devuelven estado "inactive" y las de fijación lanzan un error
claro en vez de fallar en silencio.
"""

import logging
import os
import re
from typing import Optional

from scripts.base import SystemManager

logger = logging.getLogger(__name__)

# Punto de montaje sobre el que se aplican las cuotas. Normalmente /home tiene
# su propia partición; si no, se aplica sobre / (root). enable_quota_system()
# detecta cuál usar.
DEFAULT_QUOTA_MOUNT = "/home"


class QuotaManager(SystemManager):
    """Wrapper de setquota/repquota para cuotas de disco por usuario."""

    def __init__(self):
        super().__init__(require_root=True)
        self.mount = self._detect_quota_mount()

    # ── Detección de estado ───────────────────────────────────────────────

    def _detect_quota_mount(self) -> str:
        """
        Devuelve el punto de montaje sobre el que aplicar cuotas: /home si es
        su propia partición, o / en caso contrario.
        """
        try:
            # ¿/home es un punto de montaje propio?
            rc, out, _ = self.execute_command(["mountpoint", "-q", "/home"], check=False)
            if rc == 0:
                return "/home"
        except Exception:
            pass
        return "/"

    def is_quota_active(self) -> bool:
        """
        True si las cuotas de usuario están activadas en el punto de montaje.
        Se comprueba con `quotaon -p` (estado), tolerante a errores.
        """
        try:
            rc, out, err = self.execute_command(
                ["quotaon", "-p", "-u", self.mount], check=False
            )
            text = (out + err).lower()
            # "user quota on /home (...) is on"
            return "is on" in text
        except Exception as e:
            logger.warning(f"No se pudo comprobar estado de cuotas: {e}")
            return False

    def status(self) -> dict:
        """Estado general del sistema de cuotas (para la UI)."""
        active = self.is_quota_active()
        return {
            "active": active,
            "mount": self.mount,
            "message": (
                f"Cuotas de disco activas en {self.mount}"
                if active else
                f"Cuotas de disco NO activas en {self.mount}. "
                f"Los límites de disco de los planes no se aplican hasta activarlas."
            ),
        }

    # ── Fijar / quitar cuota ───────────────────────────────────────────────

    def set_quota(self, username: str, disk_quota_mb: int) -> dict:
        """
        Fija la cuota de disco de un usuario.
        disk_quota_mb = 0 → ilimitado (cuota 0 en setquota = sin límite).

        Usa soft = hard = límite (sin periodo de gracia: bloqueo directo).
        Inodos sin límite (0) — limitamos por espacio, no por nº de ficheros.
        """
        if not self.is_quota_active():
            raise RuntimeError(
                "El sistema de cuotas no está activo en este servidor. "
                "Actívalo (usrquota en fstab + quotaon) antes de fijar límites."
            )

        # bloques de 1KB: 1 MB = 1024 bloques
        blocks = int(disk_quota_mb) * 1024 if disk_quota_mb and disk_quota_mb > 0 else 0

        # setquota -u <user> <block-soft> <block-hard> <inode-soft> <inode-hard> <mount>
        rc, out, err = self.execute_command(
            ["setquota", "-u", username, str(blocks), str(blocks), "0", "0", self.mount],
            check=False,
        )
        if rc != 0:
            raise RuntimeError(f"setquota falló para {username}: {err.strip() or out.strip()}")

        logger.info(f"Cuota fijada: {username} → {disk_quota_mb} MB ({blocks} bloques) en {self.mount}")
        return {"success": True, "username": username, "disk_quota_mb": disk_quota_mb}

    def remove_quota(self, username: str) -> dict:
        """Quita la cuota de un usuario (la pone en ilimitado)."""
        return self.set_quota(username, 0)

    # ── Consultar uso ──────────────────────────────────────────────────────

    def get_usage(self, username: str) -> dict:
        """
        Devuelve el uso de disco de un usuario y su límite.
        {used_mb, limit_mb, percent, over_quota, active}
        """
        if not self.is_quota_active():
            return {
                "active": False, "used_mb": None, "limit_mb": None,
                "percent": None, "over_quota": False,
            }

        # quota -u <user> -w no sirve bien parseable; usamos repquota filtrado.
        # repquota -u <mount> imprime: user -- usedBlocks softBlock hardBlock ...
        rc, out, _ = self.execute_command(
            ["repquota", "-u", "-O", "csv", self.mount], check=False
        )
        if rc != 0:
            # Fallback al formato clásico si -O csv no está soportado
            return self._get_usage_classic(username)

        for line in out.splitlines():
            # CSV: Account,BlockStatus,FileStatus,BlockUsed,BlockSoft,BlockHard,...
            parts = line.split(",")
            if parts and parts[0] == username:
                try:
                    used_kb = int(parts[3])
                    hard_kb = int(parts[5])
                    # Sumar el correo: vive en /home/{u}/mail con owner vmail, así
                    # que la cuota de USUARIO no lo cuenta. Lo cuenta la PROJECT
                    # quota (project id = uid del usuario). Sin esto el disco no
                    # cuadra (faltaría todo el maildir).
                    used_kb += self._project_used_kb(username)
                    return self._build_usage(used_kb, hard_kb)
                except (IndexError, ValueError):
                    continue

        return {"active": True, "used_mb": 0, "limit_mb": 0, "percent": 0, "over_quota": False}

    def _project_used_kb(self, username: str) -> int:
        """KB usados por la PROJECT quota del usuario (su correo). El project id
        es el uid del usuario. 0 si no hay project quota o no aplica."""
        try:
            import pwd
            uid = pwd.getpwnam(username).pw_uid
        except (KeyError, ImportError):
            return 0
        rc, out, _ = self.execute_command(
            ["repquota", "-P", "-O", "csv", self.mount], check=False)
        if rc != 0:
            return 0
        # CSV de project: "#<projid>,BlockStatus,FileStatus,BlockUsed,..."
        target = f"#{uid}"
        for line in out.splitlines():
            parts = line.split(",")
            if parts and parts[0] == target:
                try:
                    return int(parts[3])
                except (IndexError, ValueError):
                    return 0
        return 0

    def _get_usage_classic(self, username: str) -> dict:
        """Parseo del formato clásico de repquota (sin CSV)."""
        rc, out, _ = self.execute_command(["repquota", "-u", self.mount], check=False)
        if rc != 0:
            return {"active": True, "used_mb": 0, "limit_mb": 0, "percent": 0, "over_quota": False}
        for line in out.splitlines():
            # ej: "juan      --  123456  500000  500000          12     0     0"
            m = re.match(rf"^{re.escape(username)}\s+[-+]{{2}}\s+(\d+)\s+(\d+)\s+(\d+)", line)
            if m:
                used_kb = int(m.group(1))
                hard_kb = int(m.group(3))
                return self._build_usage(used_kb, hard_kb)
        return {"active": True, "used_mb": 0, "limit_mb": 0, "percent": 0, "over_quota": False}

    def _build_usage(self, used_kb: int, hard_kb: int) -> dict:
        used_mb = round(used_kb / 1024, 1)
        limit_mb = round(hard_kb / 1024) if hard_kb > 0 else 0  # 0 = ilimitado
        percent = round((used_kb / hard_kb) * 100, 1) if hard_kb > 0 else 0
        return {
            "active": True,
            "used_mb": used_mb,
            "limit_mb": limit_mb,
            "percent": percent,
            "over_quota": hard_kb > 0 and used_kb >= hard_kb,
        }

    def get_all_usage(self) -> dict:
        """Uso de todos los usuarios con cuota (para vistas de admin)."""
        if not self.is_quota_active():
            return {}
        rc, out, _ = self.execute_command(
            ["repquota", "-u", "-O", "csv", self.mount], check=False
        )
        result = {}
        if rc != 0:
            return result
        for line in out.splitlines():
            parts = line.split(",")
            if len(parts) >= 6 and parts[0] and not parts[0].startswith("#") and parts[0] != "Account":
                try:
                    result[parts[0]] = self._build_usage(int(parts[3]), int(parts[5]))
                except (ValueError, IndexError):
                    continue
        return result
