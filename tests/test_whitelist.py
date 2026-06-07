"""
Tests de la validación de IPs/CIDR de la whitelist del panel.

parse_ip_entries es seguridad-crítica: si acepta basura, el snippet nginx queda
mal y puedes bloquear o abrir el panel por error. Si rechaza IPs válidas, el
admin no puede configurar su whitelist.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from scripts.panel_whitelist_manager import parse_ip_entries


def test_vacio_devuelve_lista_vacia():
    assert parse_ip_entries("") == []
    assert parse_ip_entries(None) == []
    assert parse_ip_entries("   \n  \n") == []


def test_ip_v4_suelta():
    assert parse_ip_entries("88.1.2.3") == ["88.1.2.3"]


def test_varias_ips_por_linea():
    raw = "88.1.2.3\n10.0.0.5\n192.168.1.1"
    assert parse_ip_entries(raw) == ["88.1.2.3", "10.0.0.5", "192.168.1.1"]


def test_separadas_por_coma():
    assert parse_ip_entries("88.1.2.3, 10.0.0.5") == ["88.1.2.3", "10.0.0.5"]


def test_cidr_v4():
    assert parse_ip_entries("10.0.0.0/8") == ["10.0.0.0/8"]
    assert parse_ip_entries("203.0.113.0/24") == ["203.0.113.0/24"]


def test_ipv6_suelta_y_cidr():
    assert parse_ip_entries("2a01:abc::1") == ["2a01:abc::1"]
    assert parse_ip_entries("2a01:abc::/64") == ["2a01:abc::/64"]


def test_espacios_se_recortan():
    assert parse_ip_entries("  88.1.2.3  \n  10.0.0.5 ") == ["88.1.2.3", "10.0.0.5"]


def test_ip_invalida_lanza_error():
    with pytest.raises(ValueError):
        parse_ip_entries("no-es-una-ip")
    with pytest.raises(ValueError):
        parse_ip_entries("999.999.999.999")
    with pytest.raises(ValueError):
        parse_ip_entries("88.1.2.3/99")   # prefijo CIDR fuera de rango


def test_una_invalida_entre_validas_lanza_error():
    # No debe colar una entrada mala aunque las demás sean válidas
    with pytest.raises(ValueError):
        parse_ip_entries("88.1.2.3\nbasura\n10.0.0.5")
