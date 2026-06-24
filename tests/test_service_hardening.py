"""
Tests de la lógica de inserción de `version "none"` en named.conf.options
(idempotencia y no romper el bloque options). Probamos la transformación de
texto sin tocar el sistema.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _insert_version(content):
    """Réplica de la transformación de harden_bind (parte testeable)."""
    if re.search(r"version\s+", content):
        return content  # ya tiene version
    return re.sub(r"(options\s*\{)", r'\1\n\tversion "none";', content, count=1)


def test_inserta_version_en_options():
    src = 'options {\n\tdirectory "/var/cache/bind";\n};\n'
    out = _insert_version(src)
    assert 'version "none";' in out
    assert out.index("version") > out.index("options {")


def test_idempotente_si_ya_tiene_version():
    src = 'options {\n\tversion "1.2.3";\n};\n'
    assert _insert_version(src) == src   # no toca nada


def test_no_rompe_si_no_hay_bloque_options():
    src = "// sin bloque options\n"
    assert _insert_version(src) == src   # devuelve igual (no hay dónde insertar)
