"""
Tests de _dovecot_scheme: convierte el hash de contraseña de un backup de Hestia
al formato con esquema que entiende Dovecot, para CONSERVAR la contraseña del
usuario al migrar el correo. Si un formato no se reconoce, devuelve None y el
importador genera una contraseña nueva (lo que NO queremos si el hash era válido).

Regresión: el formato MD5-CRYPT ($1$) que Hestia usa para cuentas antiguas no
estaba contemplado → se regeneraba la contraseña innecesariamente.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.hestia_import import _dovecot_scheme


def test_md5_crypt_se_conserva():
    # Hestia exporta cuentas viejas con $1$ (MD5-CRYPT). Dovecot lo soporta.
    h = "$1$6cFjvk4D$NLBhgjMLYtlMc61UNmnUy0"
    assert _dovecot_scheme(h) == "{MD5-CRYPT}" + h


def test_sha512_crypt_se_conserva():
    h = "$6$75788ebc5be07530$wzanGKLEpwVtvuf5lU447YVz9n0xJuN4t3GArMQ0KLI"
    assert _dovecot_scheme(h) == "{SHA512-CRYPT}" + h


def test_sha256_crypt_se_conserva():
    h = "$5$rounds=5000$abcdef$ghijkl"
    assert _dovecot_scheme(h) == "{SHA256-CRYPT}" + h


def test_bcrypt_se_conserva():
    for prefix in ("$2y$", "$2a$", "$2b$"):
        h = prefix + "10$abcdefghijklmnopqrstuv"
        assert _dovecot_scheme(h) == "{BLF-CRYPT}" + h


def test_hash_con_esquema_explicito_se_pasa_tal_cual():
    # Hestia a veces ya guarda el esquema delante (p.ej. {SHA512-CRYPT}$6$…).
    h = "{SHA512-CRYPT}$6$75788ebc$wzanGKLE"
    assert _dovecot_scheme(h) == h


def test_hash_vacio_o_desconocido_devuelve_none():
    assert _dovecot_scheme("") is None
    assert _dovecot_scheme(None) is None
    # Texto plano u otro formato no reutilizable → None (se genera nueva).
    assert _dovecot_scheme("contraseñaenplano") is None
