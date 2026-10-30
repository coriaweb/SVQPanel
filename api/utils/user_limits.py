"""
Sincronización de los límites de un usuario con su plan y con lo que ya usa.

Asignar un plan COPIA sus límites al usuario (snapshot). Sin esto, editar el plan
después no llegaba a los usuarios que ya lo tenían: el plan subía a 40 BDs y el
cliente seguía topado en 10. Y una migración puede dejar al cliente por ENCIMA de
su límite (el importador no lo comprueba), con lo que ya no podía crear nada.
"""

from sqlalchemy.orm import Session

from api.models.models_user import User

# Campos que el plan copia al usuario (sin plan_id/plan_name).
LIMIT_FIELDS = (
    "disk_quota_mb",
    "traffic_quota_mb_month",
    "domains_limit",
    "databases_limit",
    "mailboxes_limit",
    "dns_zones_limit",
)


def propagate_plan_change(db: Session, plan, before: dict) -> int:
    """Lleva los límites editados del plan a los usuarios que lo tienen asignado.

    `before` es plan.snapshot() de ANTES de editar. Solo se actualiza un campo si
    el usuario seguía teniendo el valor viejo del plan: si un admin le ajustó ese
    límite a mano, se respeta. No hace commit. Devuelve cuántos usuarios cambiaron.
    """
    after = plan.snapshot()
    changed = [f for f in LIMIT_FIELDS if before.get(f) != after.get(f)]
    renamed = before.get("plan_name") != after.get("plan_name")
    if not changed and not renamed:
        return 0

    touched = 0
    for u in db.query(User).filter(User.plan_id == plan.id).all():
        dirty = False
        for f in changed:
            if getattr(u, f, None) == before.get(f):
                setattr(u, f, after[f])
                dirty = True
        if renamed:
            u.plan_name = plan.name
            dirty = True
        touched += dirty
    return touched


def usage_counts(db: Session, user_id: int) -> dict:
    """Recursos que tiene el usuario, contados igual que al comprobar cada límite."""
    from api.models.models_client_db import ClientDatabase
    from api.models.models_dns import DnsZone
    from api.models.models_domain import Domain
    from api.models.models_mail import MailDomain, Mailbox

    return {
        "domains_limit": db.query(Domain).filter(Domain.user_id == user_id).count(),
        "databases_limit": db.query(ClientDatabase)
                             .filter(ClientDatabase.user_id == user_id).count(),
        "mailboxes_limit": db.query(Mailbox)
                             .join(MailDomain, Mailbox.mail_domain_id == MailDomain.id)
                             .filter(MailDomain.user_id == user_id).count(),
        "dns_zones_limit": db.query(DnsZone)
                             .join(Domain, DnsZone.domain_name == Domain.domain_name)
                             .filter(Domain.user_id == user_id).count(),
    }


def raise_limits_to_usage(db: Session, user: User) -> dict:
    """Si el usuario ya tiene más recursos que su límite (p. ej. tras migrarlo),
    sube ese límite a lo que tiene. 0 = sin límite: no se toca. Nunca baja nada.
    No hace commit. Devuelve {campo: (antes, después)} de lo que cambió."""
    raised = {}
    for field, used in usage_counts(db, user.id).items():
        limit = getattr(user, field, 0) or 0
        if limit > 0 and used > limit:
            setattr(user, field, used)
            raised[field] = (limit, used)
    return raised
