"""
Migrador SVQPanel → SVQPanel, fase 1: export de una cuenta en el origen.
Sin ids (claves naturales), secretos descifrados, solo lo del cliente.
"""
import json

import pytest

from scripts import svq_export as X


@pytest.fixture
def db(monkeypatch):
    from cryptography.fernet import Fernet
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from api.models.database import Base, load_all_models
    load_all_models()
    from api.models.models_user import User
    from api.models.models_domain import Domain
    from api.models.models_mail import MailDomain, Mailbox, MailAlias
    from api.models.models_client_db import ClientDatabase
    from api.models.models_dns import DnsZone, DnsRecord
    from api.models.models_cron import CronJob

    key = Fernet.generate_key().decode()
    monkeypatch.setenv("PANEL_ENCRYPTION_KEY", key)
    f = Fernet(key.encode())

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    users = {}
    for name, role in (("admin", "admin"), ("marta", "user"), ("otro", "user")):
        u = User(username=name, email=f"{name}@ejemplo.es", role=role,
                 is_admin=(role == "admin"), is_active=True)
        u.set_password("Passw0rd!x")
        s.add(u)
        s.flush()
        users[name] = u
    # Ids desplazados: el export NO debe depender de ellos
    for name, dom in (("otro", "ajeno.es"), ("marta", "ejemplo.es"), ("marta", "tienda.ejemplo.es")):
        s.add(Domain(user_id=users[name].id, domain_name=dom,
                     public_html=f"/home/{name}/web/{dom}/public_html",
                     php_version="8.3", is_subdomain=dom.startswith("tienda.")))
    s.flush()
    dom = s.query(Domain).filter_by(domain_name="ejemplo.es").one()
    md = MailDomain(user_id=users["marta"].id, domain_id=dom.id, domain_name="ejemplo.es")
    s.add(md)
    s.flush()
    s.add(Mailbox(mail_domain_id=md.id, username="info", password_hash="{SHA512-CRYPT}$6$x"))
    s.add(MailAlias(mail_domain_id=md.id, source="ventas", destination="info@ejemplo.es"))
    s.add(ClientDatabase(user_id=users["marta"].id, domain_id=dom.id,
                         db_name="marta_wp", db_name_suffix="wp", db_user="marta_wp",
                         db_user_suffix="wp", db_password_hash="x",
                         db_password_enc=f.encrypt(b"secreta-123").decode()))
    for zname in ("ejemplo.es", "ajeno.es"):
        z = DnsZone(domain_name=zname, ip_address="203.0.113.10")
        s.add(z)
        s.flush()
        s.add(DnsRecord(zone_id=z.id, record_type="A", name="@", content="203.0.113.10"))
    s.add(CronJob(user_id=users["marta"].id, domain_id=dom.id, minute="*/5", hour="*",
                  day="*", month="*", weekday="*", command="php wp-cron.php"))
    s.commit()
    yield s
    s.close()


def test_solo_lo_del_cliente_y_sin_ids(db):
    warnings = []
    out = X.export_panel_rows(db, "marta", warnings)
    t = out["tables"]
    assert [d["domain_name"] for d in t["domains"]] == ["ejemplo.es", "tienda.ejemplo.es"]
    assert [z["domain_name"] for z in t["dns_zones"]] == ["ejemplo.es"]       # no la de «otro»
    assert len(t["dns_records"]) == 1
    # Ninguna fila lleva su id; las FK van por clave natural
    for rows in t.values():
        for r in rows:
            assert "id" not in r
    d = t["domains"][0]
    assert d["user_id"] == {"$ref": "users", "key": "marta"}
    assert t["mailboxes"][0]["mail_domain_id"] == {"$ref": "mail_domains", "key": "ejemplo.es"}
    assert t["dns_records"][0]["zone_id"] == {"$ref": "dns_zones", "key": "ejemplo.es"}
    assert t["cron_jobs"][0]["domain_id"] == {"$ref": "domains", "key": "ejemplo.es"}
    # Fechas marcadas, hash del panel tal cual
    assert "$dt" in t["users"][0]["created_at"]
    assert t["users"][0]["password_hash"]
    assert not warnings


def test_secretos_descifrados_para_recifrar_en_destino(db):
    t = X.export_panel_rows(db, "marta", [])["tables"]
    assert t["client_databases"][0]["db_password_enc"] == {"$enc": "secreta-123"}


def test_clave_distinta_avisa_y_no_filtra_el_cifrado(db, monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("PANEL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    w = []
    t = X.export_panel_rows(db, "marta", w)["tables"]
    assert t["client_databases"][0]["db_password_enc"] is None
    assert any("no se pudo descifrar" in x for x in w)


def test_rechaza_admin_y_usuario_inexistente(db):
    with pytest.raises(X.ExportError):
        X.export_panel_rows(db, "admin", [])
    with pytest.raises(X.ExportError):
        X.export_panel_rows(db, "nadie", [])


def test_salida_es_json_valido(db, monkeypatch):
    monkeypatch.setattr(X, "export_mariadb", lambda t, w: {"users": [], "databases": []})
    monkeypatch.setattr(X, "export_dkim", lambda t, w: [])
    monkeypatch.setattr(X, "export_ssl", lambda t: [])
    monkeypatch.setattr(X, "_server_ips", lambda: {"ipv4": "203.0.113.10", "ipv6": None})
    data = X.export_account(db, "marta", with_sizes=False)
    back = json.loads(json.dumps(data))
    assert back["format"] == "svqpanel-account" and back["format_version"] == 1
    s = X.summary(back)
    assert s["domains"] == ["ejemplo.es", "tienda.ejemplo.es"]
    assert s["mailboxes"] == 1 and s["crons"] == 1
    assert "$enc" not in json.dumps(s)                    # el resumen no lleva secretos


def test_mariadb_usuarios_con_hash(monkeypatch):
    calls = []

    def fake_sql(q):
        calls.append(q)
        if q.startswith("SELECT Host"):
            return [["localhost"], ["203.0.113.50"]]
        if q.startswith("SHOW CREATE USER"):
            return [["CREATE USER `marta_wp`@`localhost` IDENTIFIED BY PASSWORD '*ABC'"]]
        if q.startswith("SHOW GRANTS"):
            return [["GRANT ALL PRIVILEGES ON `marta_wp`.* TO `marta_wp`@`localhost`"]]
        return [["2048", "12"]]

    monkeypatch.setattr(X, "_sql", fake_sql)
    out = X.export_mariadb({"client_databases": [{"db_name": "marta_wp", "db_user": "marta_wp"}],
                            "database_users": [{"username": "o'hara"}]}, [])
    hosts = sorted((u["user"], u["host"]) for u in out["users"])
    assert ("marta_wp", "203.0.113.50") in hosts
    assert "IDENTIFIED BY PASSWORD" in out["users"][0]["create"]
    assert out["databases"] == [{"name": "marta_wp", "bytes": 2048, "tables": 12}]
    assert any("o\\'hara" in q for q in calls)            # comillas escapadas


def test_cli_registrado():
    import inspect
    from api import cli
    src = inspect.getsource(cli)
    assert '"export_account"' in src and "cmd_export_account(args.username" in src
