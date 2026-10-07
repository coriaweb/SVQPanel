"""PUT /users/{id} con parent_id: el admin puede cambiar el reseller de un cliente.

Antes el reseller solo se elegía al crear la cuenta: un cliente migrado o creado
como directo no se podía pasar a un reseller (ni devolverlo a cliente directo).
"""
import pytest
from fastapi import HTTPException

from tests.test_user_admin_protection import (  # noqa: F401  (fixtures)
    db, _no_os_calls, _add, _Req, _call)
from api.routes.users import update_user
from api.schemas.user_schemas import UserUpdate


def test_admin_pasa_cliente_directo_a_reseller(db):
    admin = _add(db, 1, "admin1", role="admin", is_admin=True)
    _add(db, 5, "svq1beyuri", role="reseller")
    _add(db, 9, "obradormarilo")
    r = _call(update_user(9, UserUpdate(parent_id=5), _Req(), current_user=admin, db=db))
    assert r.parent_id == 5


def test_admin_devuelve_cliente_a_directo(db):
    admin = _add(db, 1, "admin1", role="admin", is_admin=True)
    _add(db, 5, "res", role="reseller")
    c = _add(db, 9, "cliente"); c.parent_id = 5; db.commit()
    r = _call(update_user(9, UserUpdate(parent_id=None), _Req(), current_user=admin, db=db))
    assert r.parent_id is None


def test_no_enviar_parent_id_no_lo_toca(db):
    admin = _add(db, 1, "admin1", role="admin", is_admin=True)
    _add(db, 5, "res", role="reseller")
    c = _add(db, 9, "cliente"); c.parent_id = 5; db.commit()
    r = _call(update_user(9, UserUpdate(email="otro@x.com"), _Req(), current_user=admin, db=db))
    assert r.parent_id == 5


def test_el_nuevo_padre_debe_ser_reseller(db):
    admin = _add(db, 1, "admin1", role="admin", is_admin=True)
    _add(db, 8, "otrocliente")
    _add(db, 9, "cliente")
    for bad in (8, 999, 9):          # cliente normal, inexistente, él mismo
        with pytest.raises(HTTPException) as e:
            _call(update_user(9, UserUpdate(parent_id=bad), _Req(), current_user=admin, db=db))
        assert e.value.status_code == 400


def test_un_reseller_no_puede_tener_padre(db):
    admin = _add(db, 1, "admin1", role="admin", is_admin=True)
    _add(db, 5, "res", role="reseller")
    _add(db, 6, "res2", role="reseller")
    with pytest.raises(HTTPException) as e:
        _call(update_user(6, UserUpdate(parent_id=5), _Req(), current_user=admin, db=db))
    assert e.value.status_code == 400


def test_un_reseller_no_puede_mover_clientes(db):
    r1 = _add(db, 5, "res1", role="reseller")
    _add(db, 6, "res2", role="reseller")
    c = _add(db, 9, "cliente"); c.parent_id = 5; db.commit()
    with pytest.raises(HTTPException) as e:
        _call(update_user(9, UserUpdate(parent_id=6), _Req(), current_user=r1, db=db))
    assert e.value.status_code == 403
