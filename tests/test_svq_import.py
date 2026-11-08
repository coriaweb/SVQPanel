"""
Migrador SVQPanel → SVQPanel, fase 2: recrear la cuenta en el destino.
Extremo a extremo sobre dos BDs SQLite (origen y destino) con claves de cifrado
DISTINTAS y el sistema sustituido por un Ops falso.
"""
import json

import pytest
from cryptography.fernet import Fernet

from scripts import svq_export as X
from scripts import svq_import as I


def _engine():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from api.models.database import Base, load_all_models
    load_all_models()
    e = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    return sessionmaker(bind=e)()


class FakeOps(I.Ops):
    def __init__(self, installed=("8.2", "8.3"), existing_linux=(), existing_mariadb=()):
        self.calls, self.installed = [], list(installed)
        self.existing_linux, self.existing_mariadb = set(existing_linux), set(existing_mariadb)

    def _log(self, *a):
        self.calls.append(a)

    def linux_user_exists(self, n): return n in self.existing_linux
    def installed_php(self): return self.installed
    def resolve_php(self, w): return w if w in self.installed else self.installed[-1]
    def free_bytes(self, p="/home"): return 10 * 2**40
    def server_ips(self, db): return {"ipv4": "198.51.100.20", "ipv6": "2001:db8:2::1"}
    def mariadb(self, sql): self._log("sql", sql); return ""
    def mariadb_exists(self, kind, name): return (kind, name) in self.existing_mariadb
    def create_linux_user(self, u, e, p): self._log("useradd", u)
    def set_shadow_hash(self, u, h): self._log("shadow", u, h)
    def set_shell(self, u, s): self._log("shell", u, s)
    def set_quota(self, u, mb): self._log("quota", u, mb)
    def create_domain_structure(self, u, d, php): self._log("domain", d, php)
    def write_pool(self, dom, owner): self._log("pool", dom.domain_name, dom.php_version)
    def install_cert(self, n, fc, pk): self._log("cert", n)
    def regenerate_vhost(self, dom, db): self._log("vhost", dom.domain_name)
    def create_mail_domain(self, d, u): self._log("maildomain", d)
    def create_mailbox(self, u, d, user, h, q): self._log("mailbox", f"{user}@{d}", h, q)
    def set_forward(self, d, u, dests, keep): self._log("forward", f"{u}@{d}", tuple(dests), keep)
    def set_autoreply(self, u, d, mb): self._log("autoreply", f"{mb.username}@{d}")
    def mail_alias(self, d, s, dest): self._log("alias", f"{s}@{d}", dest)
    def set_mail_routing(self, d, m): self._log("routing", d, m)
    def install_dkim(self, d, sel, key): self._log("dkim", d, sel)
    def enable_webmail(self, d): self._log("webmail", d)
    def rebuild_mail(self, db): self._log("rebuild_mail")
    def add_cron(self, u, cj): self._log("cron", cj.command)
    def create_sftp(self, owner, row):
        self._log("sftp", row["username"])
        return {"username": row["username"], "jail_path": row["jail_path"], "mount_name": row["mount_name"]}
    def mysql_remote_allow(self, ip): self._log("mysql_remote", ip)


SRC_KEY = Fernet.generate_key().decode()
DST_KEY = Fernet.generate_key().decode()


