"""
Rutas API — Firewall (nftables) — Fase 12.2

CRUD de reglas de la tabla 'inet svqpanel' + apply (regenera y recarga).
Anti-lockout: cada apply asegura que la IP del request actual esté en
whitelist antes de aplicar.
"""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from api.models.database import get_db
from api.models.models_security import FirewallRule
from api.schemas.security_schemas import (
    FirewallRuleCreate,
    FirewallRuleUpdate,
    FirewallRuleResponse,
    FirewallApplyResponse,
    FirewallStatusResponse,
)
from api.dependencies import require_admin
from api.utils import nftables_helper as nft
from api.utils.security_audit import log_audit, client_ip

router = APIRouter()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/firewall/rules", response_model=List[FirewallRuleResponse])
async def list_rules(
    only_active: bool = False,
    db:          Session = Depends(get_db),
    _:           dict   = Depends(require_admin),
):
    q = db.query(FirewallRule)
    if only_active:
        q = q.filter(FirewallRule.is_active.is_(True))
    return q.order_by(FirewallRule.priority.asc(), FirewallRule.id.asc()).all()


@router.post(
    "/firewall/rules",
    response_model=FirewallRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_rule(
    payload: FirewallRuleCreate,
    request: Request,
    db:      Session = Depends(get_db),
    user:    dict    = Depends(require_admin),
):
    rule = FirewallRule(
        action       = payload.action,
        protocol     = payload.protocol,
        port_range   = payload.port_range,
        source_ip    = payload.source_ip,
        description  = payload.description,
        is_whitelist = payload.is_whitelist,
        priority     = payload.priority,
        is_active    = payload.is_active,
        created_by   = user.id,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    log_audit(
        db, user=user, category="firewall", action="create_rule",
        target=f"#{rule.id} {rule.action} {rule.protocol}/{rule.port_range or '-'} from {rule.source_ip or 'any'}",
        after=rule, request=request,
    )

    # Aplicar inmediatamente (decisión: guardar inmediato)
    _apply_internal(db, request, user)

    return rule


@router.put("/firewall/rules/{rule_id}", response_model=FirewallRuleResponse)
async def update_rule(
    rule_id: int,
    payload: FirewallRuleUpdate,
    request: Request,
    db:      Session = Depends(get_db),
    user:    dict    = Depends(require_admin),
):
    rule = db.query(FirewallRule).filter(FirewallRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Regla no encontrada")

    before_snapshot = {c.name: getattr(rule, c.name) for c in rule.__table__.columns}

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)

    log_audit(
        db, user=user, category="firewall", action="update_rule",
        target=f"#{rule.id}", before=before_snapshot, after=rule, request=request,
    )

    _apply_internal(db, request, user)

    return rule


@router.delete("/firewall/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: int,
    request: Request,
    db:      Session = Depends(get_db),
    user:    dict    = Depends(require_admin),
):
    rule = db.query(FirewallRule).filter(FirewallRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Regla no encontrada")

    snapshot = {c.name: getattr(rule, c.name) for c in rule.__table__.columns}
    db.delete(rule)
    db.commit()

    log_audit(
        db, user=user, category="firewall", action="delete_rule",
        target=f"#{rule_id}", before=snapshot, request=request,
    )

    _apply_internal(db, request, user)


# ─────────────────────────────────────────────────────────────────────────────
# Apply (regenera svqpanel-rules.nft + nft -f)
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/firewall/apply", response_model=FirewallApplyResponse)
async def apply_rules(
    request: Request,
    db:      Session = Depends(get_db),
    user:    dict    = Depends(require_admin),
):
    return _apply_internal(db, request, user)


def _apply_internal(db: Session, request: Request, user) -> FirewallApplyResponse:
    """Lógica compartida: regenera el archivo y recarga nftables."""
    # Anti-lockout: asegurar que la IP del request está en whitelist
    auto_ip = _ensure_admin_whitelist(db, request, user)

    rules = (
        db.query(FirewallRule)
        .filter(FirewallRule.is_active.is_(True))
        .order_by(FirewallRule.priority.asc(), FirewallRule.id.asc())
        .all()
    )

    content = nft.render_rules_nft(rules)
    nft.write_rules_file(content)
    ok, message = nft.reload_nftables()

    sets_present = nft.list_table_sets() if ok else []

    log_audit(
        db, user=user, category="firewall", action="apply",
        target=f"{len(rules)} reglas",
        request=request, success=ok, error=None if ok else message,
    )

    if not ok:
        raise HTTPException(
            status_code=500,
            detail=f"Fallo recargando nftables: {message}",
        )

    return FirewallApplyResponse(
        rules_applied        = len(rules),
        sets_present         = sets_present,
        auto_whitelisted_ip  = auto_ip,
        message              = message,
    )


def _ensure_admin_whitelist(db: Session, request: Request, user) -> Optional[str]:
    """
    Si la IP que está aplicando el cambio no tiene una regla de whitelist activa,
    crea una automáticamente para evitar auto-bloqueo. Devuelve la IP si la añadió.
    """
    ip = client_ip(request)
    if not ip or ip in ("127.0.0.1", "::1"):
        return None

    exists = (
        db.query(FirewallRule)
        .filter(
            FirewallRule.is_active.is_(True),
            FirewallRule.is_whitelist.is_(True),
            FirewallRule.source_ip == ip,
        )
        .first()
    )
    if exists:
        return None

    rule = FirewallRule(
        action       = "allow",
        protocol     = "any",
        port_range   = None,
        source_ip    = ip,
        description  = f"Auto-whitelist (IP que aplicó cambio por {getattr(user, 'username', '?')})",
        is_whitelist = True,
        priority     = 1,
        is_active    = True,
        created_by   = getattr(user, "id", None),
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    log_audit(
        db, user=user, category="firewall", action="auto_whitelist",
        target=ip, after=rule, request=request,
    )
    return ip


# ─────────────────────────────────────────────────────────────────────────────
# Status
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/firewall/status", response_model=FirewallStatusResponse)
async def firewall_status(
    db: Session = Depends(get_db),
    _:  dict    = Depends(require_admin),
):
    rule_count       = db.query(FirewallRule).filter(FirewallRule.is_active.is_(True)).count()
    whitelist_count  = (
        db.query(FirewallRule)
        .filter(FirewallRule.is_active.is_(True), FirewallRule.is_whitelist.is_(True))
        .count()
    )

    # Banned: contamos las IPs realmente baneadas = baneos manuales (BannedIp en
    # la BD) + las IPs vivas de fail2ban (que NO se guardan en BannedIp), igual
    # que hace la lista /fail2ban/banned. Si solo contáramos BannedIp, el panel
    # diría 0 aunque fail2ban tuviera IPs baneadas.
    from api.models.models_security import BannedIp
    from api.utils import fail2ban_helper as f2b
    from sqlalchemy import or_
    from datetime import datetime

    banned_ips = set()
    # 1) Baneos manuales activos del panel
    manual = (
        db.query(BannedIp.ip)
        .filter(BannedIp.unbanned_at.is_(None))
        .filter(or_(BannedIp.expires_at.is_(None), BannedIp.expires_at > datetime.utcnow()))
        .all()
    )
    banned_ips.update(ip for (ip,) in manual)
    # 2) IPs vivas en los jails de fail2ban
    try:
        if f2b.is_running():
            for jail in f2b.list_jails():
                st = f2b.jail_status(jail) or {}
                banned_ips.update(st.get("banned_ips", []))
    except Exception:
        pass  # si fail2ban no responde, contamos solo los manuales
    banned_count = len(banned_ips)

    return FirewallStatusResponse(
        enabled          = nft.table_exists(),
        table_present    = nft.table_exists(),
        rule_count       = rule_count,
        whitelist_count  = whitelist_count,
        banned_count     = banned_count,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Puertos del sistema (lee el firewall REAL del kernel, no la BD)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/firewall/system-ports")
async def firewall_system_ports(_: dict = Depends(require_admin)):
    """
    Devuelve la política de la cadena input y los puertos abiertos por el
    esqueleto base del firewall (los que SVQPanel deja abiertos de serie:
    web, correo, SSH, DNS). Se lee del ruleset activo (nft), así refleja la
    realidad del kernel aunque no estén en la tabla de reglas del panel.
    """
    import subprocess
    import re

    out = ""
    try:
        r = subprocess.run(
            ["/usr/sbin/nft", "list", "chain", "inet", "svqpanel", "input"],
            capture_output=True, text=True, timeout=10,
        )
        out = r.stdout
    except Exception as e:
        return {"available": False, "error": str(e), "policy": None, "ports": []}

    # Política de la cadena (drop / accept)
    pol = re.search(r"policy\s+(\w+)", out)
    policy = pol.group(1) if pol else "unknown"

    # Servicios conocidos por puerto, para mostrar nombre amigable
    known = {
        "22": "SSH", "53": "DNS", "80": "HTTP", "443": "HTTPS",
        "25": "SMTP", "587": "Submission", "465": "SMTPS",
        "143": "IMAP", "993": "IMAPS", "110": "POP3", "995": "POP3S",
    }

    # Extraer puertos de líneas 'tcp dport ... accept' / 'udp dport ... accept'
    ports = []
    seen = set()
    for m in re.finditer(r"(tcp|udp)\s+dport\s+(\{[^}]*\}|\d+)\s+accept", out):
        proto = m.group(1)
        raw = m.group(2).strip("{} ")
        for p in (x.strip() for x in raw.split(",")):
            if not p.isdigit():
                continue
            key = f"{proto}/{p}"
            if key in seen:
                continue
            seen.add(key)
            ports.append({
                "port":    int(p),
                "proto":   proto,
                "service": known.get(p, "—"),
            })
    ports.sort(key=lambda x: x["port"])

    return {
        "available": True,
        "policy":    policy,          # 'drop' = seguro (cierra todo lo no permitido)
        "ports":     ports,
    }
