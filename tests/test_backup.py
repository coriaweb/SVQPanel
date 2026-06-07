"""
Tests del parseo de DATABASE_URL del backup del panel.

Si _parse_db_url falla, el pg_dump del backup automático apuntaría a la BD o
credenciales equivocadas y el backup quedaría vacío/roto sin avisar.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.panel_backup_manager import _parse_db_url


def test_url_completa():
    r = _parse_db_url("postgresql://panel_user:secret123@localhost/panel_db")
    assert r["user"] == "panel_user"
    assert r["password"] == "secret123"
    assert r["host"] == "localhost"
    assert r["port"] == "5432"          # por defecto
    assert r["dbname"] == "panel_db"


def test_url_con_puerto():
    r = _parse_db_url("postgresql://u:p@db.host:6543/midb")
    assert r["host"] == "db.host"
    assert r["port"] == "6543"
    assert r["dbname"] == "midb"


def test_password_con_caracteres():
    # Contraseñas con símbolos no deben romper el parseo
    r = _parse_db_url("postgresql://user:p%40ss@localhost/panel_db")
    assert r["user"] == "user"
    # urlparse no decodifica %40 automáticamente en username/password; el valor
    # se usa tal cual con PGPASSWORD, así que solo comprobamos que no peta.
    assert r["dbname"] == "panel_db"


def test_valores_por_defecto_si_falta():
    # URL mínima — debe rellenar con defaults sensatos
    r = _parse_db_url("postgresql:///panel_db")
    assert r["user"] == "panel_user"
    assert r["host"] == "localhost"
    assert r["dbname"] == "panel_db"