@pytest.fixture
def exported(monkeypatch):
    """Cuenta «marta» montada en el ORIGEN y exportada (como hace el CLI)."""
    import api.utils.secret as S
    from api.models.models_user import User
    from api.models.models_plan import Plan
    from api.models.models_domain import Domain
    from api.models.models_domain_alias import DomainAlias
    from api.models.models_mail import MailDomain, Mailbox, MailAlias
    from api.models.models_client_db import ClientDatabase
    from api.models.models_dns import DnsZone, DnsRecord
    from api.models.models_cron import CronJob
    from api.models.models_sftp_account import SftpAccount
    from api.routes import mail as M

    monkeypatch.setenv("PANEL_ENCRYPTION_KEY", SRC_KEY)
    monkeypatch.setattr(S, "get_secret_key", lambda: "secret-origen")
    src = _engine()
    plan = Plan(name="Pyme", domains_limit=10)
    src.add(plan)
    src.flush()
    u = User(username="marta", email="marta@ejemplo.es", role="user", is_active=True,
             plan_id=plan.id, disk_quota_mb=5000, shell_path="/bin/bash")
    u.set_password("Passw0rd!x")
    src.add(u)
    src.flush()
    for name, extra in (("ejemplo.es", {}), ("blog.ejemplo.es", {"is_subdomain": True}),
                        ("viejo.es", {"php_version": "7.4", "ipv6": "2001:db8:1::5"})):
        kw = {"php_version": "8.3", "ipv4": "203.0.113.10", "force_https": True, **extra}
        src.add(Domain(user_id=u.id, domain_name=name,
                       public_html=f"/home/marta/web/{name}/public_html", **kw))
    src.flush()
    dom = src.query(Domain).filter_by(domain_name="ejemplo.es").one()
    src.add(DomainAlias(domain_id=dom.id, alias_name="ejemplo.com", redirect=True))
    md = MailDomain(user_id=u.id, domain_id=dom.id, domain_name="ejemplo.es",
                    relay_enabled=True, relay_host="smtp.relay.test", catch_all="info@ejemplo.es")
    src.add(md)
    src.flush()
    src.add(Mailbox(mail_domain_id=md.id, username="info", password_hash="{SHA512-CRYPT}$6$orig",
                    quota_mb=2048, forward_to="marta.j@gmail.com", forward_keep_copy=True,
                    autoreply_enabled=True, autoreply_subject="Vacaciones", autoreply_body="Vuelvo",
                    encrypted_password=M._encrypt_password("buzon-pass")))
    src.add(MailAlias(mail_domain_id=md.id, source="ventas", destination="info@ejemplo.es"))
    f = Fernet(SRC_KEY.encode())
    src.add(ClientDatabase(user_id=u.id, domain_id=dom.id, db_name="marta_wp", db_name_suffix="wp",
                           db_user="marta_wp", db_user_suffix="wp", db_password_hash="h",
                           db_password_enc=f.encrypt(b"db-secreta").decode()))
    z = DnsZone(domain_name="ejemplo.es", ip_address="203.0.113.10", dnssec_enabled=True)
    src.add(z)
    src.flush()
    for t, n, c in (("A", "@", "203.0.113.10"), ("A", "www", "203.0.113.10"),
                    ("AAAA", "@", "2001:db8:1::1"), ("A", "correo", "192.0.2.99"),
                    ("TXT", "@", "v=spf1 ip4:203.0.113.10 -all"),
                    ("NS", "@", "ns1.origen.test."), ("MX", "@", "mail.ejemplo.es.")):
        src.add(DnsRecord(zone_id=z.id, record_type=t, name=n, content=c, ttl=3600,
                          priority=10 if t == "MX" else 0))
    src.add(CronJob(user_id=u.id, domain_id=dom.id, minute="*/5", hour="*", day="*", month="*",
                    weekday="*", command="/usr/bin/php7.4 /home/marta/web/ejemplo.es/public_html/cron.php",
                    is_active=True))
    src.add(SftpAccount(owner_id=u.id, username="marta_fotos", label="fotos",
                        target_path="/home/marta/web/ejemplo.es/public_html/fotos",
                        jail_path="/srv/sftp/marta_fotos", mount_name="fotos"))
    src.commit()

    monkeypatch.setattr(X, "_sql", lambda q: [["localhost"]] if q.startswith("SELECT Host") else
                        [["CREATE USER `marta_wp`@`localhost` IDENTIFIED BY PASSWORD '*ABC'"]]
                        if q.startswith("SHOW CREATE") else
                        [["GRANT USAGE ON *.* TO `marta_wp`@`localhost`"],
                         ["GRANT ALL PRIVILEGES ON `marta_wp`.* TO `marta_wp`@`localhost`"]]
                        if q.startswith("SHOW GRANTS") else [["4096", "3"]])
    monkeypatch.setattr(X, "export_dkim", lambda t, w: [{"domain": "ejemplo.es", "selector": "mail",
                                                         "key": "-----BEGIN PRIVATE KEY-----"}])
    monkeypatch.setattr(X, "export_ssl", lambda t: [{"name": "ejemplo.es", "source": "letsencrypt",
                                                    "fullchain": "FC", "privkey": "PK"}])
    monkeypatch.setattr(X, "export_shadow", lambda us: {"marta": "$6$sys", "marta_fotos": "$6$sftp"})
    monkeypatch.setattr(X, "_server_ips", lambda: {"ipv4": "203.0.113.10", "ipv6": "2001:db8:1::1"})
    data = json.loads(json.dumps(X.export_account(src, "marta", with_sizes=False)))
    src.close()
    return data


