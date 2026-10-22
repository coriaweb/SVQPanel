"""
Reintento de migración tras un fallo: el intento anterior creó el cliente y
falló después (p.ej. el Hestia de origen con BACKUP_SYSTEM desactivado). Ese
cliente vacío se reutiliza en vez de dar "Ya existe un usuario"; un cliente
real que se llame igual NUNCA se reutiliza.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.routes import migrations as mig
from api.models.models_migration import MigrationJob
from api.models.models_domain import Domain
from api.models.models_mail import MailDomain
from api.models.models_client_db import ClientDatabase


class _Q:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *a, **k):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class _DB:
    """Sesión falsa: devuelve las filas configuradas por modelo."""
    def __init__(self, jobs=(), domains=(), mail=(), dbs=()):
        self.data = {MigrationJob: list(jobs), Domain: list(domains),
                     MailDomain: list(mail), ClientDatabase: list(dbs)}

    def query(self, model):
        return _Q(self.data.get(model, []))


def _user(**kw):
    base = dict(id=5, is_admin=False, role="user")
    base.update(kw)
    return SimpleNamespace(**base)


def _job(status):
    return SimpleNamespace(status=status)


def test_cliente_vacio_de_migracion_fallida_se_reutiliza():
    db = _DB(jobs=[_job("failed")])
    assert mig._is_leftover_migration_client(db, _user()) is True


def test_varios_intentos_fallidos_tambien():
    db = _DB(jobs=[_job("failed"), _job("failed")])
    assert mig._is_leftover_migration_client(db, _user()) is True


def test_cliente_sin_migraciones_no_se_toca():
    # Un cliente creado a mano que se llama igual: no es nuestro.
    assert mig._is_leftover_migration_client(_DB(), _user()) is False


def test_cliente_con_una_migracion_buena_no_se_toca():
    db = _DB(jobs=[_job("failed"), _job("success")])
    assert mig._is_leftover_migration_client(db, _user()) is False


def test_migracion_en_curso_no_se_toca():
    db = _DB(jobs=[_job("running")])
    assert mig._is_leftover_migration_client(db, _user()) is False


def test_cliente_con_recursos_no_se_toca():
    for extra in ({"domains": [object()]}, {"mail": [object()]}, {"dbs": [object()]}):
        db = _DB(jobs=[_job("failed")], **extra)
        assert mig._is_leftover_migration_client(db, _user()) is False, extra


def test_admin_nunca():
    db = _DB(jobs=[_job("failed")])
    assert mig._is_leftover_migration_client(db, _user(is_admin=True)) is False
    assert mig._is_leftover_migration_client(db, _user(role="admin")) is False
