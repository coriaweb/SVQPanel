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
    assert regs[0] == "~^.:.:.:.:/\\.well-known/acme-challenge/"
    # Sin «solo Cloudflare» no se usa $svq_from_cf (puede no existir en nginx)
    assert "$svq_from_cf" not in conf and '"$svq_ip_mi_web_com:1:' in conf
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


# ── «Solo tráfico desde Cloudflare» ─────────────────────────────────────────
def test_cloudflare_only_activa_y_valida():
    rules, err = g.validate_rules({"cloudflare_only": True})
    assert not err and rules["cloudflare_only"] is True
    assert g.is_active(rules)
    assert g.parse_rules(json.dumps({"ip_block": ["1.1.1.1"]}))["cloudflare_only"] is False


@pytest.mark.parametrize("extra,via_cf,uri,blocked", [
    ({}, True, "/", False),                                   # llega por Cloudflare
    ({}, False, "/", True),                                   # directo a la IP del servidor
    ({}, False, "/.well-known/acme-challenge/x", False),      # Let's Encrypt siempre
    ({"ip_allow": ["8.8.8.0/24"]}, False, "/", False),        # IP permitida entra directa
])
def test_cloudflare_only_would_block(extra, via_cf, uri, blocked):
    rules, _ = g.validate_rules({"cloudflare_only": True, **extra})
    assert g.would_block(rules, "8.8.8.8", "US", uri, via_cloudflare=via_cf) is blocked


def _nginx_map_eval(conf: str, key: str) -> int:
    """Evalúa el map final como nginx: primera regex que casa gana."""
    import re
    for line in conf.split("$svq_deny_")[1].splitlines()[1:]:
        m = re.match(r'\s*"~(.*)"\s+(\d);', line)
        if m and re.search(m.group(1), key):
            return int(m.group(2))
    return 0


def test_cloudflare_only_conf_y_orden_del_map():
    rules, _ = g.validate_rules({"cloudflare_only": True, "site_mode": "allow", "site_countries": ["ES"],
                                 "login_countries": ["ES"], "ip_allow": ["1.2.3.4"]})
    conf = g.render_domain_conf("w.com", rules)
    assert 'map "$svq_ip_w_com:$svq_from_cf:$svq_cs_w_com:$svq_cl_w_com:$uri"' in conf
    ev = lambda k: _nginx_map_eval(conf, k)
    assert ev("-:0:0:0:/") == 1                                   # directo: fuera
    assert ev("-:1:0:0:/") == 0                                   # por Cloudflare, país OK
    assert ev("-:1:1:0:/") == 1                                   # por Cloudflare, país no permitido
    assert ev("-:1:0:1:/wp-login.php") == 1                       # admin desde otro país
    assert ev("a:0:1:1:/wp-login.php") == 0                       # IP permitida gana a todo
    assert ev("-:0:1:1:/.well-known/acme-challenge/t") == 0       # ACME gana a todo


def test_cloudflare_ranges_no_se_recortan_si_falla_la_descarga(tmp_path, monkeypatch):
    from scripts import cloudflare_realip as cf
    monkeypatch.setattr(cf, "CONF_PATH", tmp_path / "realip.conf")
    monkeypatch.setattr(cf, "RANGES_FILE", tmp_path / "cf.conf")
    monkeypatch.setattr(cf, "GEO_CONF", tmp_path / "geo.conf")
    monkeypatch.setattr(cf, "_reload_nginx", lambda: True)
    good4 = [f"10.{i}.0.0/16" for i in range(10)]
    good6 = [f"2001:db8:{i}::/48" for i in range(5)]
    monkeypatch.setattr(cf, "_fetch", lambda url: good4 if "v4" in url else good6)
    assert cf.refresh()
    assert "10.9.0.0/16 1;" in (tmp_path / "cf.conf").read_text()
    assert "geo $realip_remote_addr $svq_from_cf" in (tmp_path / "geo.conf").read_text()
    # Descarga rota / sospechosamente corta → se mantienen los anteriores (no la lista embebida)
    monkeypatch.setattr(cf, "_fetch", lambda url: ["<html>"] if "v4" in url else ["2001:db8::/32"])
    cf.refresh()
    ranges = (tmp_path / "cf.conf").read_text()
    assert "10.9.0.0/16 1;" in ranges and "2001:db8:4::/48 1;" in ranges
    assert cf.is_cloudflare_ip("10.3.2.1") and not cf.is_cloudflare_ip("8.8.8.8")


def test_aviso_dns_sin_cloudflare(db, monkeypatch):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from api.models.models_domain import Domain
    from api.routes import domain_access as R
    import api.routes.domain_aliases as A
    from scripts import cloudflare_realip as cf
    from tests.test_user_admin_protection import _add
    c1 = _add(db, 5, "c1")
    db.add(Domain(id=1, user_id=5, domain_name="a.com", php_version="8.4", public_html="/p"))
    db.commit()
    monkeypatch.setattr(g, "country_names", lambda: {"ES": "España"})
    monkeypatch.setattr(g, "lookup_country", lambda ip: "ES")
    monkeypatch.setattr(cf, "get_ranges", lambda fetch=True: (["104.16.0.0/13"], []))
    regen = []
    monkeypatch.setattr(A, "_regenerate_or_revert", lambda d, db, rv: regen.append(d.access_rules))
    req = SimpleNamespace(headers={"x-real-ip": "8.8.8.8"}, client=None)

    # DNS apuntando al servidor (nube gris) → 409, no se aplica
    monkeypatch.setattr(g, "_public_ips", lambda name: ["185.104.188.71"])
    with pytest.raises(HTTPException) as e:
        R.put_access(1, R.AccessRules(cloudflare_only=True), req, current_user=c1, db=db)
    assert e.value.status_code == 409 and "185.104.188.71" in e.value.detail and not regen
    # Confirmado → se aplica
    R.put_access(1, R.AccessRules(cloudflare_only=True, confirm_self_block=True), req, current_user=c1, db=db)
    assert json.loads(regen[-1])["cloudflare_only"] is True
    # Ya activo: guardar otra vez no vuelve a consultar el DNS
    monkeypatch.setattr(g, "_public_ips", lambda name: pytest.fail("no debe consultar el DNS"))
    R.put_access(1, R.AccessRules(cloudflare_only=True), req, current_user=c1, db=db)
    # Con la nube naranja (IPs de Cloudflare) no hay aviso
    R.put_access(1, R.AccessRules(), req, current_user=c1, db=db)
    monkeypatch.setattr(g, "_public_ips", lambda name: ["104.18.1.1"])
    R.put_access(1, R.AccessRules(cloudflare_only=True), req, current_user=c1, db=db)
    assert json.loads(regen[-1])["cloudflare_only"] is True
