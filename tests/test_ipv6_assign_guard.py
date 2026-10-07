"""IPv6 de dominios: solo del rango del servidor, libre y del propio usuario.

Antes POST/DELETE /domains/{id}/ipv6 no comprobaban la propiedad (IDOR) y
aceptaban cualquier IPv6, que acababa en la interfaz del servidor.
"""
import pytest
from fastapi import HTTPException

from tests.test_user_admin_protection import db, _no_os_calls, _add, _call  # noqa: F401
from api.models.models_domain import Domain
from api.models.models_settings import Settings
from api.routes.ipv6 import _validate_assignable, assign_ipv6, delete_ipv6
from api.schemas.ipv6_schemas import IPv6Assign


@pytest.fixture
def env(db, monkeypatch):
    db.add(Settings(id=1, ipv6_enabled=True, ipv6_range="2001:678:ff4:4778::/64"))
    _add(db, 5, "cliente1")
    _add(db, 6, "cliente2")
    d1 = Domain(id=1, user_id=5, domain_name="uno.com", php_version="8.4", public_html="/p1")
    d2 = Domain(id=2, user_id=6, domain_name="dos.com", php_version="8.4", public_html="/p2",
                ipv6="2001:678:ff4:4778::20")
    db.add_all([d1, d2]); db.commit()
    import api.routes.dns as DNS
    monkeypatch.setattr(DNS, "_get_server_ipv6", lambda db: "2001:678:ff4:4778::1")
    return d1, d2


def test_rango_principal_y_ocupada(db, env):
    d1, _ = env
    _validate_assignable(db, d1, "2001:678:ff4:4778::30")            # válida
    for bad, code in (("2001:db8::30", 400),                         # fuera del rango
                      ("2001:678:ff4:4778::", 400),                  # dirección de red
                      ("2001:678:ff4:4778::1", 400),                 # la principal
                      ("2001:678:ff4:4778::20", 409)):               # de otro dominio
        with pytest.raises(HTTPException) as e:
            _validate_assignable(db, d1, bad)
        assert e.value.status_code == code, bad


def test_un_cliente_no_toca_la_ipv6_de_otro(db, env):
    _, d2 = env
    from api.models.models_user import User
    cliente1 = db.query(User).filter(User.id == 5).first()
    with pytest.raises(HTTPException) as e:
        _call(assign_ipv6(2, IPv6Assign(ipv6_address="2001:678:ff4:4778::40"),
                          current_user=cliente1, db=db))
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        _call(delete_ipv6(2, current_user=cliente1, db=db))
    assert e.value.status_code == 404
    db.refresh(d2)
    assert d2.ipv6 == "2001:678:ff4:4778::20"


def test_sin_rango_configurado(db, env):
    d1, _ = env
    db.query(Settings).filter(Settings.id == 1).first().ipv6_range = None
    db.commit()
    with pytest.raises(HTTPException) as e:
        _validate_assignable(db, d1, "2001:678:ff4:4778::30")
    assert e.value.status_code == 409
