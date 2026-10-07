"""api.cli resync_builtin_templates: los dominios con plantilla reciben las reglas nuevas."""
import pytest

from tests.test_user_admin_protection import db, _no_os_calls, _add  # noqa: F401
from api.models.models_domain import Domain
from api.models.models_template import WebTemplate
from scripts.template_manager import BUILTIN_TEMPLATES

LARAVEL = next(t for t in BUILTIN_TEMPLATES if t["slug"] == "laravel")


@pytest.fixture
def env(db, monkeypatch):
    _add(db, 5, "zococori")
    row = WebTemplate(id=3, name="Laravel", slug="laravel", category="framework",
                      nginx_extra="VIEJO", is_builtin=True, is_active=True)
    d = Domain(id=1, user_id=5, domain_name="socios.zococoria.es", php_version="8.4",
               public_html="/home/zococori/web/socios.zococoria.es/public_html",
               applied_template_id=3, applied_template_name="Laravel",
               template_nginx_extra="VIEJO", docroot_subdir="public",
               php_ini_overrides='{"memory_limit": "512M"}')
    db.add_all([row, d]); db.commit()
    import api.cli as C
    import api.routes.domains as D
    monkeypatch.setattr(C, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    calls = []
    monkeypatch.setattr(D, "_regenerate_domain_vhost", lambda dom, own: calls.append(dom.template_nginx_extra))
    return C, D, d, row, calls


def test_actualiza_reglas_sin_tocar_php(env):
    C, D, d, row, calls = env
    assert C.cmd_resync_builtin_templates() == 0
    assert row.nginx_extra == LARAVEL["nginx_extra"]          # fila builtin al día
    assert d.template_nginx_extra == LARAVEL["nginx_extra"]   # dominio al día
    assert d.php_ini_overrides == '{"memory_limit": "512M"}'  # su PHP intacto
    assert calls == [LARAVEL["nginx_extra"]]
    # Idempotente: segunda pasada no regenera nada
    C.cmd_resync_builtin_templates()
    assert len(calls) == 1


def test_si_no_valida_revierte(env, monkeypatch):
    C, D, d, row, calls = env
    seq = {"n": 0}

    def regen(dom, own):
        seq["n"] += 1
        calls.append(dom.template_nginx_extra)
        if seq["n"] == 1:
            raise RuntimeError("nginx -t falló")
    monkeypatch.setattr(D, "_regenerate_domain_vhost", regen)
    C.cmd_resync_builtin_templates()
    assert d.template_nginx_extra == "VIEJO"
    assert calls == [LARAVEL["nginx_extra"], "VIEJO"]


def test_dry_run_no_toca_nada(env):
    C, D, d, row, calls = env
    C.cmd_resync_builtin_templates(dry_run=True)
    assert d.template_nginx_extra == "VIEJO" and calls == []
