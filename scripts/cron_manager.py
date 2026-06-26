"""
Gestión de cron jobs de clientes.

Cada usuario del panel tiene una entrada en el crontab del sistema
bajo el usuario de sistema correspondiente (/var/spool/cron/crontabs/{username}).
Este manager lee/escribe esa entrada marcando las líneas gestionadas por SVQPanel.
"""

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List

from .base import SystemManager

logger = logging.getLogger(__name__)

# Marcadores para identificar bloques gestionados por SVQPanel
_BLOCK_START = "# SVQPanel-START-{cron_id}"
_BLOCK_END   = "# SVQPanel-END-{cron_id}"


def _cron_line(minute, hour, day, month, weekday, command, cron_id, comment=""):
    parts = [
        _BLOCK_START.format(cron_id=cron_id),
    ]
    if comment:
        parts.append(f"# {comment}")
    parts.append(f"{minute} {hour} {day} {month} {weekday} {command}")
    parts.append(_BLOCK_END.format(cron_id=cron_id))
    return "\n".join(parts)


class CronManager(SystemManager):
    """Gestiona crontabs del sistema para usuarios del panel."""

    def __init__(self):
        super().__init__(require_root=True)

    # ─────────────────────────────────────────────────────────────
    # Crontab helpers
    # ─────────────────────────────────────────────────────────────

    def _read_crontab(self, username: str) -> str:
        """Lee el crontab de un usuario del sistema. Devuelve cadena vacía si no existe."""
        crontab_path = Path(f"/var/spool/cron/crontabs/{username}")
        if crontab_path.exists():
            return crontab_path.read_text()
        return ""

    def _write_crontab(self, username: str, content: str):
        """Escribe el crontab de un usuario usando `crontab -` para mantener permisos."""
        # Ruta absoluta: en contextos sin PATH completo (jobs en background,
        # importación de migración) `crontab` a secas no se encuentra (FileNotFound).
        crontab_bin = shutil.which("crontab") or "/usr/bin/crontab"
        proc = subprocess.run(
            [crontab_bin, "-u", username, "-"],
            input=content,
            text=True,
            capture_output=True,
            env={**os.environ, "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"},
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Error escribiendo crontab: {proc.stderr.strip()}")

    def _remove_cron_block(self, content: str, cron_id: int) -> str:
        """Elimina el bloque de un cron por su id de la cadena de crontab."""
        start = _BLOCK_START.format(cron_id=cron_id)
        end   = _BLOCK_END.format(cron_id=cron_id)
        lines = content.splitlines(keepends=True)
        result = []
        inside = False
        for line in lines:
            if line.strip() == start:
                inside = True
                continue
            if line.strip() == end:
                inside = False
                continue
            if not inside:
                result.append(line)
        return "".join(result)

    # ─────────────────────────────────────────────────────────────
    # API pública
    # ─────────────────────────────────────────────────────────────

    def add_cron(
        self,
        username: str,
        cron_id: int,
        minute: str,
        hour: str,
        day: str,
        month: str,
        weekday: str,
        command: str,
        comment: str = "",
    ) -> dict:
        """Añade o reemplaza un cron en el crontab del usuario del sistema."""
        # Asegurarse de que el usuario existe
        rc, out, err = self.execute_command(["id", username], check=False)
        if rc != 0:
            raise RuntimeError(f"El usuario del sistema '{username}' no existe")

        current = self._read_crontab(username)
        # Primero eliminamos el bloque si ya existía (edición)
        current = self._remove_cron_block(current, cron_id)

        new_block = _cron_line(minute, hour, day, month, weekday, command, cron_id, comment)
        if current and not current.endswith("\n"):
            current += "\n"
        current += new_block + "\n"

        self._write_crontab(username, current)
        return {"success": True, "cron_id": cron_id}

    def remove_cron(self, username: str, cron_id: int) -> dict:
        """Elimina un cron del crontab del usuario del sistema."""
        current = self._read_crontab(username)
        if not current:
            return {"success": True, "message": "Crontab vacío o no existe"}

        new_content = self._remove_cron_block(current, cron_id)
        self._write_crontab(username, new_content)
        return {"success": True, "cron_id": cron_id}

    def disable_cron(self, username: str, cron_id: int) -> dict:
        """Comenta la línea activa de un cron (la deshabilita sin eliminarla del sistema)."""
        current = self._read_crontab(username)
        start = _BLOCK_START.format(cron_id=cron_id)
        end   = _BLOCK_END.format(cron_id=cron_id)
        lines = current.splitlines(keepends=True)
        result = []
        inside = False
        for line in lines:
            if line.strip() == start:
                inside = True
                result.append(line)
                continue
            if line.strip() == end:
                inside = False
                result.append(line)
                continue
            if inside and not line.startswith("#"):
                # Comentar la línea de comando
                result.append("# " + line)
            else:
                result.append(line)
        self._write_crontab(username, "".join(result))
        return {"success": True}

    def enable_cron(self, username: str, cron_id: int) -> dict:
        """Descomenta la línea activa de un cron (lo reactiva)."""
        current = self._read_crontab(username)
        start = _BLOCK_START.format(cron_id=cron_id)
        end   = _BLOCK_END.format(cron_id=cron_id)
        lines = current.splitlines(keepends=True)
        result = []
        inside = False
        for line in lines:
            if line.strip() == start:
                inside = True
                result.append(line)
                continue
            if line.strip() == end:
                inside = False
                result.append(line)
                continue
            # Descomentar solo la línea de comando (no los comentarios de etiqueta)
            if inside and re.match(r"^# [^#]", line) and not line.startswith("# SVQPanel"):
                result.append(line[2:])  # quitar "# "
            else:
                result.append(line)
        self._write_crontab(username, "".join(result))
        return {"success": True}
