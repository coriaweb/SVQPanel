"""
Rutas API — Monitor de seguridad (audit log + conexiones activas) — Fase 12.3
"""

import logging
import re
import subprocess
from typing import List, Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.models.database import get_db
from api.models.models_security import SecurityAuditLog
from api.schemas.security_schemas import AuditLogResponse, ActiveConnection
from api.dependencies import require_admin

router = APIRouter()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Audit log
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/security/audit", response_model=List[AuditLogResponse])
async def list_audit(
    category: Optional[str] = None,
    limit:    int = 100,
    db:       Session = Depends(get_db),
    _:        dict    = Depends(require_admin),
):
    q = db.query(SecurityAuditLog)
    if category:
        q = q.filter(SecurityAuditLog.category == category)
    return q.order_by(SecurityAuditLog.created_at.desc()).limit(min(limit, 500)).all()


# ─────────────────────────────────────────────────────────────────────────────
# Conexiones activas (ss -tunap)
# ─────────────────────────────────────────────────────────────────────────────
_SS_LINE_RE = re.compile(
    r"^(?P<state>\S+)\s+\d+\s+\d+\s+"
    r"(?P<local>\S+):(?P<lport>\d+|\*)\s+"
    r"(?P<remote>\S+):(?P<rport>\d+|\*)"
    r"(?:\s+users:\(\(\"(?P<proc>[^\"]+)\"[^)]*\)\))?"
)


@router.get("/security/connections", response_model=List[ActiveConnection])
async def list_connections(
    listening: bool = False,
    _:         dict = Depends(require_admin),
):
    """
    Lista conexiones TCP/UDP activas usando 'ss'. Si listening=True, solo
    sockets en estado LISTEN (puertos abiertos).
    """
    # PATH absoluto: el systemd service de svqpanel solo tiene
    # /opt/svqpanel/venv/bin en PATH, así que 'ss' (en /usr/bin) no se
    # encontraría → FileNotFoundError → [] silencioso.
    args = ["/usr/bin/ss", "-tunap", "-H"]   # -H sin cabecera
    if listening:
        args.append("-l")
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=8)
    except FileNotFoundError:
        return []
    except subprocess.TimeoutExpired:
        return []

    if r.returncode != 0:
        return []

    out: List[ActiveConnection] = []
    for raw in r.stdout.splitlines():
        # ss -tunap -H formato:
        #   proto state recv_q send_q local:port remote:port [users:((...))]
        # Ejemplo:
        #   tcp   ESTAB  0  0  127.0.0.1:8001  127.0.0.1:54321  users:(("python",pid=123,fd=8))
        parts = raw.split(None, 6)
        if len(parts) < 6:
            continue
        proto  = parts[0].lower()
        state  = parts[1]
        local  = parts[4]
        remote = parts[5]
        process = None
        if len(parts) > 6 and "users:" in parts[6]:
            m = re.search(r'\("([^"]+)"', parts[6])
            if m:
                process = m.group(1)

        l_addr, l_port = _split_addr_port(local)
        r_addr, r_port = _split_addr_port(remote)
        # Solo descartamos si el local_port es inválido. En LISTEN, remote
        # suele ser '0.0.0.0:*' o '[::]:*' → port se queda como None y lo
        # normalizamos a 0 para que se vea en la UI.
        if l_port is None:
            continue
        if r_port is None:
            r_port = 0

        out.append(ActiveConnection(
            protocol    = proto,
            local_addr  = l_addr,
            local_port  = l_port,
            remote_addr = r_addr,
            remote_port = r_port,
            state       = state,
            process     = process,
        ))
    return out


def _split_addr_port(s: str):
    """Separa 'host:port' o '[::1]:80' en (host, port_int|None)."""
    # IPv6 puede estar entre corchetes
    if s.startswith("["):
        m = re.match(r"\[([^\]]+)\]:(\S+)", s)
        if not m:
            return s, None
        addr, port = m.group(1), m.group(2)
    else:
        if ":" not in s:
            return s, None
        addr, _, port = s.rpartition(":")
    try:
        return addr, int(port)
    except (ValueError, TypeError):
        return addr, None
