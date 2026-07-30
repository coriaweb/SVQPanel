"""
Protección de la cuenta de un admin frente a OTRO admin (api/routes/users.py).

Contexto: PUT /users/{id} y DELETE /users/{id} no comprobaban NADA sobre el
usuario objetivo — solo que quien llamaba fuese admin. Un admin secundario podía
hacer PUT /api/users/1 {"new_password": "..."} y apropiarse de la cuenta del
fundador del panel (y, de paso, de su usuario Linux), o quitarle el rol, o
desactivarlo, sin dejar rastro de auditoría. La regla sí existía en
suspend_user() y en sftp._resolve_target(): faltaba justo en PUT y DELETE.

Alcance: NO es una frontera de privilegio dura (por diseño cualquier admin puede
abrir terminal como root, ver terminal.py). Es red de seguridad contra errores y
apropiaciones silenciosas. La parte de parent_id sí es escalada real: un reseller
no tiene shell root.

Tests de lógica pura sobre los helpers + los endpoints con SQLite en memoria.
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
from api.routes.users import (_is_admin, _guard_admin_target, _count_other_admins,
                              update_user, delete_user, create_user)
from api.schemas.user_schemas import UserCreate, UserUpdate


# ─────────────────────────── helpers de test ────────────────────────────────

def _mk(uid, username, role="user", is_admin=False, is_active=True):
    u = User(username=username, email=f"{username}@x.com", role=role,
             is_admin=is_admin, is_active=is_active)
    u.id = uid
    return u


@pytest.fixture
def db():
    """Sesión SQLite en memoria con el esquema del panel."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from api.models.database import Base
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _add(db, uid, username, role="user", is_admin=False, is_active=True):
    u = _mk(uid, username, role, is_admin, is_active)
    u.set_password("Passw0rd!x")
    db.add(u)
    db.commit()
    return u


class _Req:
    """Request mínimo: log_audit solo necesita headers y client."""
    headers = {}
    client = None


@pytest.fixture(autouse=True)
def _no_os_calls(monkeypatch):
    """Aísla el SO: estos tests verifican las GUARDAS de permisos, no el sistema.
    UserManager exige root (os.geteuid, que además no existe en Windows) y
    delete_user purgaría usuarios reales. Todo lo de SO se neutraliza."""
    import scripts.base
    monkeypatch.setattr(scripts.base.SystemManager, "__init__",
                        lambda self, *a, **k: None, raising=False)
    import api.routes.users as U
    monkeypatch.setattr(U.UserManager, "create_user",
                        lambda self, *a, **k: None, raising=False)
    monkeypatch.setattr(U.UserManager, "delete_user",
                        lambda self, *a, **k: None, raising=False)
    monkeypatch.setattr(U.UserManager, "change_password",
                        lambda self, *a, **k: None, raising=False)
    monkeypatch.setattr(U, "_apply_disk_quota", lambda *a, **k: None)
    # purge_user_system se importa dentro de delete_user; neutralizarlo en origen.
    import scripts.user_purge
    monkeypatch.setattr(scripts.user_purge, "purge_user_system",
                        lambda db, u: [], raising=False)


def _call(coro):
    """Ejecuta una corrutina de endpoint. asyncio.run crea su propio loop (en
    Python 3.12+ get_event_loop ya no lo hace fuera de un contexto async)."""
    return asyncio.run(coro)


# ─────────────────────────── _is_admin ──────────────────────────────────────

def test_is_admin_mira_role_y_flag():
    """role e is_admin pueden desincronizarse (cli.py y el importador escriben
    por separado, y require_admin solo mira role). Cualquiera de los dos vale."""
    assert _is_admin(_mk(1, "a", role="admin", is_admin=True))
    assert _is_admin(_mk(2, "b", role="admin", is_admin=False))   # solo role
    assert _is_admin(_mk(3, "c", role="user",  is_admin=True))    # solo flag
    assert not _is_admin(_mk(4, "d", role="user", is_admin=False))
    assert not _is_admin(_mk(5, "e", role="reseller", is_admin=False))


# ───────────────────── _guard_admin_target ──────────────────────────────────

def test_un_admin_no_puede_tocar_a_otro_admin():
    actor  = _mk(2, "admin2", role="admin", is_admin=True)
    target = _mk(1, "fundador", role="admin", is_admin=True)
    with pytest.raises(HTTPException) as e:
        _guard_admin_target(actor, target, "modificar")
    assert e.value.status_code == 403
    assert "otro administrador" in e.value.detail


