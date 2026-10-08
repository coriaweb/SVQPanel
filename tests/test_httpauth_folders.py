"""Contraseña en carpetas concretas (además de la de toda la web)."""
import json

import pytest
from fastapi import HTTPException

from scripts.utils import generate_nginx_config
from tests.test_user_admin_protection import db, _add  # noqa: F401
from api.models.models_domain import Domain


@pytest.mark.parametrize("proxy", [False, True])
def test_vhost_con_carpetas(proxy):
    v = generate_nginx_config("mi-web.com", "u", "8.4", ssl_enabled=True, proxy_to_apache=proxy,
                              httpauth_paths=[{"path": "/admin", "file": "/h/.htpasswd-a"},
                                              {"path": "/admin/sub.dir", "file": "/h/.htpasswd-b"}])
    head = v.split("upstream")[0]
    # maps a nivel http (antes del upstream); ACME primero; la carpeta más larga antes
    assert head.index('"~^/\\.well-known/acme-challenge/" off;') < head.index("/admin/sub")
    assert head.index("~^/admin/sub\\.dir(?:/|$)") < head.index('"~^/admin(?:/|$)"')
    assert '"~^/admin(?:/|$)" /h/.htpasswd-a;' in head
    # en el server http y en el https
    assert v.count("auth_basic $svq_auth_mi_web_com;") == 2
    assert v.count("auth_basic_user_file $svq_authf_mi_web_com;") == 2


def test_toda_la_web_manda_sobre_las_carpetas():
    v = generate_nginx_config("mi-web.com", "u", "8.4",
                              httpauth={"file": "/h/.htpasswd", "realm": "Zona restringida"},
                              httpauth_paths=[{"path": "/admin", "file": "/h/x"}])
    assert 'auth_basic "Zona restringida";' in v and "$svq_auth_" not in v


def _setup(db, monkeypatch, paths=None):
    import api.routes.domains as R
    c1 = _add(db, 5, "c1")
    db.add(Domain(id=1, user_id=5, domain_name="mi-web.com", php_version="8.4", public_html="/p",
                  httpauth_paths=json.dumps(paths) if paths else None))
    db.commit()
    written, regen = [], []

    class _Mgr:
        def hash_password(self, pw): return f"H({pw})"
        def write_htpasswd(self, *a): return "HSITE"
        def write_htpasswd_hash(self, *a): pass
        def remove_htpasswd(self, *a): pass
        def write_folder_htpasswds(self, user, dom, folders): written.append([f["path"] for f in folders])
        def htpasswd_path(self, *a): return "/h/.htpasswd"
    monkeypatch.setattr(R, "DomainManager", _Mgr)
    monkeypatch.setattr(R, "_regenerate_domain_vhost", lambda d, o: regen.append(d.httpauth_paths))
    return R, c1, written, regen


def test_endpoint_carpetas(db, monkeypatch):
    R, c1, written, regen = _setup(db, monkeypatch)
    body = R.HttpauthRequest(mode="folders", folders=[
        R.HttpauthFolder(path="admin/", user="jefe", password="clave1"),
        R.HttpauthFolder(path="//privado//docs", user="cli", password="clave2")])
    out = R.update_httpauth(1, body, current_user=c1, db=db)
    assert out["data"]["httpauth_folders"] == [{"path": "/admin", "user": "jefe"},
                                                {"path": "/privado/docs", "user": "cli"}]
    saved = json.loads(db.get(Domain, 1).httpauth_paths)
    assert saved[0]["hash"] == "H(clave1)" and written[-1] == ["/admin", "/privado/docs"]
    assert "hash" not in json.dumps(out)                    # la API no devuelve hashes

    # Sin contraseña nueva se conserva la de antes
    R.update_httpauth(1, R.HttpauthRequest(mode="folders", folders=[
        R.HttpauthFolder(path="/admin", user="jefe2")]), current_user=c1, db=db)
    assert json.loads(db.get(Domain, 1).httpauth_paths) == [{"path": "/admin", "user": "jefe2", "hash": "H(clave1)"}]

    # Desactivar borra las carpetas y sus ficheros
    R.update_httpauth(1, R.HttpauthRequest(mode="off"), current_user=c1, db=db)
    assert db.get(Domain, 1).httpauth_paths is None and written[-1] == []


@pytest.mark.parametrize("folders,msg", [
    ([], "al menos una carpeta"),
    ([("/", "jefe", "clave1")], "no válida"),
    ([("/a/../etc", "jefe", "clave1")], "no válida"),
    ([("/a b", "jefe", "clave1")], "no válida"),
    ([("/admin", "jefe", "clave1"), ("admin/", "otro", "clave2")], "repetida"),
    ([("/admin", "j", "clave1")], "usuario no válido"),
    ([("/admin", "jefe", None)], "indica una contraseña"),
    ([("/admin", "jefe", "abc")], "al menos 4"),
])
def test_endpoint_rechaza(db, monkeypatch, folders, msg):
    R, c1, written, regen = _setup(db, monkeypatch)
    body = R.HttpauthRequest(mode="folders", folders=[
        R.HttpauthFolder(path=p, user=u, password=pw) for p, u, pw in folders])
    with pytest.raises(HTTPException) as e:
        R.update_httpauth(1, body, current_user=c1, db=db)
    assert e.value.status_code == 400 and msg in e.value.detail
    assert not regen and db.get(Domain, 1).httpauth_paths is None


def test_endpoint_dominio_ajeno(db, monkeypatch):
    R, c1, written, regen = _setup(db, monkeypatch)
    otro = _add(db, 6, "c2")
    with pytest.raises(HTTPException) as e:
        R.update_httpauth(1, R.HttpauthRequest(mode="off"), current_user=otro, db=db)
    assert e.value.status_code == 404


def test_compatibilidad_enabled(db, monkeypatch):
    """La API antigua (enabled + user + password) sigue funcionando."""
    R, c1, written, regen = _setup(db, monkeypatch)
    R.update_httpauth(1, R.HttpauthRequest(enabled=True, user="jefe", password="clave1"),
                      current_user=c1, db=db)
    d = db.get(Domain, 1)
    assert d.httpauth_enabled and d.httpauth_user == "jefe"
