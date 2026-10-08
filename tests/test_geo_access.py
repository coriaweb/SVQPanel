"""Acceso por país/IP por dominio: validación, lógica (igual que el map de nginx) y config."""
import json

import pytest

from scripts import geo_access as g
from scripts.utils import generate_nginx_config


def test_validacion_normaliza_y_rechaza():
    rules, err = g.validate_rules({"site_mode": "allow", "site_countries": ["es", "ES", "pt"],
                                   "ip_allow": [" 1.2.3.4 ", "10.0.0.5/8", "2001:db8::1/128"],
                                   "ip_block": ["5.6.7.8"]})
    assert not err
    assert rules["site_countries"] == ["ES", "PT"]
    assert rules["ip_allow"] == ["1.2.3.4", "10.0.0.0/8", "2001:db8::1"]
    for bad in ({"site_mode": "allow", "site_countries": []},
                {"site_mode": "raro"},
                {"site_countries": ["ESP"], "site_mode": "allow"},
                {"ip_block": ["no-es-ip"]},
                {"ip_allow": ["1.1.1.1"], "ip_block": ["1.1.1.1"]}):
        assert g.validate_rules(bad)[1], bad
    # Con catálogo, un código que no existe en la base se rechaza
    assert g.validate_rules({"login_countries": ["ZZ"]}, known_countries={"ES"})[1]


def test_activo():
    assert not g.is_active(g.empty_rules())
    assert not g.is_active({**g.empty_rules(), "ip_allow": ["1.2.3.4"]})
    assert g.is_active({**g.empty_rules(), "login_countries": ["ES"]})
    assert g.is_active({**g.empty_rules(), "ip_block": ["1.2.3.4"]})


@pytest.mark.parametrize("rules,ip,cc,uri,blocked", [
    ({"site_mode": "allow", "site_countries": ["ES"]}, "1.1.1.1", "US", "/", True),
    ({"site_mode": "allow", "site_countries": ["ES"]}, "1.1.1.1", "ES", "/", False),
    ({"site_mode": "allow", "site_countries": ["ES"]}, "1.1.1.1", "", "/", True),       # país desconocido
    ({"site_mode": "allow", "site_countries": ["ES"]}, "1.1.1.1", "US",
     "/.well-known/acme-challenge/x", False),                                           # Let's Encrypt
    ({"site_mode": "allow", "site_countries": ["ES"], "ip_allow": ["1.1.1.0/24"]}, "1.1.1.1", "US", "/", False),
    ({"site_mode": "block", "site_countries": ["CN"]}, "1.1.1.1", "CN", "/", True),
    ({"site_mode": "block", "site_countries": ["CN"]}, "1.1.1.1", "", "/", False),
    ({"ip_block": ["2001:db8::/32"]}, "2001:db8::5", "ES", "/", True),
    ({"login_countries": ["ES"]}, "1.1.1.1", "US", "/", False),
    ({"login_countries": ["ES"]}, "1.1.1.1", "US", "/wp-login.php", True),
    ({"login_countries": ["ES"]}, "1.1.1.1", "US", "/wp-admin", True),
    ({"login_countries": ["ES"]}, "1.1.1.1", "US", "/wp-admin/admin-ajax.php", False),
    ({"login_countries": ["ES"]}, "1.1.1.1", "ES", "/wp-login.php", False),
])
def test_would_block(rules, ip, cc, uri, blocked):
    full, err = g.validate_rules(rules)
    assert not err
    assert g.would_block(full, ip, cc, uri) is blocked


def test_conf_del_dominio():
    rules, _ = g.validate_rules({"site_mode": "allow", "site_countries": ["ES", "PT"],
                                 "login_countries": ["ES"], "ip_allow": ["1.2.3.4"], "ip_block": ["5.6.7.0/24"]})
    conf = g.render_domain_conf("mi-web.com", rules)
    assert "geo $svq_ip_mi_web_com {" in conf and "1.2.3.4 a;" in conf and "5.6.7.0/24 b;" in conf
    assert "map $svq_cc $svq_cs_mi_web_com {\n    default 1;\n    es 0;\n    pt 0;\n}" in conf
    assert "map $svq_cc $svq_cl_mi_web_com {\n    default 1;\n    es 0;\n}" in conf
    # ACME es la PRIMERA regex (en un map gana la primera que casa)
    regs = [l.split('"')[1] for l in conf.splitlines() if l.strip().startswith('"~')]
    assert regs[0] == "~^.:.:.:/\\.well-known/acme-challenge/"
    # Sin filtro de país la variable queda a 0 para todos
    off = g.render_domain_conf("x.com", g.validate_rules({"ip_block": ["1.1.1.1"]})[0])
    assert "map $svq_cc $svq_cs_x_com {\n    default 0;\n}" in off


