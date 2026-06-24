"""
Tests de la política de contraseñas (validador + generador). Funciones puras.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.password_policy import (
    validate_password, is_valid, generate_password, normalize_policy,
    DEFAULT_POLICY,
)


def test_default_rechaza_corta():
    errs = validate_password("Ab1")  # default min 12
    assert any("12" in e for e in errs)


def test_default_acepta_buena():
    assert is_valid("MiClaveSegura123")  # 16, may+min+dig


def test_requisitos_individuales():
    pol = {"min_length": 8, "require_upper": True, "require_lower": True,
           "require_digit": True, "require_symbol": False}
    assert validate_password("todominus1", pol)   # falta mayúscula
    assert validate_password("TODOMAYUS1", pol)   # falta minúscula
    assert validate_password("SinNumeros", pol)   # falta dígito
    assert is_valid("Correcta1", pol)


def test_simbolo_requerido():
    pol = {"min_length": 8, "require_symbol": True,
           "require_upper": False, "require_lower": False, "require_digit": False}
    assert validate_password("sinsimbolo", pol)
    assert is_valid("con-simbolo!", pol)


def test_normalize_suelo_minimo():
    # min_length nunca baja de 6 aunque el admin lo ponga absurdo
    assert normalize_policy({"min_length": 2})["min_length"] == 6
    assert normalize_policy({"min_length": "x"})["min_length"] == DEFAULT_POLICY["min_length"]


def test_generador_cumple_siempre():
    # Generar muchas y todas deben validar contra su propia política.
    for pol in (
        DEFAULT_POLICY,
        {"min_length": 8, "require_symbol": True},
        {"min_length": 20, "require_upper": True, "require_lower": True,
         "require_digit": True, "require_symbol": True},
        {"min_length": 6, "require_upper": False, "require_lower": True,
         "require_digit": False, "require_symbol": False},
    ):
        for _ in range(50):
            pwd = generate_password(pol)
            assert is_valid(pwd, pol), f"{pwd!r} no cumple {pol}"


def test_generador_respeta_longitud_minima():
    p = generate_password({"min_length": 24})
    assert len(p) >= 24


def test_generador_es_aleatorio():
    # Dos generaciones seguidas no deberían coincidir (CSPRNG).
    a = generate_password(DEFAULT_POLICY)
    b = generate_password(DEFAULT_POLICY)
    assert a != b
