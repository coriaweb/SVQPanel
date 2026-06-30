"""
Test de idempotencia de import_db: una migración que se reintenta (porque la
anterior quedó a medias) NO debe fallar con "database exists" (ERROR 1007). El
importador debe DROP ... IF EXISTS antes de CREATE, tanto la BD como el usuario.
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scripts.hestia_import as hi


def _run_import_db(captured_sql):
    """Ejecuta import_db con MariaDB y panel mockeados; captura el SQL emitido."""
    def fake_run(sql):
        captured_sql.append(sql)

    owner = MagicMock(id=7)
    db = MagicMock()
    # No existe ClientDatabase previa.
    db.query.return_value.filter.return_value.first.return_value = None
    report = hi.ImportReport()
    backup = MagicMock()

    dbinfo = {
        "db": "cliente_db",
        "dbuser": "cliente_user",
        "md5": "*ABC123",            # hash nativo → usuario con hash
        "type": "mysql",
        "charset": "utf8mb4",
        "_dump": None,               # sin dump (no toca _import_sql_dump)
    }

    with patch("api.routes.databases._run_mariadb", side_effect=fake_run), \
         patch("api.routes.databases._hash_password", return_value="h"), \
         patch("api.routes.databases._encrypt_password", return_value=None), \
         patch("api.routes.databases._generate_password", return_value="pw"), \
         patch("api.models.models_client_db.ClientDatabase", MagicMock()):
        hi.import_db(backup, dbinfo, owner, db, report)
    return report


def test_dropea_bd_antes_de_crear():
    sql = []
    _run_import_db(sql)
    joined = "\n".join(sql)
    # Debe haber un DROP DATABASE IF EXISTS y luego el CREATE.
    drop_idx = next(i for i, s in enumerate(sql) if "DROP DATABASE IF EXISTS" in s and "cliente_db" in s)
    create_idx = next(i for i, s in enumerate(sql) if "CREATE DATABASE" in s and "cliente_db" in s)
    assert drop_idx < create_idx, "el DROP DATABASE debe ir ANTES del CREATE"


def test_dropea_usuario_antes_de_crear():
    sql = []
    _run_import_db(sql)
    assert any("DROP USER IF EXISTS" in s and "cliente_user" in s for s in sql), \
        "debe hacer DROP USER IF EXISTS para ser idempotente"
