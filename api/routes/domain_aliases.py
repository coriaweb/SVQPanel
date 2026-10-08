"""
Dominios alias: otros nombres que llevan a la web de un dominio.

  GET    /api/domains/{id}/aliases              → lista (+ ¿apunta aquí? ¿en el cert?)
  POST   /api/domains/{id}/aliases              → añadir {alias_name, redirect}
  PUT    /api/domains/{id}/aliases/{alias_id}   → cambiar el modo {redirect}
  DELETE /api/domains/{id}/aliases/{alias_id}   → quitar
  POST   /api/domains/{id}/aliases/ssl          → reintentar meter en el cert los que ya apuntan

Modo por defecto: redirigir (301) al dominio principal, lo habitual (Plesk lo
hace así): una sola URL buena para buscadores. Con redirect=False el alias sirve
la misma web con su propio nombre.

Cada cambio regenera el vhost con el camino común del panel (respeta Apache+Nginx)
y, si nginx -t falla, se revierte. El certificado del dominio se amplía con el
alias (y su www.) cuando apuntan aquí, y se reduce al quitarlo (si un alias
borrado se quedara en el certificado, la renovación fallaría entera cuando deje
de apuntar aquí).
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import require_auth
from api.models.database import get_db
from api.models.models_domain import Domain
from api.models.models_domain_alias import DomainAlias
from api.models.models_user import User
from scripts.ssl_paths import covers

logger = logging.getLogger(__name__)
router = APIRouter()


class AliasCreate(BaseModel):
    alias_name: str = Field(..., max_length=253)
    redirect: bool = True


class AliasUpdate(BaseModel):
    redirect: bool


def _owned(domain_id: int, db: Session, user: User) -> Domain:
    from api.routes.domains import _get_owned_domain
    return _get_owned_domain(domain_id, db, user)


def _normalize(name: str) -> str:
    n = (name or "").strip().lower().rstrip(".")
    for prefix in ("https://", "http://"):
        if n.startswith(prefix):
            n = n[len(prefix):]
    n = n.split("/")[0]
    if n.startswith("www."):
        n = n[4:]          # el www. se añade solo
    return n


def _validate_new_alias(db: Session, domain: Domain, name: str) -> None:
    from scripts.utils import validate_domain
    if not name or not validate_domain(name) or "." not in name:
        raise HTTPException(400, detail=f"Nombre de dominio no válido: {name or '(vacío)'}")
    if name == domain.domain_name:
        raise HTTPException(400, detail="Ese es el propio dominio.")
    if db.query(Domain).filter(Domain.domain_name.in_([name, f"www.{name}"])).first():
        raise HTTPException(409, detail=f"{name} ya existe como dominio en el panel.")
    dup = db.query(DomainAlias).filter(DomainAlias.alias_name == name).first()
    if dup:
        owner_dom = db.query(Domain).filter(Domain.id == dup.domain_id).first()
        raise HTTPException(409, detail=f"{name} ya es alias de "
                                        f"{owner_dom.domain_name if owner_dom else 'otro dominio'}.")
    # No colgar un alias bajo un dominio de OTRO cliente (shop.dominio-ajeno.com)
    labels = name.split(".")
    parents = [".".join(labels[i:]) for i in range(1, len(labels) - 1)]
    if parents:
        foreign = db.query(Domain).filter(Domain.domain_name.in_(parents),
                                          Domain.user_id != domain.user_id).first()
        if foreign:
            raise HTTPException(409, detail=f"{name} pertenece a un dominio de otro cliente.")


def _regenerate_or_revert(domain: Domain, db: Session, revert) -> None:
    """Regenera el vhost; si no valida, ejecuta revert() y vuelve a regenerar."""
    from api.routes.domains import _regenerate_domain_vhost
    owner = db.query(User).filter(User.id == domain.user_id).first()
    try:
        _regenerate_domain_vhost(domain, owner)
    except Exception as e:
        revert()
        db.commit()
        try:
            _regenerate_domain_vhost(domain, owner)
        except Exception:
            pass
        raise HTTPException(422, detail=f"La configuración no es válida y se ha revertido: {e}")


def _cert_names(domain: Domain) -> set:
    from scripts.ssl_paths import names_of
    return set(names_of(domain.domain_name))   # propio o Let's Encrypt


def _sync_cert(domain: Domain, add=None, remove=None) -> dict:
    """Ajusta el certificado del dominio. Nunca hace fallar la operación."""
    if not domain.ssl_enabled:
        return {"changed": False, "skipped": list(add or []), "error": None}
    try:
        from scripts.ssl_manager import SSLManager
        res = SSLManager().sync_cert_names(domain.domain_name, add=add, remove=remove)
        res["error"] = None
        return res
    except Exception as e:
        logger.warning(f"Alias {domain.domain_name}: certificado no actualizado: {e}")
        return {"changed": False, "skipped": list(add or []), "error": str(e)}


def _dns_hint(domain: Domain, db: Session) -> dict:
    """Registros que tiene que tener el alias para apuntar aquí."""
    ipv4 = domain.ipv4
    if not ipv4:
        try:
            from api.routes.dns import _get_server_ipv4
            ipv4 = _get_server_ipv4(db)
        except Exception:
            ipv4 = None
    return {"A": ipv4, "AAAA": domain.ipv6}


@router.get("/domains/{domain_id}/aliases")
def list_aliases(domain_id: int, current_user: User = Depends(require_auth),
                 db: Session = Depends(get_db)):
    domain = _owned(domain_id, db, current_user)
    rows = db.query(DomainAlias).filter(DomainAlias.domain_id == domain.id) \
                                .order_by(DomainAlias.alias_name).all()
    in_cert = _cert_names(domain)
    from scripts.ssl_manager import SSLManager
    sm = SSLManager()
    out = []
    for a in rows:
        out.append({
            "id": a.id, "alias_name": a.alias_name, "redirect": bool(a.redirect),
            "points_here": sm.points_here(a.alias_name),
            "in_certificate": covers(in_cert, a.alias_name),
            "created_at": a.created_at,
        })
    return {"aliases": out, "ssl_enabled": bool(domain.ssl_enabled),
            "dns": _dns_hint(domain, db)}


@router.post("/domains/{domain_id}/aliases", status_code=201)
def add_alias(domain_id: int, data: AliasCreate,
              current_user: User = Depends(require_auth), db: Session = Depends(get_db)):
    domain = _owned(domain_id, db, current_user)
    if getattr(domain, "mail_dns_only", False):
        raise HTTPException(400, detail="Este dominio no tiene web en este servidor (solo correo/DNS).")
    name = _normalize(data.alias_name)
    _validate_new_alias(db, domain, name)

    alias = DomainAlias(domain_id=domain.id, alias_name=name, redirect=bool(data.redirect))
    db.add(alias)
    db.commit()
    db.refresh(alias)

    def _revert():
        db.delete(alias)
    _regenerate_or_revert(domain, db, _revert)

    ssl = _sync_cert(domain, add=[name, f"www.{name}"])
    return {"status": "success", "alias": {"id": alias.id, "alias_name": name,
                                           "redirect": bool(alias.redirect)},
            "ssl": ssl, "dns": _dns_hint(domain, db)}


@router.put("/domains/{domain_id}/aliases/{alias_id}")
def update_alias(domain_id: int, alias_id: int, data: AliasUpdate,
                 current_user: User = Depends(require_auth), db: Session = Depends(get_db)):
    domain = _owned(domain_id, db, current_user)
    alias = db.query(DomainAlias).filter(DomainAlias.id == alias_id,
                                         DomainAlias.domain_id == domain.id).first()
    if not alias:
        raise HTTPException(404, detail="Alias no encontrado")
    prev = bool(alias.redirect)
    if prev == bool(data.redirect):
        return {"status": "success", "changed": False}
    alias.redirect = bool(data.redirect)
    db.commit()

    def _revert():
        alias.redirect = prev
    _regenerate_or_revert(domain, db, _revert)
    return {"status": "success", "changed": True}


@router.delete("/domains/{domain_id}/aliases/{alias_id}")
def delete_alias(domain_id: int, alias_id: int,
                 current_user: User = Depends(require_auth), db: Session = Depends(get_db)):
    domain = _owned(domain_id, db, current_user)
    alias = db.query(DomainAlias).filter(DomainAlias.id == alias_id,
                                         DomainAlias.domain_id == domain.id).first()
    if not alias:
        raise HTTPException(404, detail="Alias no encontrado")
    name, redirect = alias.alias_name, bool(alias.redirect)
    db.delete(alias)
    db.commit()

    def _revert():
        db.add(DomainAlias(domain_id=domain.id, alias_name=name, redirect=redirect))
    _regenerate_or_revert(domain, db, _revert)

    ssl = _sync_cert(domain, remove=[name, f"www.{name}"])
    return {"status": "success", "ssl": ssl}


@router.post("/domains/{domain_id}/aliases/ssl")
def retry_alias_ssl(domain_id: int, current_user: User = Depends(require_auth),
                    db: Session = Depends(get_db)):
    """Mete en el certificado los alias que ya apuntan aquí y aún no están."""
    domain = _owned(domain_id, db, current_user)
    if not domain.ssl_enabled:
        raise HTTPException(409, detail="El dominio no tiene SSL activo: actívalo primero en la pestaña SSL.")
    names = []
    for a in db.query(DomainAlias).filter(DomainAlias.domain_id == domain.id).all():
        names += [a.alias_name, f"www.{a.alias_name}"]
    return {"status": "success", "ssl": _sync_cert(domain, add=names)}