@pytest.mark.parametrize("proxy", [False, True])
def test_vhost_comprueba_la_variable(proxy):
    v = generate_nginx_config("mi-web.com", "u", "8.4", ssl_enabled=True, proxy_to_apache=proxy,
                              access_deny_var=g.deny_var("mi-web.com"))
    # en el server http y en el https
    assert v.count("if ($svq_deny_mi_web_com) { return 403; }") == 2
    assert "svq_deny" not in generate_nginx_config("mi-web.com", "u", "8.4")


def test_parse_rules_tolerante():
    assert g.parse_rules(None) == g.empty_rules()
    assert g.parse_rules("no-json") == g.empty_rules()
    assert g.parse_rules(json.dumps({"ip_block": ["1.1.1.1"]}))["ip_block"] == ["1.1.1.1"]


def test_lista_global_solo_paises_en_uso(tmp_path, monkeypatch, db):
    from api.models.models_domain import Domain
    from tests.test_user_admin_protection import _add
    monkeypatch.setattr(g, "GEO_DIR", str(tmp_path))
    monkeypatch.setattr(g, "CC_DIR", str(tmp_path / "cc"))
    monkeypatch.setattr(g, "UNION_FILE", str(tmp_path / "union.conf"))
    monkeypatch.setattr(g, "cache_ready", lambda: True)
    (tmp_path / "cc").mkdir()
    (tmp_path / "cc" / "ES.txt").write_text("2.136.0.0/13\n2a0c:5a80::/29\n")
    (tmp_path / "cc" / "CN.txt").write_text("1.0.1.0/24\n")
    (tmp_path / "cc" / "US.txt").write_text("3.0.0.0/9\n")
    _add(db, 5, "c1")
    db.add_all([
        Domain(id=1, user_id=5, domain_name="a.com", php_version="8.4", public_html="/p",
               access_rules=json.dumps({"site_mode": "allow", "site_countries": ["ES"]})),
        Domain(id=2, user_id=5, domain_name="b.com", php_version="8.4", public_html="/p",
               access_rules=json.dumps({"login_countries": ["CN"]})),
        Domain(id=3, user_id=5, domain_name="c.com", php_version="8.4", public_html="/p",
               access_rules=json.dumps({"site_mode": "off", "site_countries": ["US"]})),   # inactivo
    ])
    db.commit()
    assert g.rebuild_union(db) == 3
    union = (tmp_path / "union.conf").read_text()
    assert "2.136.0.0/13 es;" in union and "2a0c:5a80::/29 es;" in union and "1.0.1.0/24 cn;" in union
    assert "3.0.0.0/9" not in union


from tests.test_user_admin_protection import db  # noqa: E402,F401


def test_endpoint_avisa_antes_de_dejarte_fuera(db, monkeypatch):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from api.models.models_domain import Domain
    from api.routes import domain_access as R
    import api.routes.domain_aliases as A
    from tests.test_user_admin_protection import _add
    c1 = _add(db, 5, "c1")
    db.add(Domain(id=1, user_id=5, domain_name="a.com", php_version="8.4", public_html="/p"))
    db.commit()
    monkeypatch.setattr(g, "country_names", lambda: {"ES": "España", "US": "Estados Unidos"})
    monkeypatch.setattr(g, "lookup_country", lambda ip: "US")
    regen = []
    monkeypatch.setattr(A, "_regenerate_or_revert", lambda d, db, rv: regen.append(d.access_rules))
    req = SimpleNamespace(headers={"x-real-ip": "8.8.8.8"}, client=None)

    body = R.AccessRules(site_mode="allow", site_countries=["ES"])
    with pytest.raises(HTTPException) as e:
        R.put_access(1, body, req, current_user=c1, db=db)
    assert e.value.status_code == 409 and "8.8.8.8" in e.value.detail and not regen

    # Con su IP en permitidas ya no hace falta confirmar
    R.put_access(1, R.AccessRules(site_mode="allow", site_countries=["ES"], ip_allow=["8.8.8.8"]),
                 req, current_user=c1, db=db)
    assert json.loads(regen[-1])["ip_allow"] == ["8.8.8.8"]
    # Quitarlo todo deja la columna a NULL
    R.put_access(1, R.AccessRules(), req, current_user=c1, db=db)
    assert regen[-1] is None
