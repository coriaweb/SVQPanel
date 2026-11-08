"""
Migrador SVQPanel → SVQPanel, fase 4: corte DNS, Let's Encrypt tras el corte,
marcar el origen, la máquina de fases de la UI y las credenciales del job.
"""
import json
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from scripts import svq_cutover as K


@pytest.fixture
def db(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from api.models.database import Base, load_all_models
    load_all_models()
    from api.models.models_user import User
    from api.models.models_domain import Domain
    from api.models.models_mail import MailDomain
    from api.models.models_dns import DnsZone
    from api.models.models_cron import CronJob
    from api.models.models_backup import BackupJob
    monkeypatch.setenv("PANEL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    for name in ("marta", "otro"):
        u = User(username=name, email=f"{name}@ejemplo.es", role="user")
        u.set_password("Passw0rd!x")
        s.add(u)
    s.flush()
    marta = s.query(User).filter_by(username="marta").one()
    otro = s.query(User).filter_by(username="otro").one()
    for uid, d, sub in ((marta.id, "ejemplo.es", False), (marta.id, "blog.ejemplo.es", True),
                        (otro.id, "ajeno.es", False)):
        s.add(Domain(user_id=uid, domain_name=d, public_html="/x", php_version="8.3",
                     is_subdomain=sub, wp_auto_update=True))
    s.add(MailDomain(user_id=marta.id, domain_name="correo.es"))
    for z, active in (("ejemplo.es", False), ("correo.es", False), ("ajeno.es", True)):
        s.add(DnsZone(domain_name=z, is_active=active, serial=2026010101))
    s.add(CronJob(user_id=marta.id, minute="*", hour="*", day="*", month="*", weekday="*",
                  command="php cron.php", is_active=True))
    s.commit()
    s.Session = Session
    yield s
    s.close()


def test_corte_activa_y_publica_solo_lo_de_la_cuenta(db):
    from api.models.models_dns import DnsZone
    published = []
    res = K.cutover(db, "marta", publish=lambda z, d: published.append(z.domain_name))
    assert sorted(published) == ["correo.es", "ejemplo.es"]          # no «ajeno.es»
    zones = {z.domain_name: z for z in db.query(DnsZone).all()}
    assert zones["ejemplo.es"].is_active and zones["correo.es"].is_active
    assert zones["ejemplo.es"].serial > 2026010101                    # serial sube: los NS recargan
    assert res["ok"]


def test_corte_con_fallo_de_publicacion_deja_la_zona_activa(db):
    from api.models.models_dns import DnsZone
    def publish(z, d):
        if z.domain_name == "correo.es":
            raise RuntimeError("cluster caído")
    res = K.cutover(db, "marta", publish=publish)
    assert not res["ok"]
    bad = [z for z in res["zones"] if not z["published"]]
    assert bad[0]["zone"] == "correo.es" and "cluster caído" in bad[0]["error"]
    # Activa: el chequeo de salud del cluster la reintentará
    assert db.query(DnsZone).filter_by(domain_name="correo.es").one().is_active


def test_ssl_solo_donde_el_dns_ya_apunta(db):
    issued, finished = [], []
    res = K.ssl_after_cutover(
        db, "marta", ["ejemplo.es", "blog.ejemplo.es", "mail.correo.es", "webmail.correo.es"],
        "marta@ejemplo.es", "198.51.100.20",
        resolve=lambda n: ["198.51.100.20"] if n == "ejemplo.es" else ["203.0.113.10"],
        issue=lambda d, e: issued.append(d.domain_name),
        finish=lambda d, s: finished.append(d.domain_name))
    assert res["issued"] == ["ejemplo.es"] and issued == finished == ["ejemplo.es"]
    assert res["waiting_dns"] == ["blog.ejemplo.es"]                  # aún al servidor viejo
    assert res["manual"] == ["mail.correo.es", "webmail.correo.es"]


def test_ssl_fallo_de_certbot_no_retira_la_copia(db):
    finished = []
    res = K.ssl_after_cutover(db, "marta", ["ejemplo.es"], "e@x.es", "198.51.100.20",
                              resolve=lambda n: ["198.51.100.20"],
                              issue=lambda d, e: (_ for _ in ()).throw(RuntimeError("rate limit")),
                              finish=lambda d, s: finished.append(d))
    assert res["failed"][0]["domain"] == "ejemplo.es" and not finished


def test_marcar_origen_pausa_lo_que_correria_dos_veces(db):
    from api.models.models_user import User
    from api.models.models_cron import CronJob
    from api.models.models_domain import Domain
    removed = []
    changed = K.mark_migrated(db, "marta", "nuevo.ejemplo.net",
                              remove_cron=lambda u, cid: removed.append((u, cid)))
    u = db.query(User).filter_by(username="marta").one()
    assert u.migrated_to == "nuevo.ejemplo.net" and u.migrated_at
    assert db.query(CronJob).one().is_active is False and removed
    assert sorted(changed["wp_autoupdate_off"]) == ["blog.ejemplo.es", "ejemplo.es"]
    assert db.query(Domain).filter_by(domain_name="ajeno.es").one().wp_auto_update   # ajeno intacto
    # Idempotente
    again = K.mark_migrated(db, "marta", "nuevo.ejemplo.net", remove_cron=lambda *a: None)
    assert again == {"crons_paused": [], "backups_paused": [], "wp_autoupdate_off": []}


# ── rutas: máquina de fases y credenciales ───────────────────────────────────
def _job(db, phase, scope="svq-import", status="success"):
    from api.models.models_migration import MigrationJob
    j = MigrationJob(source_type="ssh", source_kind="svq", scope=scope, status=status,
                     manifest_json=json.dumps({"host": "203.0.113.10", "port": 22,
                                               "ssh_user": "root", "username": "marta",
                                               "phase": phase}))
    db.add(j)
    db.commit()
    return j


def test_fases_protegen_de_machacar_datos(db):
    from api.routes import svq_migrations as R
    bg = SimpleNamespace(add_task=lambda *a, **k: None)
    creds = R.SvqCreds(password="x")
    j = _job(db, "cutover")
    with pytest.raises(HTTPException) as e:
        R.svq_resync(j.id, creds, bg, db=db, current_user=None)
    assert e.value.status_code == 409 and "Recoger correo" in e.value.detail
    j2 = _job(db, "imported")
    with pytest.raises(HTTPException) as e:
        R.svq_mail_catchup(j2.id, creds, bg, db=db, current_user=None)
    assert e.value.status_code == 409
    with pytest.raises(HTTPException):
        R.svq_ssl(j2.id, bg, db=db, current_user=None)              # SSL antes del corte: no
    # Sin contraseña ni clave: no se crea el job
    with pytest.raises(HTTPException) as e:
        R.svq_resync(j2.id, R.SvqCreds(), bg, db=db, current_user=None)
    assert e.value.status_code == 400


def test_resync_crea_job_con_credenciales_cifradas(db):
    from api.routes import svq_migrations as R
    from api.models.models_migration import MigrationJob
    spawned = []
    bg = SimpleNamespace(add_task=lambda f, *a: spawned.append(a))
    j = _job(db, "imported")
    r = R.svq_resync(j.id, R.SvqCreds(password="secreta"), bg, db=db, current_user=None)
    child = db.query(MigrationJob).get(r["data"]["job_id"])
    assert child.scope == "svq-resync" and "secreta" not in (child.ssh_cfg_enc or "")
    assert R._dec_cfg(child.ssh_cfg_enc)["password"] == "secreta"
    assert spawned == [(child.id,)]
    # Mientras corre, no se puede lanzar otro trabajo ni el corte
    child.status = "running"
    db.commit()
    with pytest.raises(HTTPException) as e:
        R.svq_cutover(j.id, R.CutoverRequest(mark_source=False), db=db, current_user=None)
    assert e.value.status_code == 409


def test_job_borra_las_credenciales_aunque_falle(db, monkeypatch):
    from api.routes import svq_migrations as R
    from api.models.models_migration import MigrationJob
    import api.models.database as D
    import scripts.svq_import as I
    monkeypatch.setattr(R, "SessionLocal", db.Session)
    monkeypatch.setattr(D, "SessionLocal", db.Session)
    import api.routes.migrations as M
    monkeypatch.setattr(M, "SessionLocal", db.Session)
    j = _job(db, "importing", status="pending")
    j.ssh_cfg_enc = R._enc_cfg({"host": "h", "password": "secreta"})
    db.commit()
    monkeypatch.setattr(I, "fetch_export",
                        lambda *a, **k: (_ for _ in ()).throw(I.SvqImportError("origen caído")))
    with pytest.raises(I.SvqImportError):
        R.run_svq_job_inproc(j.id)
    db.expire_all()
    j = db.query(MigrationJob).get(j.id)
    assert j.status == "failed" and "origen caído" in j.error
    assert j.ssh_cfg_enc is None
    assert json.loads(j.manifest_json)["phase"] == "failed"


def test_job_importacion_bien_marca_fase_y_certs(db, monkeypatch):
    from api.routes import svq_migrations as R
    from api.models.models_migration import MigrationJob
    import api.models.database as D
    import api.routes.migrations as M
    import scripts.svq_import as I
    import scripts.svq_copy as C
    for mod in (R, D, M):
        monkeypatch.setattr(mod, "SessionLocal", db.Session)
    j = _job(db, "importing", status="pending")
    j.ssh_cfg_enc = R._enc_cfg({"host": "h", "password": "secreta"})
    db.commit()
    data = {"username": "marta", "ssl": [{"name": "ejemplo.es", "source": "letsencrypt"},
                                         {"name": "propio.es", "source": "custom"}]}
    monkeypatch.setattr(I, "fetch_export", lambda *a, **k: data)
    monkeypatch.setattr(I, "apply_import", lambda d, db, report, progress: {"warnings": []})
    monkeypatch.setattr(C, "run_copy", lambda cfg, d, rep, progress=None: {"verify": {"ok": True}})
    R.run_svq_job_inproc(j.id)
    db.expire_all()
    j = db.query(MigrationJob).get(j.id)
    st = json.loads(j.manifest_json)
    assert j.status == "success" and st["phase"] == "imported"
    assert st["letsencrypt"] == ["ejemplo.es"]
    assert j.ssh_cfg_enc is None
    assert "secreta" not in (j.report_json or "")


def test_cli_y_rutas_registradas():
    import inspect
    from api import cli, main
    assert '"svq_mark_migrated"' in inspect.getsource(cli)
    # Por el esquema OpenAPI: en FastAPI nuevas app.routes anida los routers
    # (_IncludedRouter, sin .path) y recorrerlo no vale entre versiones.
    paths = set(main.app.openapi()["paths"])
    for p in ("/api/migrations/svq/analyze", "/api/migrations/svq/import",
              "/api/migrations/svq/{job_id}/cutover", "/api/migrations/svq/{job_id}/ssl",
              "/api/migrations/svq/{job_id}/resync", "/api/migrations/svq/{job_id}/mail-catchup",
              "/api/migrations/svq"):
        assert p in paths, p
