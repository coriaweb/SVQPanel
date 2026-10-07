"""TemplateManager.apply_template: usa el camino común del panel y revierte si falla.

Bug (obradormarilo.com, oct 2026): en un servidor Apache+Nginx la plantilla
escribía un vhost de PHP directo con fastcgi_cache sobre una zona declarada como
proxy_cache → nginx -t fallaba y el vhost roto se quedaba en disco.
"""
import pytest

from tests.test_user_admin_protection import db, _no_os_calls, _add  # noqa: F401
from api.models.models_domain import Domain
from api.models.models_template import WebTemplate


@pytest.fixture
def setup(db, monkeypatch):
    owner = _add(db, 5, "obradormarilo")
    d = Domain(id=1, user_id=5, domain_name="obradormarilo.com", php_version="8.5",
               public_html="/home/obradormarilo/web/obradormarilo.com/public_html",
               fastcgi_cache_enabled=False, fastcgi_cache_ttl_minutes=60)
    t = WebTemplate(id=7, name="WordPress", slug="wordpress", category="cms",
                    nginx_extra="location = /xmlrpc.php { deny all; }",
                    fastcgi_cache_default=True, php_ini_overrides=None, is_active=True)
    db.add_all([d, t]); db.commit()
    import api.routes.domains as D
    calls = []
    monkeypatch.setattr(D, "_regenerate_domain_vhost",
                        lambda dom, own: calls.append((dom.applied_template_id,
                                                       dom.fastcgi_cache_enabled)))
    from scripts.template_manager import TemplateManager
    return TemplateManager(), d, t, owner, calls, D


def test_aplica_con_el_regenerador_comun(setup):
    tm, d, t, owner, calls, _ = setup
    r = tm.apply_template(d, t, owner.username)
    assert r["status"] == "success"
    assert calls == [(7, True)]          # regenera ya con los campos de la plantilla
    assert d.applied_template_name == "WordPress"
    assert d.template_nginx_extra.startswith("location = /xmlrpc.php")
    assert d.fastcgi_cache_enabled is True


def test_si_la_validacion_falla_revierte_todo(setup, monkeypatch):
    tm, d, t, owner, calls, D = setup
    state = {"n": 0}

    def regen(dom, own):
        state["n"] += 1
        calls.append((dom.applied_template_id, dom.fastcgi_cache_enabled))
        if state["n"] == 1:
            raise RuntimeError('nginx: [emerg] the shared memory zone "SVQ_x" is already declared')
    monkeypatch.setattr(D, "_regenerate_domain_vhost", regen)

    r = tm.apply_template(d, t, owner.username)
    assert r["status"] == "failed"
    assert "se ha restaurado" in r["error"] and "shared memory zone" in r["error"]
    # Segunda regeneración = restauración con los valores anteriores
    assert calls == [(7, True), (None, False)]
    assert d.applied_template_id is None and d.applied_template_name is None
    assert d.template_nginx_extra is None and d.fastcgi_cache_enabled is False


def test_enable_cache_explicito_manda(setup):
    tm, d, t, owner, calls, _ = setup
    tm.apply_template(d, t, owner.username, enable_cache=False)
    assert d.fastcgi_cache_enabled is False