@pytest.fixture
def dest(monkeypatch):
    import api.utils.secret as S
    monkeypatch.setenv("PANEL_ENCRYPTION_KEY", DST_KEY)
    monkeypatch.setenv("MAIL_ENABLED", "true")
    monkeypatch.setattr(S, "get_secret_key", lambda: "secret-destino")
    import scripts.dns_manager as D
    monkeypatch.setattr(D, "get_panel_nameservers", lambda db: ("ns1.destino.test", "ns2.destino.test"))
    db = _engine()
    yield db
    db.close()


def test_plan_sin_conflictos_y_avisos(exported, dest):
    p = I.plan_import(exported, dest, FakeOps())
    assert p["importable"] and not p["conflicts"]
    w = " ".join(p["warnings"])
    assert "PHP 7.4 no está instalado" in w and "IPv6 dedicada" in w
    assert "relay" in w and "DNSSEC" in w
    assert p["php_changes"] == {"viejo.es": ["7.4", "8.3"]}


def test_plan_detecta_conflictos(exported, dest):
    from api.models.models_user import User
    o = User(username="otro", email="o@x.es", role="user")
    o.set_password("Passw0rd!x")
    dest.add(o)
    dest.commit()
    ops = FakeOps(existing_linux={"marta"}, existing_mariadb={("db", "marta_wp")})
    p = I.plan_import(exported, dest, ops)
    assert not p["importable"]
    assert any("usuario de sistema «marta»" in c for c in p["conflicts"])
    assert any("marta_wp" in c for c in p["conflicts"])
    with pytest.raises(I.SvqImportError):
        I.apply_import(exported, dest, ops=ops)


def test_formato_desconocido(dest):
    with pytest.raises(I.SvqImportError):
        I.plan_import({"format": "otra-cosa"}, dest, FakeOps())
    with pytest.raises(I.SvqImportError):
        I.plan_import({"format": X.FORMAT, "format_version": 99}, dest, FakeOps())


