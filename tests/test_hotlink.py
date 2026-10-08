"""Protección contra hotlinking: validación, regex (igual que el map de nginx) y vhost."""
import json
import re

import pytest
from fastapi import HTTPException

from scripts import hotlink as h
from scripts.utils import generate_nginx_config


def test_validacion():
    s, err = h.validate({"enabled": True, "types": ["images", "docs"],
                         "allow": ["https://www.Socio.es/tienda", "*.otra.com", "socio.es", ""]})
    assert not err and s["types"] == ["images", "docs"] and s["allow"] == ["socio.es", "otra.com"]
    assert h.validate({"enabled": True, "types": []})[1]
    assert h.validate({"enabled": True, "types": ["exe"]})[1]
    assert h.validate({"enabled": True, "types": ["images"], "allow": ["no es dominio"]})[1]
    assert h.validate({"enabled": False, "types": []})[1] == []      # desactivada: no hace falta tipo


def _decide(maps, referer, uri):
    """Evalúa los maps como nginx: primera entrada que casa (cadena exacta antes que regex)."""
    blocks = re.findall(r"map (\S+) \$(\S+) \{\n(.*?)\n\}", maps, re.S)
    vals = {}
    for src, var, body in blocks:
        key = src.strip('"').replace("$http_referer", referer)
        key = re.sub(r"\$(svq_ref_\w+)", lambda m: vals[m.group(1)], key).replace("$uri", uri)
        default, exact, regs = "0", {}, []
        for line in body.splitlines():
            line = line.split("#")[0].strip().rstrip(";")
            if not line:
                continue
            k, v = line.rsplit(" ", 1)
            if k == "default":
                default = v
            elif k.startswith('"~'):
                rx = k.strip('"')[1:]
                flags = re.I if rx.startswith("*") else 0
                regs.append((re.compile(rx.lstrip("*"), flags), v))
            else:
                exact[k.strip('"')] = v
        out = exact.get(key)
        if out is None:
            out = next((v for rx, v in regs if rx.search(key)), default)
        vals[var] = out
    return vals[blocks[-1][1]] == "1"


@pytest.mark.parametrize("referer,uri,blocked", [
    ("", "/img/foto.jpg", False),
    ("https://www.mi-web.com/blog", "/img/foto.jpg", False),
    ("https://tienda.mi-web.com/", "/img/foto.jpg", False),
    ("https://mi-web.es/", "/img/foto.jpg", False),                 # alias
    ("https://webajena.com/", "/img/foto.jpg", True),
    ("https://webajena.com/", "/img/FOTO.JPEG", True),
    ("https://webajena.com/", "/pagina.html", False),               # solo ficheros protegidos
    ("https://webajena.com/", "/doc.pdf", False),                   # docs no elegido
    ("https://www.google.es/", "/img/foto.jpg", False),
    ("https://images.google.co.uk/", "/img/foto.jpg", False),
    ("https://google.webajena.com/", "/img/foto.jpg", True),
    ("https://x.webajena.com/", "/img/foto.jpg", True),
    ("https://t.co/abc", "/img/foto.jpg", False),
    ("https://mi-web.com.webajena.com/", "/img/foto.jpg", True),
    ("https://blog.socio.es/", "/img/foto.jpg", False),             # permitida + subdominios
    ("android-app://com.x", "/img/foto.jpg", False),
])
def test_decision(referer, uri, blocked):
    s, _ = h.validate({"enabled": True, "types": ["images"], "allow": ["socio.es"]})
    maps = h.render_maps("mi-web.com", s, ["mi-web.es"])
    assert _decide(maps, referer, uri) is blocked


def test_sin_buscadores():
    s, _ = h.validate({"enabled": True, "types": ["images"], "allow_search": False})
    assert _decide(h.render_maps("mi-web.com", s), "https://www.google.es/", "/a.png") is True


@pytest.mark.parametrize("proxy", [False, True])
def test_vhost(proxy):
    s, _ = h.validate({"enabled": True, "types": ["images"]})
    v = generate_nginx_config("mi-web.com", "u", "8.4", ssl_enabled=True, proxy_to_apache=proxy,
                              hotlink=s, aliases=[{"name": "mi-web.es", "redirect": False}])
    assert "map $http_referer $svq_ref_mi_web_com" in v.split("upstream")[0]
    assert "mi\\-web\\.es" in v
    assert v.count("if ($svq_hotlink_mi_web_com) { return 403; }") == 2
    off = generate_nginx_config("mi-web.com", "u", "8.4", hotlink={"enabled": False})
    assert "svq_hotlink" not in off


from tests.test_user_admin_protection import db, _add  # noqa: E402,F401


def test_endpoint(db, monkeypatch):
    from api.models.models_domain import Domain
    from api.routes import domain_access as R
    import api.routes.domain_aliases as A
    c1 = _add(db, 5, "c1"); c2 = _add(db, 6, "c2")
    db.add(Domain(id=1, user_id=5, domain_name="mi-web.com", php_version="8.4", public_html="/p"))
    db.commit()
    regen = []
    monkeypatch.setattr(A, "_regenerate_or_revert", lambda d, db, rv: regen.append(d.hotlink_protection))
    with pytest.raises(HTTPException) as e:
        R.put_hotlink(1, R.HotlinkRequest(enabled=True), current_user=c2, db=db)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        R.put_hotlink(1, R.HotlinkRequest(enabled=True, types=[]), current_user=c1, db=db)
    assert e.value.status_code == 400 and not regen
    out = R.put_hotlink(1, R.HotlinkRequest(enabled=True, allow=["Socio.es"]), current_user=c1, db=db)
    assert out["hotlink"]["enabled"] and json.loads(regen[-1])["allow"] == ["socio.es"]
    assert db.get(Domain, 1).hotlink_settings["types"] == ["images"]
    R.put_hotlink(1, R.HotlinkRequest(enabled=False), current_user=c1, db=db)
    assert regen[-1] is None and db.get(Domain, 1).hotlink_settings["enabled"] is False
