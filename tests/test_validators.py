"""
Tests de la validación de email para Let's Encrypt ACME.

Si esta validación falla, podríamos enviar a certbot un email que Let's Encrypt
rechaza (root@localhost, admin@example.com), rompiendo la emisión de SSL — un
bug que ya sufrimos en el pasado.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from api.utils.validators import validate_acme_email


def test_email_valido():
    assert validate_acme_email("admin@midominio.com") == "admin@midominio.com"


def test_normaliza_a_minusculas_y_recorta():
    assert validate_acme_email("  Admin@Midominio.COM ") == "admin@midominio.com"


def test_rechaza_vacio():
    with pytest.raises(ValueError):
        validate_acme_email("")
    with pytest.raises(ValueError):
        validate_acme_email(None)


def test_rechaza_sin_arroba():
    with pytest.raises(ValueError):
        validate_acme_email("noesunemail")


def test_rechaza_dominios_de_ejemplo():
    for bad in ["admin@example.com", "admin@localhost", "x@test", "y@invalid"]:
        with pytest.raises(ValueError):
            validate_acme_email(bad)


def test_rechaza_dominio_sin_punto():
    # root@localhost o admin@servidor (sin TLD) no sirven para ACME
    with pytest.raises(ValueError):
        validate_acme_email("admin@servidor")
