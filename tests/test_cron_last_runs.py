"""
GET /api/crons/last-runs: la última ejecución de cada cron en UNA consulta
(antes la vista hacía una petición por cron), sin la salida y respetando el
alcance del usuario.
"""
import asyncio
from datetime import datetime, timedelta

import pytest


@pytest.fixture
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from api.models.database import Base, load_all_models
    load_all_models()
    from api.models.models_user import User
    from api.models.models_cron import CronJob
    from api.models.models_cron_run import CronRun

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
    crons = {}
    for name in ("marta", "otro"):
        c = CronJob(user_id=users[name].id, minute="0", hour="*", day="*",
                    month="*", weekday="*", command="/usr/bin/php x.php", is_active=True)
        s.add(c)
        s.flush()
        crons[name] = c
    # Cron sin ejecuciones: no debe aparecer
    s.add(CronJob(user_id=users["marta"].id, minute="5", hour="*", day="*",
                  month="*", weekday="*", command="true", is_active=True))
    base = datetime(2026, 11, 11, 7, 0, 1)
    for h in range(4):
        s.add(CronRun(cron_id=crons["marta"].id, started_at=base + timedelta(hours=h),
                      duration_ms=24000 + h, exit_code=0, output="x" * 8000, trigger="auto"))
    s.add(CronRun(cron_id=crons["otro"].id, started_at=base, duration_ms=10,
                  exit_code=1, output="fallo", trigger="manual"))
    s.commit()
    yield s, users, crons
    s.close()


def _call(s, user):
    from api.routes.crons import crons_last_runs
    return asyncio.run(crons_last_runs(current_user=user, db=s))


def test_admin_ve_la_ultima_de_cada_cron(db):
    s, users, crons = db
    out = _call(s, users["admin"])
    assert set(out) == {str(crons["marta"].id), str(crons["otro"].id)}
    m = out[str(crons["marta"].id)]
    assert m["started_at"].startswith("2026-11-11T10:00:01")
    assert m["duration_ms"] == 24003 and m["exit_code"] == 0
    assert "output" not in m          # la salida no viaja en el listado
    assert out[str(crons["otro"].id)]["exit_code"] == 1


def test_usuario_solo_ve_los_suyos(db):
    s, users, crons = db
    out = _call(s, users["marta"])
    assert set(out) == {str(crons["marta"].id)}


def test_ruta_declarada_antes_que_cron_id():
    """/crons/last-runs debe ir ANTES de /crons/{cron_id}: si no, FastAPI la
    casa con {cron_id} y responde 422."""
    from api.routes.crons import router
    paths = [r.path for r in router.routes]
    assert paths.index("/crons/last-runs") < paths.index("/crons/{cron_id}")
