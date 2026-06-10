"""
Tests de los validadores de entrada (primera línea de defensa).

validate_username/domain/ipv6/email rechazan input malformado antes de que llegue
a comandos del SO o SQL. Cubrirlos evita que un cambio afloje la validación.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.utils import (
    validate_username, validate_domain, validate_ipv6, validate_email,
)


# ── Username ──
def test_username_valido():
    assert validate_username("user1")
    assert validate_username("_svq_a3f9")
    assert validate_username("juan_perez")


def test_username_invalido():
    assert not validate_username("1user")        # no empieza por letra/_
    assert not validate_username("a")            # demasiado corto
    assert not validate_username("user con espacios")
    assert not validate_username("user;rm -rf")  # caracteres de shell
    assert not validate_username("")


# ── Dominio ──
def test_dominio_valido():
    assert validate_domain("ejemplo.com")
    assert validate_domain("sub.ejemplo.com")
    assert validate_domain("mi-dominio.es")


def test_dominio_invalido():
    assert not validate_domain("ejemplo")          # sin TLD
    assert not validate_domain("ejemplo..com")     # doble punto
    assert not validate_domain("-ejemplo.com")     # empieza por guión
    assert not validate_domain("ejemplo.com/path") # con ruta
    assert not validate_domain("")


# ── IPv6 ──
def test_ipv6_valida():
    assert validate_ipv6("2001:db8::1")
    assert validate_ipv6("::1")
    assert validate_ipv6("2001:678:ff4:163b:9a9d:d27:b78e:4832")


def test_ipv6_invalida():
    assert not validate_ipv6("192.168.1.1")   # eso es IPv4
    assert not validate_ipv6("no-es-ip")
    assert not validate_ipv6("")


# ── Email ──
def test_email_valido():
    assert validate_email("info@svqhost.com")
    assert validate_email("juan.perez+test@dominio.es")


def test_email_invalido():
    assert not validate_email("sin-arroba")
    assert not validate_email("@dominio.com")
    assert not validate_email("user@")
    assert not validate_email("")
