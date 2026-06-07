"""
Tests de validate_owner_assignment: política común para asignar el propietario
de un recurso de cliente (base de datos, dominio de correo, zona DNS).

Garantiza que un recurso NUNCA pertenezca a un administrador y que admin/reseller
deban elegir el cliente propietario, igual que en los dominios.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from api.utils.validators import validate_owner_assignment, OwnerAssignmentError


def _call(**kw):
    base = dict(
        actor_role="user", actor_id=5, actor_is_admin=False,
        requested_user_id=None, owner_exists=False, owner_is_admin=False,
        owner_parent_id=None, resource_label="el recurso",
    )
    base.update(kw)
    return validate_owner_assignment(**base)


def test_usuario_normal_es_su_propio_propietario():
    # Un usuario normal siempre es el dueño; se ignora requested_user_id
    assert _call(actor_role="user", actor_id=5, requested_user_id=99) == 5


def test_admin_debe_elegir_usuario():
    with pytest.raises(OwnerAssignmentError) as e:
        _call(actor_role="admin", actor_id=1, actor_is_admin=True, requested_user_id=None)
    assert e.value.status_code == 400


def test_admin_usuario_inexistente():
    with pytest.raises(OwnerAssignmentError) as e:
        _call(actor_role="admin", actor_id=1, actor_is_admin=True,
              requested_user_id=42, owner_exists=False)
    assert e.value.status_code == 404


def test_no_se_puede_asignar_a_un_admin():
    with pytest.raises(OwnerAssignmentError) as e:
        _call(actor_role="admin", actor_id=1, actor_is_admin=True,
              requested_user_id=2, owner_exists=True, owner_is_admin=True)
    assert e.value.status_code == 400


def test_admin_asigna_a_cliente_ok():
    assert _call(actor_role="admin", actor_id=1, actor_is_admin=True,
                 requested_user_id=7, owner_exists=True, owner_is_admin=False) == 7


def test_reseller_no_puede_asignar_a_cliente_ajeno():
    # owner.parent_id != reseller.id → 403
    with pytest.raises(OwnerAssignmentError) as e:
        _call(actor_role="reseller", actor_id=3, actor_is_admin=False,
              requested_user_id=9, owner_exists=True, owner_is_admin=False,
              owner_parent_id=99)
    assert e.value.status_code == 403


def test_reseller_asigna_a_su_propio_cliente_ok():
    assert _call(actor_role="reseller", actor_id=3, actor_is_admin=False,
                 requested_user_id=9, owner_exists=True, owner_is_admin=False,
                 owner_parent_id=3) == 9


def test_reseller_se_asigna_a_si_mismo_ok():
    # Un reseller asignándose a sí mismo (requested == actor) es válido
    assert _call(actor_role="reseller", actor_id=3, actor_is_admin=False,
                 requested_user_id=3, owner_exists=True, owner_is_admin=False,
                 owner_parent_id=None) == 3
