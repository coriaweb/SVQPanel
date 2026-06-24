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
from api.models.models_domain import Domain
from api.models.models_user import User
from api.schemas.security_schemas import AuditLogResponse, ActiveConnection
from api.dependencies import require_admin, require_auth

router = APIRouter()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Aislamiento PHP por dominio (open_basedir / pool FPM dedicado)
# ─────────────────────────────────────────────────────────────────────────────
def _domains_for_audit(db: Session) -> List[dict]:
    """Lista de dominios con su owner y config PHP, para auditar/reparar."""
    rows = (
        db.query(Domain, User.username)
        .join(User, Domain.user_id == User.id)
        .all()
    )
    out = []
    for dom, username in rows:
        out.append({
            "domain": dom.domain_name,
            "owner": username,
            "php_version": dom.php_version or "8.2",
            "overrides": dom.php_ini_overrides,            # JSON string o None
            "relaxed": bool(dom.php_hardening_relaxed),
        })
    return out


@router.get("/security/php-isolation")
async def audit_php_isolation(
    db: Session = Depends(get_db),
    _:  dict    = Depends(require_admin),
):
    """
    Audita el aislamiento PHP de todos los dominios: verifica que cada uno
    tiene pool FPM dedicado con open_basedir, disable_functions y tmp aislado.
    Detecta dominios que caerían al pool global (sin open_basedir).
    """
    from scripts.security_audit import audit_domains
    try:
        return audit_domains(_domains_for_audit(db))
    except Exception as e:
        logger.error(f"Error auditando aislamiento PHP: {e}")
        return {"total": 0, "secure": 0, "insecure": 0, "all_ok": True, "domains": [], "error": str(e)}


@router.post("/security/php-isolation/repair")
async def repair_php_isolation(
    db: Session = Depends(get_db),
    _:  dict    = Depends(require_admin),
):
    """
    Repara los dominios sin aislamiento correcto reescribiendo su pool FPM
    con el bloque de seguridad completo. Respeta overrides php.ini y el flag
    de hardening relajado de cada dominio.
    """
    from scripts.security_audit import repair_domains
    try:
        return repair_domains(_domains_for_audit(db))
    except Exception as e:
        logger.error(f"Error reparando aislamiento PHP: {e}")
        return {"attempted": 0, "repaired": 0, "failed": 0, "details": [], "error": str(e)}


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


# ─────────────────────────────────────────────────────────────────────────────
# Bad Bots Blocker
# ─────────────────────────────────────────────────────────────────────────────

from pydantic import BaseModel

class BadBotsUpdate(BaseModel):
    enabled_ids: List[str] = []
    custom_patterns: List[str] = []


@router.get("/security/bad-bots")
async def get_bad_bots(current_user=Depends(require_auth)):
    """Lista el catálogo de bots con su estado activo/inactivo y los patrones custom."""
    from scripts.bad_bots_manager import get_known_bots, get_custom_bots
    return {
        "known_bots": get_known_bots(),
        "custom_patterns": get_custom_bots(),
    }


@router.put("/security/bad-bots")
async def update_bad_bots(data: BadBotsUpdate, current_user=Depends(require_admin)):
    """Actualiza el bloqueo de user-agents y recarga nginx."""
    from scripts.bad_bots_manager import update_bad_bots
    try:
        result = update_bad_bots(data.enabled_ids, data.custom_patterns)
        return {"status": "ok", **result}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


# ── Actualizaciones automáticas de seguridad del SO ──────────────────────────
@router.get("/security/auto-updates")
async def get_auto_updates(_: dict = Depends(require_admin)):
    """Estado de las actualizaciones automáticas de seguridad (unattended-upgrades)."""
    try:
        from scripts.auto_updates import AutoUpdatesManager
        return AutoUpdatesManager().status()
    except PermissionError:
        return {"available": False, "reason": "requiere root"}
    except Exception as e:
        return {"available": False, "reason": str(e)}


@router.post("/security/auto-updates")
async def set_auto_updates(data: dict, _: dict = Depends(require_admin)):
    """Activa o desactiva las actualizaciones automáticas de seguridad.
    Body: {"enabled": bool}."""
    from scripts.auto_updates import AutoUpdatesManager
    mgr = AutoUpdatesManager()
    if data.get("enabled"):
        return mgr.install()
    return mgr.disable()


@router.post("/security/auto-updates/run")
async def run_auto_updates(_: dict = Depends(require_admin)):
    """Aplica ahora las actualizaciones de seguridad pendientes (bajo demanda)."""
    from scripts.auto_updates import AutoUpdatesManager
    return AutoUpdatesManager().run_now()
