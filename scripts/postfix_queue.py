"""
Gestor de la cola de correo de Postfix (solo admin).

Envuelve los comandos estándar de Postfix:
  - postqueue -p / -j   → listar la cola
  - postqueue -f        → reintentar (flush) toda la cola
  - postsuper -r ID|ALL → re-encolar para reintento
  - postsuper -d ID|ALL → borrar de la cola
  - postcat -q ID       → ver el contenido de un mensaje

No mantiene estado: cada llamada consulta Postfix en vivo. Todas las operaciones
exigen root (las hace el panel vía systemd) y se exponen SOLO a admin en la API.
"""

import json
import re
import shutil
import subprocess
from typing import List, Dict, Tuple

# Un queue ID de Postfix es hex/base36: letras y dígitos (y a veces el sufijo
# nuevo con guion). Lo validamos estrictamente para no pasar nada raro a postsuper.
_QID_RE = re.compile(r"^[A-Za-z0-9]+$")

_SYSTEM_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def _run(cmd: List[str], timeout: int = 20) -> Tuple[int, str, str]:
    import os
    env = os.environ.copy()
    env["PATH"] = _SYSTEM_PATH
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    return p.returncode, p.stdout, p.stderr


def postfix_available() -> bool:
    """¿Está Postfix instalado en el sistema?"""
    return shutil.which("postqueue") is not None


def _valid_qid(qid: str) -> bool:
    return bool(qid) and bool(_QID_RE.match(qid)) and len(qid) <= 32


def list_queue() -> Dict:
    """
    Devuelve la cola de correo parseada. Usa `postqueue -j` (JSON, una línea por
    mensaje) si está disponible (Postfix 3.1+); si no, cae a parsear `postqueue -p`.
    """
    if not postfix_available():
        return {"available": False, "messages": [], "count": 0}

    # Preferir JSON (-j): robusto y estructurado.
    rc, out, err = _run(["postqueue", "-j"])
    if rc == 0:
        msgs = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                j = json.loads(line)
            except ValueError:
                continue
            recipients = j.get("recipients", [])
            rcpts = [r.get("address", "") for r in recipients]
            reasons = [r.get("delay_reason", "") for r in recipients if r.get("delay_reason")]
            msgs.append({
                "id":         j.get("queue_id", ""),
                "queue":      j.get("queue_name", ""),     # incoming/active/deferred/hold
                "sender":     j.get("sender", ""),
                "recipients": rcpts,
                "size":       j.get("message_size", 0),
                "arrival":    j.get("arrival_time", 0),
                "reason":     reasons[0] if reasons else "",
            })
        return {"available": True, "messages": msgs, "count": len(msgs)}

    # Fallback: parsear el formato clásico de `postqueue -p`.
    rc, out, err = _run(["postqueue", "-p"])
    if rc != 0:
        return {"available": True, "messages": [], "count": 0, "error": (err or "").strip()}
    return {"available": True, **_parse_mailq(out)}


def _parse_mailq(text: str) -> Dict:
    """Parser del formato clásico de mailq/postqueue -p (best-effort)."""
    msgs = []
    if "Mail queue is empty" in text:
        return {"messages": [], "count": 0}
    block = {}
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.startswith("-Queue ID-") or line.startswith("--"):
            continue
        # Línea de cabecera de mensaje: "ID    SIZE  DATE  SENDER"
        m = re.match(r"^([A-Za-z0-9]+)([*!]?)\s+(\d+)\s+(.+?)\s+(\S+@\S+|\S+)$", line)
        if m:
            if block:
                msgs.append(block)
            block = {
                "id": m.group(1),
                "size": int(m.group(3)),
                "arrival_str": m.group(4),
                "sender": m.group(5),
                "recipients": [],
                "reason": "",
            }
        elif block:
            s = line.strip()
            if s.startswith("(") and s.endswith(")"):
                block["reason"] = s.strip("()")
            elif "@" in s:
                block["recipients"].append(s)
    if block:
        msgs.append(block)
    return {"messages": msgs, "count": len(msgs)}


def flush_queue() -> Tuple[bool, str]:
    """Reintenta la entrega de TODA la cola (postqueue -f)."""
    if not postfix_available():
        return False, "Postfix no está instalado"
    rc, out, err = _run(["postqueue", "-f"])
    if rc != 0:
        return False, (err or out or "").strip()
    return True, "Cola reencolada para reintento de entrega"


def delete_message(qid: str) -> Tuple[bool, str]:
    """Borra un mensaje de la cola (postsuper -d ID)."""
    if not postfix_available():
        return False, "Postfix no está instalado"
    if qid != "ALL" and not _valid_qid(qid):
        return False, "Queue ID no válido"
    rc, out, err = _run(["postsuper", "-d", qid])
    if rc != 0:
        return False, (err or out or "").strip()
    return True, ("Cola vaciada" if qid == "ALL" else f"Mensaje {qid} borrado")


def requeue_message(qid: str) -> Tuple[bool, str]:
    """Re-encola un mensaje para reintento inmediato (postsuper -r ID)."""
    if not postfix_available():
        return False, "Postfix no está instalado"
    if qid != "ALL" and not _valid_qid(qid):
        return False, "Queue ID no válido"
    rc, out, err = _run(["postsuper", "-r", qid])
    if rc != 0:
        return False, (err or out or "").strip()
    return True, ("Toda la cola re-encolada" if qid == "ALL" else f"Mensaje {qid} re-encolado")


def message_content(qid: str, max_bytes: int = 100_000) -> Tuple[bool, str]:
    """Devuelve el contenido (cabeceras + cuerpo) de un mensaje (postcat -q ID)."""
    if not postfix_available():
        return False, "Postfix no está instalado"
    if not _valid_qid(qid):
        return False, "Queue ID no válido"
    rc, out, err = _run(["postcat", "-q", qid])
    if rc != 0:
        return False, (err or out or "").strip()
    if len(out) > max_bytes:
        out = out[:max_bytes] + "\n\n[... truncado ...]"
    return True, out
