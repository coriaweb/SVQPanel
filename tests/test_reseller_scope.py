"""
Jerarquía admin → reseller → clientes (api/utils/scope.py) y "entrar como cliente".

Escenario:
    1 admin
    2 reseller R      ── 3 cliente C1 (parent=R)
    4 reseller R2     ── 5 cliente C2 (parent=R2)
    6 usuario suelto U

Cubre: el alcance por rol, que el reseller gestione SOLO a sus clientes (ver,
editar sin cambiar rol, suspender), que no pueda subirse sus propios límites con
un plan, que las zonas DNS ajenas no se puedan leer, y la impersonación (token
marcado, revalidado en cada petición, bloqueado para API tokens/2FA).
"""
import os
import sys
import asyncio

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.models.database import load_all_models
load_all_models()

from api.models.models_user import User
from api.utils import scope


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from api.models.database import Base
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    for uid, name, role, parent in [
        (1, "admin", "admin", None),
        (2, "res1", "reseller", None),
        (3, "cli1", "user", 2),
        (4, "res2", "reseller", None),
        (5, "cli2", "user", 4),
        (6, "suelto", "user", None),
    ]:
        u = User(username=name, email=f"{name}@x.com", role=role,
                 is_admin=(role == "admin"), is_active=True, parent_id=parent)
        u.id = uid
        u.set_password("Passw0rd!x")
        s.add(u)
    s.commit()
    yield s
    s.close()


def U(db, uid):
    return db.query(User).filter(User.id == uid).first()


class _Req:
    def __init__(self):
        self.headers = {}
        self.client = None
        self.state = type("S", (), {})()


