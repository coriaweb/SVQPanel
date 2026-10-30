"""Editar un plan llega a sus usuarios; una migración no deja al cliente topado."""
from types import SimpleNamespace

from api.utils import user_limits
from api.utils.user_limits import propagate_plan_change, raise_limits_to_usage


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *a, **k):
        return self

    def all(self):
        return self.rows


class _DB:
    def __init__(self, users):
        self.users = users

    def query(self, *a):
        return _Query(self.users)


def _plan(**kw):
    vals = dict(id=3, name="AVANZADO", disk_quota_mb=1000, traffic_quota_mb_month=2000,
                domains_limit=15, databases_limit=10, mailboxes_limit=50, dns_zones_limit=15)
    vals.update(kw)
    p = SimpleNamespace(**vals)
    p.snapshot = lambda: {f: getattr(p, f) for f in user_limits.LIMIT_FIELDS} | {
        "plan_id": p.id, "plan_name": p.name}
    return p


def _user(**kw):
    vals = dict(plan_id=3, plan_name="AVANZADO", disk_quota_mb=1000,
                traffic_quota_mb_month=2000, domains_limit=15, databases_limit=10,
                mailboxes_limit=50, dns_zones_limit=15)
    vals.update(kw)
    return SimpleNamespace(**vals)


def test_editar_plan_actualiza_a_sus_usuarios():
    plan = _plan()
    before = plan.snapshot()
    plan.databases_limit = 40
    u = _user()
    assert propagate_plan_change(_DB([u]), plan, before) == 1
    assert u.databases_limit == 40


def test_respeta_el_ajuste_manual_del_usuario():
    plan = _plan()
    before = plan.snapshot()
    plan.databases_limit = 40
    u = _user(databases_limit=25)          # un admin se lo subió a mano
    assert propagate_plan_change(_DB([u]), plan, before) == 0
    assert u.databases_limit == 25


def test_sin_cambios_no_toca_nada():
    plan = _plan()
    assert propagate_plan_change(_DB([_user()]), plan, plan.snapshot()) == 0


def test_migracion_sube_limites_superados(monkeypatch):
    monkeypatch.setattr(user_limits, "usage_counts", lambda db, uid: {
        "domains_limit": 3, "databases_limit": 14,
        "mailboxes_limit": 60, "dns_zones_limit": 3})
    u = SimpleNamespace(id=36, domains_limit=15, databases_limit=10,
                        mailboxes_limit=0, dns_zones_limit=15)
    raised = raise_limits_to_usage(None, u)
    assert raised == {"databases_limit": (10, 14)}
    assert u.databases_limit == 14
    assert u.mailboxes_limit == 0          # 0 = sin límite: no se toca