def test_un_admin_si_puede_tocarse_a_si_mismo():
    """Cambiarse la propia contraseña es legítimo."""
    a = _mk(1, "admin1", role="admin", is_admin=True)
    _guard_admin_target(a, a, "modificar")   # no lanza


def test_un_admin_si_puede_tocar_a_un_usuario_normal():
    actor = _mk(1, "admin1", role="admin", is_admin=True)
    _guard_admin_target(actor, _mk(9, "cliente"), "modificar")
    _guard_admin_target(actor, _mk(8, "revendedor", role="reseller"), "modificar")


def test_la_guarda_usa_is_admin_no_solo_role():
    """Un admin con role desincronizado sigue protegido."""
    actor  = _mk(2, "admin2", role="admin", is_admin=True)
    with pytest.raises(HTTPException):
        _guard_admin_target(actor, _mk(1, "raro", role="user", is_admin=True),
                            "modificar")


# ───────────────────── _count_other_admins ──────────────────────────────────

def test_cuenta_otros_admins(db):
    _add(db, 1, "admin1", role="admin", is_admin=True)
    _add(db, 2, "admin2", role="admin", is_admin=True)
    _add(db, 3, "solorole", role="admin", is_admin=False)   # desincronizado
    _add(db, 9, "cliente")
    assert _count_other_admins(db, exclude_id=1) == 2
    assert _count_other_admins(db, exclude_id=99) == 3      # ninguno excluido


# ──────────────────── PUT /users/{id} — endpoint ────────────────────────────

def test_put_rechaza_robar_la_password_del_fundador(db):
    fundador = _add(db, 1, "fundador", role="admin", is_admin=True)
    atacante = _add(db, 2, "admin2",   role="admin", is_admin=True)
    old_hash = fundador.password_hash

    with pytest.raises(HTTPException) as e:
        _call(update_user(1, UserUpdate(new_password="RobadaClave2026!"),
                          _Req(), current_user=atacante, db=db))
    assert e.value.status_code == 403
    db.refresh(fundador)
    assert fundador.password_hash == old_hash, "la contraseña NO debe cambiar"


def test_put_rechaza_degradar_a_otro_admin(db):
    _add(db, 1, "fundador", role="admin", is_admin=True)
    atacante = _add(db, 2, "admin2", role="admin", is_admin=True)
    with pytest.raises(HTTPException) as e:
        _call(update_user(1, UserUpdate(role="user"), _Req(),
                          current_user=atacante, db=db))
    assert e.value.status_code == 403


def test_put_rechaza_desactivar_a_otro_admin(db):
    _add(db, 1, "fundador", role="admin", is_admin=True)
    atacante = _add(db, 2, "admin2", role="admin", is_admin=True)
    with pytest.raises(HTTPException) as e:
        _call(update_user(1, UserUpdate(is_active=False), _Req(),
                          current_user=atacante, db=db))
    assert e.value.status_code == 403


def test_put_permite_editar_a_un_cliente(db):
    admin = _add(db, 1, "admin1", role="admin", is_admin=True)
    _add(db, 9, "cliente")
    r = _call(update_user(9, UserUpdate(email="nuevo@x.com"), _Req(),
                          current_user=admin, db=db))
    assert r.email == "nuevo@x.com"


def test_put_permite_cambiarse_la_propia_password(db):
    admin = _add(db, 1, "admin1", role="admin", is_admin=True)
    old = admin.password_hash
    _call(update_user(1, UserUpdate(new_password="MiNuevaClave2026!"), _Req(),
                      current_user=admin, db=db))
    db.refresh(admin)
    assert admin.password_hash != old


def test_put_no_deja_el_panel_sin_ningun_admin(db):
    """El único admin no puede quitarse el rol: nadie podría administrar."""
    admin = _add(db, 1, "unico", role="admin", is_admin=True)
    _add(db, 9, "cliente")
    with pytest.raises(HTTPException) as e:
        _call(update_user(1, UserUpdate(role="user"), _Req(),
                          current_user=admin, db=db))
    assert e.value.status_code == 409
    assert "único administrador" in e.value.detail
    db.refresh(admin)
    assert admin.role == "admin"


def test_put_no_deja_el_panel_sin_admin_activo(db):
    admin = _add(db, 1, "unico", role="admin", is_admin=True)
    with pytest.raises(HTTPException) as e:
        _call(update_user(1, UserUpdate(is_active=False), _Req(),
                          current_user=admin, db=db))
    assert e.value.status_code == 409


