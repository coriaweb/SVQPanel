"""SSL: las rutas solo actúan sobre dominios propios, y regenerar no pierde la
contraseña de la web (httpauth)."""
import pytest
from fastapi import HTTPException

from tests.test_user_admin_protection import db, _add  # noqa: F401
from api.models.models_domain import Domain


def _setup(db):
    c1 = _add(db, 5, "c1"); _add(db, 6, "c2")
    db.add_all([Domain(id=1, user_id=5, domain_name="uno.com", php_version="8.4", public_html="/p"),
                Domain(id=2, user_id=6, domain_name="ajeno.com", php_version="8.4", public_html="/p",
                       ssl_enabled=True)])
    db.commit()
    return c1


def test_rutas_ssl_rechazan_dominios_ajenos(db, monkeypatch):
    from api.routes import ssl as R
    from api.schemas.ssl_schemas import SSLToggleRequest
    c1 = _setup(db)

    class _Boom:  # si se llegara a tocar el certificado, el test lo vería
        def __init__(self, *a, **k): raise AssertionError("no debía llegar a certbot")
    monkeypatch.setattr(R, "SSLManager", _Boom)
    monkeypatch.setattr(R, "DomainManager", _Boom)

    calls = [
        lambda: R.toggle_ssl(2, SSLToggleRequest(enabled=False), current_user=c1, db=db),
        lambda: R.renew_ssl(2, current_user=c1, db=db),
        lambda: R.delete_ssl(2, current_user=c1, db=db),
    ]
    for call in calls:
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 404
    assert db.get(Domain, 2).ssl_enabled is True     # el certificado del otro sigue ahí


def test_regenerate_vhost_conserva_la_contrasena_de_la_web(db, monkeypatch, tmp_path):
    import scripts.domain_manager as DM
    import api.models.database as database
    _setup(db)
    d = db.get(Domain, 1)
    d.httpauth_enabled, d.httpauth_user = True, "cliente"
    db.commit()

    seen = {}
    monkeypatch.setattr(database, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(DM, "generate_nginx_config", lambda *a, **k: seen.update(k) or "")
    monkeypatch.setattr(DM, "get_nginx_config_path", lambda dom: str(tmp_path / dom))
    monkeypatch.setattr(DM, "reload_nginx", lambda: True)
    for fn in ("write_fastcgi_cache_zone", "remove_fastcgi_cache_zone", "remove_ratelimit_zone"):
        monkeypatch.setattr(DM, fn, lambda *a, **k: None)
    mgr = DM.DomainManager.__new__(DM.DomainManager)
    # Como lo llaman el SSL, el cambio de PHP o el CLI de los updates: sin httpauth
    mgr.regenerate_vhost("c1", "uno.com", "8.4", webserver="nginx")
    assert seen["httpauth"]["user"] == "cliente"

    d.httpauth_enabled = False
    db.commit()
    mgr.regenerate_vhost("c1", "uno.com", "8.4", webserver="nginx")
    assert seen["httpauth"] is None
