"""
Un subdominio comparte la IPv6 de su dominio padre. Borrarlo quitaba esa IPv6
de la interfaz y el padre se quedaba sin IPv6 (applicaabogados.com, .71).
release_ipv6_if_unused solo la quita si no la usa ningún otro dominio.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.models.database import load_all_models
load_all_models()

from api.models.models_domain import Domain

IP = "2001:678:ff4:163b:359a:868f:36e6:d3ea"


@pytest.fixture
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from api.models.database import Base
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add(Domain(id=1, user_id=1, domain_name="padre.com", public_html="/x", ipv6=IP))
    s.add(Domain(id=2, user_id=1, domain_name="sub.padre.com", public_html="/y",
                 ipv6=IP.upper(), is_subdomain=True, parent_domain="padre.com"))
    s.add(Domain(id=3, user_id=1, domain_name="suelto.com", public_html="/z",
                 ipv6="2001:678:ff4:163b::99"))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def removed(monkeypatch):
    import scripts.ipv6_manager as m
    calls = []

    class _Fake:
        def remove_ipv6(self, iface, ip):
            calls.append(ip)
    monkeypatch.setattr(m, "IPv6Manager", _Fake)
    return calls


def test_borrar_el_subdominio_no_quita_la_ipv6_del_padre(db, removed):
    from scripts.ipv6_manager import release_ipv6_if_unused
    assert not release_ipv6_if_unused(db, "eth0", IP, exclude_domain_ids=[2])
    assert removed == []


def test_compara_direcciones_normalizadas(db):
    from scripts.ipv6_manager import ipv6_users
    assert ipv6_users(db, IP.upper() + "/64", exclude_domain_ids=[1]) == ["sub.padre.com"]


def test_si_no_la_usa_nadie_mas_se_quita(db, removed):
    from scripts.ipv6_manager import release_ipv6_if_unused
    assert release_ipv6_if_unused(db, "eth0", "2001:678:ff4:163b::99", exclude_domain_ids=[3])
    assert removed == ["2001:678:ff4:163b::99"]


def test_borrar_el_cliente_entero_si_la_quita(db, removed):
    from scripts.ipv6_manager import release_ipv6_if_unused
    assert release_ipv6_if_unused(db, "eth0", IP, exclude_domain_ids=[1, 2, 3])
    assert removed == [IP]