def test_importacion_completa(exported, dest):
    from api.models.models_user import User
    from api.models.models_plan import Plan
    from api.models.models_domain import Domain
    from api.models.models_domain_alias import DomainAlias
    from api.models.models_mail import MailDomain, Mailbox
    from api.models.models_client_db import ClientDatabase
    from api.models.models_dns import DnsZone, DnsRecord
    from api.models.models_cron import CronJob
    from api.models.models_sftp_account import SftpAccount
    from api.routes import mail as M

    ops = FakeOps()
    rep = I.apply_import(exported, dest, ops=ops)
    assert rep["errors"] == [], rep["errors"]
    calls = ops.calls

    # Usuario: mismas contraseñas (panel y sistema), plan, shell y cuota
    u = dest.query(User).filter_by(username="marta").one()
    assert u.check_password("Passw0rd!x")
    assert dest.query(Plan).get(u.plan_id).name == "Pyme"
    assert ("shadow", "marta", "$6$sys") in calls
    assert ("shell", "marta", "/bin/bash") in calls and ("quota", "marta", 5000) in calls

    # Dominios: PHP que falta → el instalado; IPv4 del destino; sin la IPv6 dedicada
    doms = {d.domain_name: d for d in dest.query(Domain).all()}
    assert set(doms) == {"ejemplo.es", "blog.ejemplo.es", "viejo.es"}
    assert doms["viejo.es"].php_version == "8.3" and doms["viejo.es"].ipv6 is None
    assert doms["ejemplo.es"].ipv4 == "198.51.100.20" and doms["ejemplo.es"].force_https
    assert all(d.user_id == u.id for d in doms.values())
    assert dest.query(DomainAlias).one().domain_id == doms["ejemplo.es"].id
    assert ("cert", "ejemplo.es") in calls
    # El certificado se instala ANTES de regenerar el vhost (si no, nginx sin cert)
    assert calls.index(("cert", "ejemplo.es")) < calls.index(("vhost", "ejemplo.es"))

    # BD: misma contraseña recifrada con la clave del DESTINO; usuario MariaDB con su hash
    cdb = dest.query(ClientDatabase).one()
    assert Fernet(DST_KEY.encode()).decrypt(cdb.db_password_enc.encode()) == b"db-secreta"
    sqls = [c[1] for c in calls if c[0] == "sql"]
    assert any("CREATE DATABASE IF NOT EXISTS `marta_wp`" in s for s in sqls)
    assert any("IDENTIFIED BY PASSWORD '*ABC'" in s for s in sqls)
    assert not any(s.startswith("GRANT USAGE") for s in sqls)

    # Correo: hash original, reenvío, autorespuesta, catch-all, DKIM; relay apagado
    md = dest.query(MailDomain).one()
    assert md.relay_enabled is False and md.user_id == u.id
    mb = dest.query(Mailbox).one()
    assert ("mailbox", "info@ejemplo.es", "{SHA512-CRYPT}$6$orig", 2048) in calls
    assert ("forward", "info@ejemplo.es", ("marta.j@gmail.com",), True) in calls
    assert ("autoreply", "info@ejemplo.es") in calls
    assert ("alias", "@@ejemplo.es", "info@ejemplo.es") in calls
    assert ("alias", "ventas@ejemplo.es", "info@ejemplo.es") in calls
    assert ("dkim", "ejemplo.es", "mail") in calls and ("rebuild_mail",) in calls
    # Autologin del webmail recifrado con la clave de SECRET_KEY del destino
    assert M._decrypt_password(mb.encrypted_password) == "buzon-pass"

    # DNS: INACTIVA, IPs del origen → destino, lo ajeno intacto, NS del destino
    z = dest.query(DnsZone).one()
    assert z.is_active is False and z.dnssec_enabled is False
    recs = {(r.record_type, r.name, r.content) for r in dest.query(DnsRecord).all()}
    assert ("A", "@", "198.51.100.20") in recs and ("A", "www", "198.51.100.20") in recs
    assert ("AAAA", "@", "2001:db8:2::1") in recs
    assert ("A", "correo", "192.0.2.99") in recs
    assert any(t == "TXT" and "198.51.100.20" in c and "203.0.113.10" not in c for t, n, c in recs)
    assert not any(c.startswith("ns1.origen") for t, n, c in recs)
    assert ("NS", "@", "ns1.destino.test") in {(t, n, c.rstrip(".")) for t, n, c in recs}

    # Cron con el PHP del dominio en el destino; SFTP con su contraseña de sistema
    cj = dest.query(CronJob).one()
    assert cj.command.startswith("/usr/bin/php8.3 ") and ("cron", cj.command) in calls
    assert dest.query(SftpAccount).one().owner_id == u.id
    assert ("shadow", "marta_fotos", "$6$sftp") in calls

    # Ningún registro de BD sale publicado: no hay llamadas de DNS al sistema
    assert not any(c[0] in ("push_zone", "dns") for c in calls)
    assert rep["next_steps"]


def test_un_fallo_no_para_el_resto(exported, dest):
    class Rompe(FakeOps):
        def create_mailbox(self, *a):
            raise RuntimeError("dovecot caído")
    rep = I.apply_import(exported, dest, ops=Rompe())
    assert [e["type"] for e in rep["errors"]] == ["mailbox"]
    from api.models.models_mail import Mailbox
    from api.models.models_cron import CronJob
    assert dest.query(Mailbox).count() == 0          # sin fila huérfana del buzón fallido
    assert dest.query(CronJob).count() == 1          # lo de después sigue


