"""
Al emitir el wildcard de un dominio, sus subdominios sin HTTPS que el wildcard
cubre lo activan. Antes se quedaban sin 443 mientras la pestaña SSL decía
"Activo" (caso real: tienda.techocamper.com).
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _db(kids):
    q = SimpleNamespace(filter=lambda *a, **k: SimpleNamespace(all=lambda: kids))
    return SimpleNamespace(query=lambda *a: q)


def test_subdominios_cubiertos_sin_https(monkeypatch):
    from api.utils import ssl_jobs
    from scripts import ssl_paths
    monkeypatch.setattr(ssl_paths, "inherited_from",
                        lambda n: "techocamper.com" if n != "propio.techocamper.com" else None)
    tienda = SimpleNamespace(domain_name="tienda.techocamper.com", ssl_enabled=False)
    ya = SimpleNamespace(domain_name="blog.techocamper.com", ssl_enabled=True)
    propio = SimpleNamespace(domain_name="propio.techocamper.com", ssl_enabled=False)
    padre = SimpleNamespace(domain_name="techocamper.com", is_subdomain=False)
    assert ssl_jobs._uncovered_children(_db([tienda, ya, propio]), padre) == [tienda]


def test_un_subdominio_no_tiene_hijos():
    from api.utils import ssl_jobs
    sub = SimpleNamespace(domain_name="tienda.techocamper.com", is_subdomain=True)
    assert ssl_jobs._uncovered_children(_db([]), sub) == []


def test_estado_ssl_es_el_de_la_bd(monkeypatch):
    # Un certificado en disco (el wildcard heredado) no hace "activo" un dominio
    # cuyo vhost no escucha en 443.
    from api.routes import ssl as ssl_routes
    mgr = SimpleNamespace(get_cert_info=lambda name: {"sans": ["*.techocamper.com"]})
    d = SimpleNamespace(id=61, domain_name="tienda.techocamper.com", ssl_enabled=False, force_https=False, hsts_enabled=False, ssl_expires=None)
    assert ssl_routes._domain_ssl_response(d, mgr).ssl_enabled is False
