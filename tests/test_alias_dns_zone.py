"""
Zona DNS de los dominios ALIAS (dominio.es → web de dominio.com).

Antes un alias no podía tener zona: POST /dns exigía un Domain con ese nombre
(«Solo puedes crear zonas DNS para tus dominios») aunque la pestaña Alias te
mandaba a crearla. Ahora la zona de un alias pertenece al dueño de su dominio
principal, se crea sola si el principal ya tiene su DNS aquí, y se borra al
quitar el alias si nadie la ha tocado.
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
from api.models.models_domain import Domain
from api.models.models_domain_alias import DomainAlias
from api.models.models_dns import DnsZone, DnsRecord


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def db(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from api.models.database import Base
    import api.routes.dns as dns
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    for uid, name, role in [(1, "admin", "admin"), (2, "cli", "user"), (3, "otro", "user")]:
        u = User(username=name, email=f"{name}@x.com", role=role,
                 is_admin=(role == "admin"), is_active=True)
        u.id = uid
        u.set_password("Passw0rd!x")
        s.add(u)
    s.add(Domain(id=10, user_id=2, domain_name="principal.com", public_html="/x"))
    s.add(DomainAlias(domain_id=10, alias_name="principal.es", redirect=True))
    s.commit()
    # Nada de BIND/cluster ni detección de IP en los tests
    monkeypatch.setattr(dns, "_sync_zone_to_bind", lambda zone, db: None)
    monkeypatch.setattr(dns, "_get_server_ipv4", lambda db: "192.0.2.10")
    monkeypatch.setattr(dns, "_get_server_ipv6", lambda db: "")
    monkeypatch.setattr(dns, "remove_zone",
                        lambda db, zone: (db.query(DnsRecord).filter(DnsRecord.zone_id == zone.id).delete(),
                                          db.delete(zone), db.commit()))
    yield s
    s.close()


def U(db, uid):
    return db.query(User).filter(User.id == uid).first()


def test_el_cliente_puede_crear_la_zona_de_su_alias(db, monkeypatch):
    from api.routes.dns import create_zone
    from api.schemas.dns_schemas import DnsZoneCreate
    import api.routes.dns as dns

    class _NoBind:
        def create_zone(self, *a, **k):
            raise PermissionError()
    monkeypatch.setattr(dns, "DNSManager", _NoBind)
    z = run(create_zone(DnsZoneCreate(domain_name="principal.es"), current_user=U(db, 2), db=db))
    assert z.domain_name == "principal.es"


def test_otro_cliente_no_puede_crear_la_zona_del_alias_ajeno(db):
    from api.routes.dns import create_zone
    from api.schemas.dns_schemas import DnsZoneCreate
    with pytest.raises(HTTPException) as e:
        run(create_zone(DnsZoneCreate(domain_name="principal.es"), current_user=U(db, 3), db=db))
    assert e.value.status_code == 403


def test_la_zona_del_alias_sale_en_la_lista_del_cliente_y_puede_editarla(db):
    from api.routes.dns import list_zones, _user_can_edit_zone
    db.add(DnsZone(domain_name="principal.es")); db.commit()
    names = [z.domain_name for z in run(list_zones(current_user=U(db, 2), db=db))]
    assert "principal.es" in names
    z = db.query(DnsZone).filter(DnsZone.domain_name == "principal.es").first()
    assert _user_can_edit_zone(z, U(db, 2), db)
    assert not _user_can_edit_zone(z, U(db, 3), db)


def test_create_alias_zone_plantilla_web_sin_correo(db):
    from api.routes.dns import create_alias_zone
    d = db.query(Domain).filter(Domain.id == 10).first()
    res = create_alias_zone(db, d, "principal.es")
    assert res["created"] and not res["error"]
    z = db.query(DnsZone).filter(DnsZone.domain_name == "principal.es").first()
    recs = {(r.record_type, r.name) for r in db.query(DnsRecord).filter(DnsRecord.zone_id == z.id)}
    assert ("A", "@") in recs and ("CNAME", "www") in recs
    assert not any(t == "MX" for t, _ in recs)
    # Segunda vez: ya existe, no duplica
    assert create_alias_zone(db, d, "principal.es").get("exists")


def test_respeta_el_limite_de_zonas_del_plan(db):
    from api.routes.dns import create_alias_zone
    cli = U(db, 2)
    cli.dns_zones_limit = 1
    db.add(DnsZone(domain_name="principal.com")); db.commit()
    d = db.query(Domain).filter(Domain.id == 10).first()
    res = create_alias_zone(db, d, "principal.es")
    assert not res["created"] and "Límite" in res["error"]


def test_al_quitar_el_alias_se_borra_su_zona_solo_si_nadie_la_toco(db):
    from api.routes.dns import create_alias_zone, remove_alias_zone_if_untouched
    d = db.query(Domain).filter(Domain.id == 10).first()
    create_alias_zone(db, d, "principal.es")
    assert remove_alias_zone_if_untouched(db, d, "principal.es")
    assert not db.query(DnsZone).filter(DnsZone.domain_name == "principal.es").first()

    # Con un MX añadido a mano, se conserva
    create_alias_zone(db, d, "principal.es")
    z = db.query(DnsZone).filter(DnsZone.domain_name == "principal.es").first()
    db.add(DnsRecord(zone_id=z.id, record_type="MX", name="@", content="mx.externo.com.",
                     ttl=3600, priority=10)); db.commit()
    assert not remove_alias_zone_if_untouched(db, d, "principal.es")
    assert db.query(DnsZone).filter(DnsZone.domain_name == "principal.es").first()