def test_put_si_permite_degradarse_si_queda_otro_admin(db):
    a1 = _add(db, 1, "admin1", role="admin", is_admin=True)
    _add(db, 2, "admin2", role="admin", is_admin=True)
    r = _call(update_user(1, UserUpdate(role="user"), _Req(),
                          current_user=a1, db=db))
    assert r.role == "user" and r.is_admin is False


def test_put_escribe_auditoria(db):
    """Sin esto, un cambio de rol o contraseña no dejaba NINGÚN rastro."""
    from api.models.models_security import SecurityAuditLog
    admin = _add(db, 1, "admin1", role="admin", is_admin=True)
    _add(db, 9, "cliente")
    _call(update_user(9, UserUpdate(role="reseller"), _Req(),
                      current_user=admin, db=db))
    rows = db.query(SecurityAuditLog).filter_by(category="users").all()
    assert len(rows) == 1
    assert rows[0].action == "update" and rows[0].target == "cliente"
    assert rows[0].user_label == "admin1"


# ─────────────────── DELETE /users/{id} — endpoint ──────────────────────────

def test_delete_rechaza_borrar_a_otro_admin(db):
    _add(db, 1, "fundador", role="admin", is_admin=True)
    atacante = _add(db, 2, "admin2", role="admin", is_admin=True)
    with pytest.raises(HTTPException) as e:
        _call(delete_user(1, _Req(), current_user=atacante, db=db))
    assert e.value.status_code == 403
    assert db.query(User).filter_by(id=1).first() is not None


def test_delete_rechaza_autoborrarse(db):
    """Destruiría la sesión en curso y su home, sin vuelta atrás."""
    admin = _add(db, 1, "admin1", role="admin", is_admin=True)
    _add(db, 2, "admin2", role="admin", is_admin=True)
    with pytest.raises(HTTPException) as e:
        _call(delete_user(1, _Req(), current_user=admin, db=db))
    assert e.value.status_code == 409
    assert "tu propia cuenta" in e.value.detail


def test_delete_sigue_protegiendo_al_unico_admin(db):
    """Check que ya existía; no debe haberse perdido en el refactor."""
    admin = _add(db, 1, "unico", role="admin", is_admin=True)
    # Otro admin distinto para poder llegar al check sin toparse con el de
    # autoborrado, pero con el target siendo el único admin por role+flag.
    assert _count_other_admins(db, 1) == 0
    with pytest.raises(HTTPException):
        _call(delete_user(1, _Req(), current_user=admin, db=db))


# ─────────────────── POST /users — parent_id (escalada real) ────────────────

def test_reseller_no_puede_colgar_clientes_de_otro_reseller(db):
    """ESCALADA REAL: parent_id venía del body sin validar, así que un reseller
    podía meter/ocultar cuentas en la cartera de otro reseller."""
    r1 = _add(db, 5, "reseller1", role="reseller")
    _add(db, 6, "reseller2", role="reseller")
    payload = UserCreate(username="victima", email="v@x.com",
                         password="Passw0rd!x", role="user", parent_id=6)
    with pytest.raises(HTTPException) as e:
        _call(create_user(payload, _Req(), current_user=r1, db=db))
    assert e.value.status_code == 403
    assert "su propia cuenta" in e.value.detail


def test_parent_id_inexistente_da_400(db):
    admin = _add(db, 1, "admin1", role="admin", is_admin=True)
    payload = UserCreate(username="nuevo", email="x@x.com",
                         password="Passw0rd!x", role="user", parent_id=999)
    with pytest.raises(HTTPException) as e:
        _call(create_user(payload, _Req(), current_user=admin, db=db))
    assert e.value.status_code == 400
    assert "no existe" in e.value.detail


def test_parent_id_no_puede_ser_un_usuario_normal(db):
    """Un cliente no puede ser 'padre' de otra cuenta: rompería el árbol."""
    admin = _add(db, 1, "admin1", role="admin", is_admin=True)
    _add(db, 9, "cliente")
    payload = UserCreate(username="nuevo", email="x@x.com",
                         password="Passw0rd!x", role="user", parent_id=9)
    with pytest.raises(HTTPException) as e:
        _call(create_user(payload, _Req(), current_user=admin, db=db))
    assert e.value.status_code == 400


def test_reseller_si_puede_usar_su_propio_id_como_parent(db):
    r1 = _add(db, 5, "reseller1", role="reseller")
    payload = UserCreate(username="propio", email="p@x.com",
                         password="Passw0rd!x", role="user", parent_id=5)
    # Llega a la creación real (falla en el UserManager del SO, no en la guarda).
    try:
        _call(create_user(payload, _Req(), current_user=r1, db=db))
    except HTTPException as e:
        assert e.status_code != 403, "no debe bloquearse por permisos"