@pytest.fixture(autouse=True)
def _no_os(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret-reseller-scope-0123456789abcdef")
    import scripts.base
    monkeypatch.setattr(scripts.base.SystemManager, "__init__",
                        lambda self, *a, **k: None, raising=False)
    import api.routes.users as Ur
    monkeypatch.setattr(Ur.UserManager, "change_password", lambda self, *a, **k: None, raising=False)
    monkeypatch.setattr(Ur, "_apply_disk_quota", lambda *a, **k: None)
    import scripts.suspend_manager as sm
    monkeypatch.setattr(sm, "suspend_user", lambda u, suspend, db: {"suspended": suspend})


# ─────────────────────────── alcance por rol ────────────────────────────────

def test_alcance_admin_es_todo(db):
    assert scope.managed_user_ids(db, U(db, 1)) is None


def test_alcance_reseller_es_el_y_sus_clientes(db):
    assert scope.managed_user_ids(db, U(db, 2)) == {2, 3}


def test_alcance_usuario_solo_el(db):
    assert scope.managed_user_ids(db, U(db, 6)) == {6}
    assert scope.managed_user_ids(db, U(db, 3)) == {3}


def test_can_manage_owner(db):
    r = U(db, 2)
    assert scope.can_manage_owner(db, r, 3)        # su cliente
    assert scope.can_manage_owner(db, r, 2)        # él mismo
    assert not scope.can_manage_owner(db, r, 5)    # cliente de OTRO reseller
    assert not scope.can_manage_owner(db, r, 6)
    assert not scope.can_manage_owner(db, U(db, 6), 3)


def test_can_manage_account_solo_clientes_directos(db):
    r = U(db, 2)
    assert scope.can_manage_account(r, U(db, 3))
    assert not scope.can_manage_account(r, U(db, 5))
    assert not scope.can_manage_account(r, r)            # su cuenta la gestiona el admin
    assert not scope.can_manage_account(r, U(db, 1))
    assert not scope.can_manage_account(U(db, 6), U(db, 3))
    assert scope.can_manage_account(U(db, 1), U(db, 5))


def test_can_manage_user_del_modelo_incluye_a_si_mismo(db):
    """Antes un reseller NO pasaba can_manage_user consigo mismo (p.ej. su SFTP)."""
    r = U(db, 2)
    assert r.can_manage_user(r)
    assert r.can_manage_user(U(db, 3))
    assert not r.can_manage_user(U(db, 5))


# ─────────────────────────── cuentas (users.py) ─────────────────────────────

def test_reseller_ve_a_su_cliente_y_no_al_ajeno(db):
    from api.routes.users import get_user
    assert run(get_user(3, current_user=U(db, 2), db=db)).id == 3
    with pytest.raises(HTTPException) as e:
        run(get_user(5, current_user=U(db, 2), db=db))
    assert e.value.status_code == 404


def test_usuario_no_ve_otras_cuentas(db):
    from api.routes.users import get_user
    with pytest.raises(HTTPException) as e:
        run(get_user(3, current_user=U(db, 6), db=db))
    assert e.value.status_code == 404
    assert run(get_user(6, current_user=U(db, 6), db=db)).id == 6


def test_reseller_edita_a_su_cliente(db):
    from api.routes.users import update_user
    from api.schemas.user_schemas import UserUpdate
    out = run(update_user(3, UserUpdate(email="nuevo@x.com"), _Req(),
                          current_user=U(db, 2), db=db))
    assert out.email == "nuevo@x.com"


def test_reseller_no_puede_ascender_a_su_cliente(db):
    from api.routes.users import update_user
    from api.schemas.user_schemas import UserUpdate
    for rol in ("reseller", "admin"):
        with pytest.raises(HTTPException) as e:
            run(update_user(3, UserUpdate(role=rol), _Req(), current_user=U(db, 2), db=db))
        assert e.value.status_code == 403
    assert U(db, 3).role == "user"


def test_reseller_no_edita_clientes_ajenos(db):
    from api.routes.users import update_user
    from api.schemas.user_schemas import UserUpdate
    with pytest.raises(HTTPException) as e:
        run(update_user(5, UserUpdate(email="x@x.com"), _Req(), current_user=U(db, 2), db=db))
    assert e.value.status_code == 404


def test_reseller_suspende_solo_a_los_suyos(db):
    from api.routes.users import suspend_user_endpoint
    assert run(suspend_user_endpoint(3, current_user=U(db, 2), db=db))["status"] == "ok"
    with pytest.raises(HTTPException) as e:
        run(suspend_user_endpoint(5, current_user=U(db, 2), db=db))
    assert e.value.status_code == 404


# ─────────────────────────── planes ─────────────────────────────────────────

def test_reseller_no_se_asigna_un_plan_a_si_mismo(db):
    """can_manage_user ahora incluye a uno mismo: assign-plan NO debe usarlo, o
    un reseller podría subirse sus propios límites."""
    from api.routes.plans import assign_plan_to_user
    with pytest.raises(HTTPException) as e:
        run(assign_plan_to_user(2, 999, _Req(), db=db, actor=U(db, 2)))
    assert e.value.status_code == 403


# ─────────────────────────── DNS ────────────────────────────────────────────

def test_zona_dns_ajena_no_se_puede_leer(db):
    from api.models.models_domain import Domain
    from api.models.models_dns import DnsZone
    from api.routes.dns import get_zone
    d = Domain(user_id=5, domain_name="ajeno.com", public_html="/x")
    z = DnsZone(domain_name="ajeno.com")
    db.add_all([d, z]); db.commit()
    with pytest.raises(HTTPException) as e:
        run(get_zone(z.id, current_user=U(db, 2), db=db))
    assert e.value.status_code == 404
    # su reseller (R2) y el admin sí
    assert run(get_zone(z.id, current_user=U(db, 4), db=db)) is not None
    assert run(get_zone(z.id, current_user=U(db, 1), db=db)) is not None


# ─────────────────────────── entrar como cliente ────────────────────────────

def _auth(token):
    return f"Bearer {token}"


def test_impersonar_emite_token_marcado(db):
    from api.routes.auth import impersonate_user
    out = run(impersonate_user(3, _Req(), actor=U(db, 2), db=db))
    payload = User.verify_token(out["access_token"])
    assert payload["sub"] == "3" and payload["imp"] == 2
    assert out["impersonator"] == "res1"


def test_impersonar_cliente_ajeno_o_admin_falla(db):
    from api.routes.auth import impersonate_user
    for uid in (5, 1, 6):
        with pytest.raises(HTTPException) as e:
            run(impersonate_user(uid, _Req(), actor=U(db, 2), db=db))
        assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:      # admin tampoco entra en otro admin
        run(impersonate_user(1, _Req(), actor=U(db, 1), db=db))
    assert e.value.status_code == 403


def test_sesion_impersonada_se_revalida(db):
    from api.routes.auth import impersonate_user
    from api.dependencies import get_current_user
    tok = run(impersonate_user(3, _Req(), actor=U(db, 2), db=db))["access_token"]
    req = _Req()
    assert run(get_current_user(req, _auth(tok), db)).id == 3
    assert req.state.impersonator_id == 2
    # Si al reseller lo desactivan, la sesión dentro del cliente muere
    U(db, 2).is_active = False; db.commit()
    with pytest.raises(HTTPException) as e:
        run(get_current_user(_Req(), _auth(tok), db))
    assert e.value.status_code == 401


def test_sesion_impersonada_muere_si_el_cliente_cambia_de_reseller(db):
    from api.routes.auth import impersonate_user
    from api.dependencies import get_current_user
    tok = run(impersonate_user(3, _Req(), actor=U(db, 2), db=db))["access_token"]
    U(db, 3).parent_id = 4; db.commit()
    with pytest.raises(HTTPException):
        run(get_current_user(_Req(), _auth(tok), db))


def test_impersonando_no_se_crean_api_tokens_ni_2fa(db):
    from api.routes.auth import impersonate_user
    from api.dependencies import get_current_user, forbid_impersonation
    tok = run(impersonate_user(3, _Req(), actor=U(db, 2), db=db))["access_token"]
    req = _Req()
    user = run(get_current_user(req, _auth(tok), db))
    with pytest.raises(HTTPException) as e:
        run(forbid_impersonation(req, user))
    assert e.value.status_code == 403
    # Sesión normal: sí
    req2 = _Req()
    me = run(get_current_user(req2, _auth(U(db, 3).generate_token()), db))
    assert run(forbid_impersonation(req2, me)).id == 3


def test_no_se_anida_la_impersonacion(db):
    """Un admin dentro de un reseller no puede saltar a un cliente de este."""
    from api.routes.auth import impersonate_user
    from api.dependencies import get_current_user
    tok = run(impersonate_user(2, _Req(), actor=U(db, 1), db=db))["access_token"]
    req = _Req()
    res = run(get_current_user(req, _auth(tok), db))
    with pytest.raises(HTTPException) as e:
        run(impersonate_user(3, req, actor=res, db=db))
    assert e.value.status_code == 409


def test_refresh_conserva_la_marca(db):
    from api.routes.auth import impersonate_user, refresh_token
    from api.dependencies import get_current_user
    tok = run(impersonate_user(3, _Req(), actor=U(db, 2), db=db))["access_token"]
    req = _Req()
    user = run(get_current_user(req, _auth(tok), db))
    new = run(refresh_token(req, user))["access_token"]
    assert User.verify_token(new)["imp"] == 2
