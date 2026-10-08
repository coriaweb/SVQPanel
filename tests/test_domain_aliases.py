"""Dominios alias en el vhost (nginx y Apache) y validación del alta."""
import re

import pytest
from fastapi import HTTPException

from scripts.utils import generate_nginx_config
from scripts.apache_vhost_generator import generate_apache_vhost


def _blocks(cfg):
    out, depth, cur = [], 0, None
    for line in cfg.splitlines():
        if cur is None and re.match(r"^server\s*\{", line.strip()):
            cur, depth = [], 0
        if cur is not None:
            cur.append(line)
            depth += line.count("{") - line.count("}")
            if depth == 0:
                out.append("\n".join(cur)); cur = None
    return out


@pytest.mark.parametrize("proxy", [False, True])
def test_alias_que_sirve_entra_en_server_name(proxy):
    cfg = generate_nginx_config("dominio.com", "u", "8.4", proxy_to_apache=proxy,
                                aliases=[{"name": "dominio.es", "redirect": False}])
    assert "server_name dominio.com www.dominio.com dominio.es www.dominio.es;" in cfg
    assert "Dominios alias que redirigen" not in cfg


@pytest.mark.parametrize("ssl", [False, True])
def test_alias_que_redirige_tiene_su_server_con_acme(ssl):
    cfg = generate_nginx_config("dominio.com", "u", "8.4", ssl_enabled=ssl,
                                canonical_domain="www",
                                aliases=[{"name": "dominio.es", "redirect": True},
                                         {"name": "dominio.net", "redirect": True}])
    red = [b for b in _blocks(cfg) if "dominio.es" in b]
    assert len(red) == (2 if ssl else 1)          # http (+ https)
    for b in red:
        assert "server_name dominio.es www.dominio.es dominio.net www.dominio.net;" in b
        assert "location ^~ /.well-known/acme-challenge/" in b   # el alias se puede validar
        scheme = "https" if ssl else "http"
        assert f"return 301 {scheme}://www.dominio.com$request_uri;" in b
    # El server principal no incluye los alias que redirigen
    main = [b for b in _blocks(cfg) if "server_name dominio.com" in b]
    assert main and all("dominio.es" not in b for b in main)


def test_redirige_al_canonico_sin_www():
    cfg = generate_nginx_config("dominio.com", "u", "8.4", canonical_domain="non-www",
                                aliases=[{"name": "dominio.es", "redirect": True}])
    assert "return 301 http://dominio.com$request_uri;" in cfg


def test_apache_reconoce_solo_los_que_sirven():
    v = generate_apache_vhost("dominio.com", "u", "8.4", serve_aliases=["dominio.es"])
    assert "ServerAlias www.dominio.com dominio.es www.dominio.es" in v


# ── Validación del alta ─────────────────────────────────────────────────────
from tests.test_user_admin_protection import db, _no_os_calls, _add  # noqa: E402,F401
from api.models.models_domain import Domain  # noqa: E402
from api.models.models_domain_alias import DomainAlias  # noqa: E402
from api.routes.domain_aliases import _normalize, _validate_new_alias  # noqa: E402


def test_normalizar():
    assert _normalize(" https://WWW.Dominio.ES/ruta ") == "dominio.es"


def test_validacion(db):
    _add(db, 5, "c1"); _add(db, 6, "c2")
    d1 = Domain(id=1, user_id=5, domain_name="uno.com", php_version="8.4", public_html="/p")
    d2 = Domain(id=2, user_id=6, domain_name="ajeno.com", php_version="8.4", public_html="/p")
    db.add_all([d1, d2, DomainAlias(domain_id=2, alias_name="ajeno.es")]); db.commit()
    _validate_new_alias(db, d1, "uno.es")                       # válido
    for bad, code in (("uno.com", 400), ("ajeno.com", 409), ("ajeno.es", 409),
                      ("tienda.ajeno.com", 409), ("no valido", 400)):
        with pytest.raises(HTTPException) as e:
            _validate_new_alias(db, d1, bad)
        assert e.value.status_code == code, bad
