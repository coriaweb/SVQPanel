"""Suspensión que sobrevive a las regeneraciones, y borrado de cliente sin restos."""
import os

from scripts import domain_suspend_manager as S


# ── Suspensión ─────────────────────────────────────────────────────────────
def test_vhost_de_un_suspendido_sigue_suspendido(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "SUSPENDED_DIR", str(tmp_path / "susp"))
    path = str(tmp_path / "dominio.com")
    S.write_nginx_vhost(path, "server { proxy_pass http://127.0.0.1:8181; }", "dominio.com", suspended=True)
    assert S.is_suspended_config(open(path).read())                 # se sirve la página de suspendido
    assert "proxy_pass" in open(path + ".active").read()            # y el bueno, al día, aparte
    S.write_nginx_vhost(path, "server { nuevo }", "dominio.com", suspended=False)
    assert open(path).read() == "server { nuevo }"


def test_regenerate_vhost_respeta_la_suspension(db, monkeypatch, tmp_path):
    import scripts.domain_manager as DM
    import api.models.database as database
    from api.models.models_domain import Domain
    from tests.test_user_admin_protection import _add
    _add(db, 5, "c1")
    db.add(Domain(id=1, user_id=5, domain_name="uno.com", php_version="8.4", public_html="/p", is_suspended=True))
    db.commit()
    monkeypatch.setattr(S, "SUSPENDED_DIR", str(tmp_path / "susp"))
    monkeypatch.setattr(database, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(DM, "generate_nginx_config", lambda *a, **k: "server { la web normal }")
    monkeypatch.setattr(DM, "get_nginx_config_path", lambda dom: str(tmp_path / dom))
    monkeypatch.setattr(DM, "reload_nginx", lambda: True)
    for fn in ("write_fastcgi_cache_zone", "remove_fastcgi_cache_zone", "remove_ratelimit_zone"):
        monkeypatch.setattr(DM, fn, lambda *a, **k: None)
    mgr = DM.DomainManager.__new__(DM.DomainManager)
    # Lo que hacían los updates, el SSL o el cambio de PHP: regenerar sin saber nada
    mgr.regenerate_vhost("c1", "uno.com", "8.4", webserver="nginx")
    assert S.is_suspended_config(open(tmp_path / "uno.com").read())
    assert "la web normal" in open(str(tmp_path / "uno.com") + ".active").read()


# ── Borrado de cliente ─────────────────────────────────────────────────────
def test_quita_solo_esa_zona_del_bind_local(tmp_path, monkeypatch):
    import scripts.dns_manager as DNS
    from scripts import user_purge as P
    zones = tmp_path / "zones"; zones.mkdir()
    (zones / "db.borrado.es").write_text("zona")
    (zones / "db.otro.com").write_text("zona")
    conf = tmp_path / "named.conf.zones"
    conf.write_text(
        'zone "otro.com" IN {\n    type master;\n    file "x";\n    allow-transfer { none; };\n};\n\n'
        'zone "borrado.es" IN {\n    type master;\n    file "y";\n    allow-transfer { none; };\n    allow-update { none; };\n};\n\n'
        'zone "z.org" IN {\n    type master;\n};\n')
    monkeypatch.setattr(DNS, "ZONES_DIR", str(zones))
    assert P.remove_local_zone("borrado.es", conf=str(conf), reload=False)
    text = conf.read_text()
    assert 'zone "borrado.es"' not in text and 'zone "otro.com"' in text and 'zone "z.org"' in text
    assert not (zones / "db.borrado.es").exists() and (zones / "db.otro.com").exists()


def test_borrar_correo_quita_vhost_mail_certificados_y_sni(db, monkeypatch):
    from types import SimpleNamespace
    from scripts import user_purge as P
    import scripts.mail_tls_manager as T
    import api.routes.mail as M
    done = []
    for mod, name in (("scripts.webmail_manager", "WebmailManager"), ("scripts.mail_manager", "MailManager"),
                      ("scripts.dkim_manager", "DkimManager"), ("scripts.rspamd_manager", "RspamdManager")):
        monkeypatch.setattr(__import__(mod, fromlist=[name]), name,
                            lambda *a, **k: SimpleNamespace(destroy=lambda *x: None, delete_mail_domain=lambda *x: None,
                                                            remove_key=lambda *x: None, remove_domain=lambda *x: None))
    monkeypatch.setattr(T, "MailTLSManager", lambda: SimpleNamespace(_remove_nginx_vhost=lambda d: done.append(("vhost", d))))
    monkeypatch.setattr(P, "purge_certs", lambda names, w: done.append(("certs", tuple(names))))
    monkeypatch.setattr(M, "_rebuild_rspamd", lambda db: None)
    monkeypatch.setattr(M, "_rebuild_mail_tls", lambda db: done.append(("sni",)))
    md = SimpleNamespace(domain_name="borrado.es", dkim_selector="mail")
    monkeypatch.setattr(db, "delete", lambda x: None)
    warnings = []
    P.purge_mail_domains(db, [md], "cli", warnings)
    assert ("vhost", "borrado.es") in done
    assert ("certs", ("mail.borrado.es", "webmail.borrado.es")) in done
    assert ("sni",) in done and not warnings


from tests.test_user_admin_protection import db  # noqa: E402,F401
