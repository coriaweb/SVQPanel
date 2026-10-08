"""
Acceso por país e IP de un dominio (lógica y nginx en scripts/geo_access.py).

  GET /api/domains/{id}/access   → reglas + catálogo de países + tu IP/país
  PUT /api/domains/{id}/access   → guardar reglas (regenera el vhost; revierte si no valida)
  PUT /api/domains/{id}/hotlink  → protección contra hotlinking (ver scripts/hotlink.py)

Si las reglas nuevas dejarían FUERA a quien las está guardando (su IP o su país),
se pide confirmación (409) en vez de aplicarlas: es la forma típica de quedarse
sin acceso a la propia web o al wp-admin.
"""
import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import require_auth
from api.models.database import get_db
from api.models.models_user import User
from api.utils.client_ip import client_ip
from scripts import geo_access

router = APIRouter()


class AccessRules(BaseModel):
    site_mode: str = "off"
    site_countries: List[str] = Field(default_factory=list, max_length=300)
    login_countries: List[str] = Field(default_factory=list, max_length=300)
    ip_allow: List[str] = Field(default_factory=list, max_length=geo_access.MAX_IPS + 1)
    ip_block: List[str] = Field(default_factory=list, max_length=geo_access.MAX_IPS + 1)
    confirm_self_block: bool = False


def _me(request: Request) -> dict:
    ip = client_ip(request) or ""
    return {"ip": ip, "country": geo_access.lookup_country(ip)}


def _domain(domain_id: int, db: Session, user: User):
    from api.routes.domains import _get_owned_domain
    domain = _get_owned_domain(domain_id, db, user)
    if getattr(domain, "mail_dns_only", False):
        raise HTTPException(400, detail="Este dominio no tiene web en este servidor (solo correo/DNS).")
    return domain


@router.get("/domains/{domain_id}/access")
def get_access(domain_id: int, request: Request,
               current_user: User = Depends(require_auth), db: Session = Depends(get_db)):
    domain = _domain(domain_id, db, current_user)
    names = geo_access.country_names()
    if not names:
        geo_access.warm_cache_async()      # el selector se llenará en unos segundos
    return {
        "rules": geo_access.parse_rules(domain.access_rules),
        "countries": sorted(({"cc": cc, "name": n} for cc, n in names.items()),
                            key=lambda c: c["name"]),
        "countries_ready": bool(names),
        "me": _me(request),
    }


@router.put("/domains/{domain_id}/access")
def put_access(domain_id: int, data: AccessRules, request: Request,
               current_user: User = Depends(require_auth), db: Session = Depends(get_db)):
    from api.routes.domain_aliases import _regenerate_or_revert

    domain = _domain(domain_id, db, current_user)
    names = geo_access.country_names()
    rules, errors = geo_access.validate_rules(data.model_dump(), known_countries=set(names) or None)
    if errors:
        raise HTTPException(400, detail="; ".join(errors))

    me = _me(request)
    if me["ip"] and not data.confirm_self_block:
        site = geo_access.would_block(rules, me["ip"], me["country"], "/")
        login = geo_access.would_block(rules, me["ip"], me["country"], "/wp-login.php")
        if site or login:
            where = "la web" if site else "el acceso de administración de WordPress"
            raise HTTPException(409, detail=(
                f"Con estas reglas tu conexión actual ({me['ip']}"
                f"{', ' + names.get(me['country'], me['country']) if me['country'] else ''}) "
                f"no podría entrar a {where}. Añade tu IP a las permitidas o confirma."))

    previous = domain.access_rules
    domain.access_rules = json.dumps(rules) if geo_access.is_active(rules) or rules["ip_allow"] else None
    db.commit()

    def _revert():
        domain.access_rules = previous

    # La primera vez que se usa un país hay que preparar los rangos (~30 s).
    _regenerate_or_revert(domain, db, _revert)
    return {"status": "success", "rules": geo_access.parse_rules(domain.access_rules),
            "message": "Reglas de acceso aplicadas"}


# ── Protección contra hotlinking (scripts/hotlink.py) ──────────────────────
class HotlinkRequest(BaseModel):
    enabled: bool = False
    types: List[str] = Field(default_factory=lambda: ["images"], max_length=10)
    allow_search: bool = True
    allow: List[str] = Field(default_factory=list, max_length=101)


@router.put("/domains/{domain_id}/hotlink")
def put_hotlink(domain_id: int, data: HotlinkRequest,
                current_user: User = Depends(require_auth), db: Session = Depends(get_db)):
    from api.routes.domain_aliases import _regenerate_or_revert
    from scripts import hotlink

    domain = _domain(domain_id, db, current_user)
    settings, errors = hotlink.validate(data.model_dump())
    if errors:
        raise HTTPException(400, detail="; ".join(errors))
    previous = domain.hotlink_protection
    domain.hotlink_protection = json.dumps(settings) if (settings["enabled"] or settings["allow"]) else None
    db.commit()

    def _revert():
        domain.hotlink_protection = previous

    _regenerate_or_revert(domain, db, _revert)
    return {"status": "success", "hotlink": hotlink.parse(domain.hotlink_protection),
            "message": "Protección contra hotlinking " + ("activada" if settings["enabled"] else "desactivada")}
