"""
Tests del gestor de extensiones PHP por versión (constantes y validación,
sin tocar el sistema).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import php_manager as pm


def test_paquetes_base_protegidos():
    # Quitar cli/fpm/etc. rompería la versión: deben estar protegidos
    for ext in pm.BASE_EXTENSIONS:
        assert ext in pm.PROTECTED_EXTENSIONS
    assert "common" in pm.PROTECTED_EXTENSIONS


def test_redis_y_opcache_protegidos():
    # redis: el caché de objetos por dominio depende de él.
    # opcache: rendimiento de todos los sitios de la versión.
    assert "redis" in pm.PROTECTED_EXTENSIONS
    assert "opcache" in pm.PROTECTED_EXTENSIONS


def test_nombres_de_extension_validos():
    for ok in ("ldap", "imap", "mongodb", "xdebug", "yaml", "ast", "sqlite3"):
        assert pm._EXT_NAME_RE.match(ok), ok


def test_nombres_de_extension_invalidos():
    # Nada de traversal, espacios, mayúsculas ni flags: van a una línea apt-get
    for bad in ("", "../evil", "Foo", "a b", "-flag", "ext;rm", "ext&x", "ldap\n"):
        assert not pm._EXT_NAME_RE.match(bad), repr(bad)
