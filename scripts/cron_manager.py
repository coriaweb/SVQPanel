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


# Wrapper que registra cada ejecución (estado/duración/salida). El daemon de cron
# ejecuta esta línea; el wrapper corre el comando real y encola el historial.
CRON_WRAPPER = "/usr/local/bin/svq-cron-run"
CRON_QUEUE_DIR = "/var/lib/svqpanel/cron-runs"
# Wrapper AUTÓNOMO (Python puro): NO importa nada del panel ni lee el .env (el
# cliente no tiene acceso a los secretos). Solo ejecuta el comando, mide y deja
# un .json en la cola. El panel (root) lo ingiere a BD aparte. Así el cliente
# nunca toca BD/secretos/red → cero superficie de escalada.
_WRAPPER_CONTENT = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SVQPanel - wrapper de cron. Registra estado/duracion/salida.
# Generado automaticamente. NO editar. Uso: svq-cron-run <cron_id> "<comando>"
import sys, os, json, time, uuid, subprocess
from datetime import datetime, timezone

QUEUE = "/var/lib/svqpanel/cron-runs"
CAP = 8000
cron_id = sys.argv[1] if len(sys.argv) > 1 else "0"
cmd = sys.argv[2] if len(sys.argv) > 2 else ""

started = datetime.now(timezone.utc)
t0 = time.monotonic()
try:
    p = subprocess.run(["/bin/bash", "-lc", cmd], capture_output=True, text=True,
                       timeout=3600)
    code = p.returncode
    out = (p.stdout or "") + (("\\n" + p.stderr) if p.stderr else "")
except subprocess.TimeoutExpired:
    code, out = 124, "[svq-cron] timeout (>3600s)"
except Exception as e:
    code, out = 127, "[svq-cron] error: %s" % e
dur = int((time.monotonic() - t0) * 1000)

try:
    if os.path.isdir(QUEUE):
        payload = {"cron_id": int(cron_id), "started_at": started.isoformat(),
                   "duration_ms": dur, "exit_code": code, "output": out[:CAP]}
        fn = "%s.%d.%s.json" % (cron_id, int(time.time()), uuid.uuid4().hex[:8])
        fd = os.open(os.path.join(QUEUE, fn),
                     os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f)
except Exception:
    pass

# Reemitir salida SOLO si el comando fallo (code != 0). El cron del sistema
# manda por email cualquier stdout/stderr al dueño; un job correcto que imprime
# ("Success: ..." de wp-cli, por ej.) generaria un email por ejecucion -> miles
# de correos del usuario a si mismo, frenados por el ratelimit y apilados en cola.
# La salida completa (exito incluido) YA queda en el historial del panel; aqui
# solo reemitimos los fallos, que si conviene que lleguen por correo al usuario.
if code != 0:
    sys.stdout.write(out)
sys.exit(code)
'''


def install_cron_wrapper() -> dict:
    """Instala el wrapper svq-cron-run y la cola en disco (1733: los clientes
    pueden crear ficheros pero no listar/leer/borrar ajenos). Idempotente."""
    import os
    # Cola de resultados (1733 = sticky + write-only para 'otros').
    os.makedirs(CRON_QUEUE_DIR, exist_ok=True)
    os.chmod(CRON_QUEUE_DIR, 0o1733)
    # Wrapper ejecutable por todos (solo lanza el CLI del panel).
    with open(CRON_WRAPPER, "w") as f:
        f.write(_WRAPPER_CONTENT)
    os.chmod(CRON_WRAPPER, 0o755)
    return {"success": True, "wrapper": CRON_WRAPPER, "queue": CRON_QUEUE_DIR}


def _cron_line(minute, hour, day, month, weekday, command, cron_id, comment=""):
    parts = [
        _BLOCK_START.format(cron_id=cron_id),
    ]
    if comment:
        parts.append(f"# {comment}")
    # Envolver el comando con el wrapper de historial si está instalado. El
    # comando real se pasa como UN único argumento entre comillas simples (así
    # &&, ;, | y demás no se parten a nivel del crontab). Las comillas simples
    # internas se escapan con la secuencia '\'' estándar de shell.
    if os.path.exists(CRON_WRAPPER):
        safe = command.replace("'", "'\\''")
        wrapped = f"{CRON_WRAPPER} {cron_id} '{safe}'"
    else:
        wrapped = command  # sin wrapper (compat): se ejecuta tal cual
    parts.append(f"{minute} {hour} {day} {month} {weekday} {wrapped}")
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
