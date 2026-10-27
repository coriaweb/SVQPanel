"""
/api/system/features: qué componentes opcionales se instalaron, para que la UI
oculte lo que no hay (p. ej. el menú Correo en un servidor con SVQ_MAIL=no).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _features(monkeypatch, env, webserver="nginx", cscli=None):
    import shutil
    import scripts.webserver_config as wc
    from api.routes.system import installed_features
    for k in ("MAIL_ENABLED", "ROUNDCUBE_ENABLED", "MARIADB_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(wc, "get_webserver", lambda: webserver)
    monkeypatch.setattr(shutil, "which", lambda name: cscli)
    return installed_features()


def test_servidor_sin_correo_ni_mariadb(monkeypatch):
    f = _features(monkeypatch, {"MAIL_ENABLED": "false", "MARIADB_ENABLED": "false"})
    assert f == {"mail": False, "webmail": False, "mariadb": False,
                 "apache": False, "crowdsec": False}


def test_servidor_completo(monkeypatch):
    f = _features(monkeypatch, {"MAIL_ENABLED": "true", "ROUNDCUBE_ENABLED": "true",
                                "MARIADB_ENABLED": "true"},
                  webserver="apache+nginx", cscli="/usr/bin/cscli")
    assert all(f.values())


def test_webmail_requiere_correo(monkeypatch):
    f = _features(monkeypatch, {"MAIL_ENABLED": "false", "ROUNDCUBE_ENABLED": "true"})
    assert f["webmail"] is False
