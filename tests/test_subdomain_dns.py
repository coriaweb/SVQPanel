"""
Detección y tratamiento de SUBDOMINIOS en DNS: un subdominio cuya zona padre
está en el panel debe colgarse de esa zona (registro A/AAAA), no crear zona propia.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.routes.dns import subdomain_label


def test_subdomain_label_un_nivel():
    assert subdomain_label("gestion.zococoria.es", "zococoria.es") == "gestion"


def test_subdomain_label_varios_niveles():
    assert subdomain_label("a.b.zococoria.es", "zococoria.es") == "a.b"


def test_subdomain_label_mismo_dominio_es_arroba():
    assert subdomain_label("zococoria.es", "zococoria.es") == "@"


def test_subdomain_label_sin_relacion_devuelve_fqdn():
    # Si no es sufijo, devuelve el fqdn tal cual (no debería pasar en uso real).
    assert subdomain_label("otro.com", "zococoria.es") == "otro.com"


def test_vhost_subdominio_sin_www_ni_canonical():
    """El vhost de un subdominio no lleva www. ni redirección canónica."""
    from scripts.utils import generate_nginx_config
    sub = generate_nginx_config("gestion.zococoria.es", "zococori", "8.2",
                                is_subdomain=True, canonical_domain="www")
    assert "server_name gestion.zococoria.es;" in sub
    assert "www.gestion.zococoria.es" not in sub
    assert "301" not in sub or "www." not in sub.split("server_name")[1][:200]


def test_importador_regenera_el_vhost_al_marcar_subdominio(monkeypatch):
    """La web se importa antes que el DNS, con vhost de dominio principal (www.sub
    + forzar www). Al descubrir que es subdominio hay que regenerarlo, o redirige a
    www.tienda.techocamper.com, que no existe (caso real)."""
    from types import SimpleNamespace
    from scripts import hestia_import as H
    import api.routes.domains as routes_domains

    regen = []
    monkeypatch.setattr(routes_domains, "_regenerate_domain_vhost",
                        lambda d, owner: regen.append((d.domain_name, d.is_subdomain)))
    db = SimpleNamespace(commit=lambda: None)
    d = SimpleNamespace(domain_name="tienda.techocamper.com", is_subdomain=False,
                        parent_domain=None, ipv6=None)
    H._mark_subdomain(db, d, "techocamper.com", SimpleNamespace(username="techocamper"),
                      "2001:db8::1", H.ImportReport())
    assert d.is_subdomain and d.parent_domain == "techocamper.com" and d.ipv6 == "2001:db8::1"
    assert regen == [("tienda.techocamper.com", True)]


def test_vhost_dominio_normal_si_lleva_www():
    """Un dominio normal sí incluye www. en server_name."""
    from scripts.utils import generate_nginx_config
    dom = generate_nginx_config("zococoria.es", "zococori", "8.2",
                                is_subdomain=False, canonical_domain="www")
    assert "www.zococoria.es" in dom


def test_importador_crea_la_zona_con_el_ns_real_en_el_soa(monkeypatch):
    """import_dns creaba la DnsZone sin soa_ns y caía al default de la columna,
    el placeholder ns1.svqpanel.local: el SOA de todas las zonas importadas lo
    publicaba en el cluster (beyuri.com, oct 2026)."""
    from unittest.mock import MagicMock
    from scripts import hestia_import as H
    import scripts.dns_manager as dm
    import api.routes.dns as routes_dns
    from api.models.database import load_all_models
    from api.models.models_dns import DnsZone
    load_all_models()

    monkeypatch.setattr(routes_dns, "find_parent_zone", lambda db, d: None)
    monkeypatch.setattr(dm, "get_panel_nameservers", lambda db: ("nssvq1.svqhost.red", "nssvq2.svqhost.red"))
    creada = {}
    monkeypatch.setattr(dm.DNSManager, "__init__", lambda self: None)
    monkeypatch.setattr(dm.DNSManager, "create_zone",
                        lambda self, domain, ipv4=None, ipv6=None, ns1=None, ns2=None, **k:
                        creada.update(ns1=ns1, ns2=ns2) or 2026102701)
    monkeypatch.setattr(dm.DNSManager, "reload_zone", lambda self, *a, **k: None)
    db = MagicMock()
    H.import_dns(None, {"domain": "beyuri.com", "ip": "185.104.188.41", "ttl": 14400},
                 MagicMock(), db, H.ImportReport(), approved_records=[],
                 server_ipv4="185.104.188.223")
    zonas = [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], DnsZone)]
    assert zonas and zonas[0].soa_ns == "nssvq1.svqhost.red"
    assert creada == {"ns1": "nssvq1.svqhost.red", "ns2": "nssvq2.svqhost.red"}


def test_columna_soa_ns_sin_placeholder_por_defecto():
    from api.models.models_dns import DnsZone
    assert DnsZone.__table__.c.soa_ns.default is None
