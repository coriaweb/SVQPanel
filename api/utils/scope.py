"""
Alcance por rol (jerarquía admin → reseller → clientes), en UN solo sitio.

Antes cada ruta repetía su propia versión de "¿qué usuarios puede ver/gestionar
este actor?" y se desincronizaban: el reseller veía las BD y el correo de sus
clientes pero no sus dominios, zonas DNS ni crons. Toda ruta nueva debe usar
estas funciones en lugar de reimplementar el filtro.

Reglas:
  - admin:    todos los usuarios.
  - reseller: él mismo + sus clientes (users.parent_id == reseller.id).
  - user:     solo él mismo.
"""

from typing import Optional, Set

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from api.models.models_user import User


def is_admin(u: User) -> bool:
    """role e is_admin pueden desincronizarse (cli/importador): mirar ambos."""
    return bool(getattr(u, "is_admin", False)) or getattr(u, "role", None) == "admin"


def is_reseller(u: User) -> bool:
    return getattr(u, "role", None) == "reseller" and not is_admin(u)


def managed_user_ids(db: Session, actor: User) -> Optional[Set[int]]:
    """IDs de usuario cuyos recursos puede ver/gestionar `actor`.

    Devuelve None para admin (= sin filtro, todos). Para filtrar una query:
        ids = managed_user_ids(db, user)
        if ids is not None:
            q = q.filter(Modelo.user_id.in_(ids))
    """
    if is_admin(actor):
        return None
    ids = {actor.id}
    if is_reseller(actor):
        ids |= {uid for (uid,) in db.query(User.id).filter(User.parent_id == actor.id).all()}
    return ids


def can_manage_owner(db: Session, actor: User, owner_id) -> bool:
    """¿Puede `actor` gestionar los recursos del usuario `owner_id`?"""
    if owner_id is None:
        return is_admin(actor)
    ids = managed_user_ids(db, actor)
    return ids is None or owner_id in ids


def can_manage_account(actor: User, target: User) -> bool:
    """¿Puede `actor` gestionar la CUENTA `target` (editarla, suspenderla, entrar
    como ella…)? Admin: cualquiera. Reseller: solo sus clientes directos (no a
    sí mismo como "cliente": su propia cuenta la gestiona el admin). User: no."""
    if is_admin(actor):
        return True
    if is_reseller(actor):
        return target.parent_id == actor.id and not is_admin(target)
    return False


def get_managed_account_or_404(db: Session, actor: User, user_id: int) -> User:
    """Carga la cuenta `user_id` si `actor` puede gestionarla; si no, 404 (no
    403: no revelamos la existencia de cuentas ajenas)."""
    target = db.query(User).filter(User.id == user_id).first()
    if not target or not can_manage_account(actor, target):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Usuario no encontrado")
    return target