def test_campos_de_un_origen_mas_nuevo_se_ignoran(exported, dest):
    exported["tables"]["domains"][0]["campo_del_futuro"] = 1
    rep = I.apply_import(exported, dest, ops=FakeOps())
    assert rep["errors"] == []
    assert any("domains.campo_del_futuro" in w for w in rep["warnings"])


def test_las_dependencias_reales_de_ops_existen():
    """Ops (lo que de verdad toca el sistema) no lo ejercitan los tests de arriba:
    si alguien renombra una de estas funciones, que falle aquí y no en la migración."""
    import importlib
    deps = {
        "scripts.dkim_manager.DkimManager": ["_key_path", "_chown_rspamd", "_update_selector_map", "_reload_rspamd"],
        "scripts.mail_manager.MailManager": ["create_mail_domain", "create_mailbox", "_dovecot_set",
                                             "_reload_dovecot", "set_forward", "set_autoreply",
                                             "create_alias", "set_catch_all", "set_mail_routing"],
        "scripts.user_manager.UserManager": ["create_user"],
        "scripts.quota_manager.QuotaManager": ["set_quota"],
        "scripts.domain_manager.DomainManager": ["create_domain"],
        "scripts.webmail_manager.WebmailManager": ["enable"],
        "scripts.cron_manager.CronManager": ["add_cron"],
        "api.routes.databases": ["_run_mariadb"],
        "api.routes.domains": ["_fpm_tuning_of", "_regenerate_from_domain"],
        "api.routes.mail": ["_rebuild_rspamd", "_rebuild_mail_tls", "_apply_domain_sender_ip"],
        "api.utils.nftables_helper": ["ensure_mysql_remote_setup", "mysql_remote_add_ip", "persist_mysql_remote"],
        "scripts.custom_ssl": ["install"],
        "scripts.sftp_account_manager": ["create_account"],
        "scripts.php_ini_manager": ["write_pool"],
    }
    missing = []
    for path, names in deps.items():
        mod, _, cls = path.rpartition(".")
        try:
            obj = getattr(importlib.import_module(mod), cls)
        except (ImportError, AttributeError):
            obj = importlib.import_module(path)
        missing += [f"{path}.{n}" for n in names if not hasattr(obj, n)]
    assert not missing, missing


def test_fetch_export_por_ssh(monkeypatch):
    from types import SimpleNamespace
    import subprocess
    answers = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **k: answers.pop(0))
    cfg = {"host": "203.0.113.10", "password": "x"}

    def run(*resps):
        answers[:] = [SimpleNamespace(**r) for r in resps]
        return I.fetch_export(cfg, "marta")

    # Origen sin SVQPanel / demasiado viejo → error claro, sin exportar
    with pytest.raises(I.SvqImportError, match="no tiene SVQPanel"):
        run({"returncode": 0, "stdout": "NOSVQ\n", "stderr": ""})
    with pytest.raises(I.SvqImportError, match="0.279.0 o superior"):
        run({"returncode": 0, "stdout": "0.276.1\n", "stderr": ""})
    # El origen rechaza la cuenta → su mensaje ERROR: llega tal cual
    with pytest.raises(I.SvqImportError, match="No existe el usuario"):
        run({"returncode": 0, "stdout": "0.279.0", "stderr": ""},
            {"returncode": 2, "stdout": "", "stderr": "log\nERROR: No existe el usuario «marta»"})
    # Bien
    assert run({"returncode": 0, "stdout": "0.279.0", "stderr": ""},
               {"returncode": 0, "stdout": '{"format": "svqpanel-account"}', "stderr": "x"}) \
        == {"format": "svqpanel-account"}
    # Usuario con caracteres raros: ni se intenta
    with pytest.raises(I.SvqImportError):
        I.fetch_export(cfg, "marta; rm -rf /")
