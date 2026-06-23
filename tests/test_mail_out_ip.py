"""
Tests de la IP de salida SMTP por dominio (IPv4/IPv6) — generación del bloque
de master.cf de Postfix. Función pura: dado el mapa de config {@dominio:
'ipv4|ipv6|pref'}, produce el bloque con los binds y la preferencia correctos.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.mail_manager import MailManager


def _mm():
    # Evita __init__ (require_root usa os.geteuid, no disponible en Windows).
    return MailManager.__new__(MailManager)


def test_bloque_ipv4_por_defecto():
    mm = _mm()
    block = mm._build_master_bind_block({"@ejemplo.com": "1.2.3.4||ipv4"})
    assert "svqout_ejemplo_com" in block
    assert "smtp_bind_address=1.2.3.4" in block
    assert "smtp_bind_address6=" in block
    assert "smtp_address_preference=ipv4" in block


def test_bloque_ipv6_preferida():
    mm = _mm()
    block = mm._build_master_bind_block({"@ejemplo.com": "1.2.3.4|2001:db8::1|ipv6"})
    assert "smtp_bind_address=1.2.3.4" in block
    assert "smtp_bind_address6=2001:db8::1" in block
    assert "smtp_address_preference=ipv6" in block


def test_pref_ipv6_sin_ipv6_cae_a_ipv4():
    # Si pide ipv6 pero no hay IPv6, no debe forzar preferencia ipv6
    mm = _mm()
    block = mm._build_master_bind_block({"@ejemplo.com": "1.2.3.4||ipv6"})
    assert "smtp_address_preference=ipv4" in block
    assert "smtp_address_preference=ipv6" not in block


def test_varios_dominios():
    mm = _mm()
    block = mm._build_master_bind_block({
        "@a.com": "1.1.1.1||ipv4",
        "@b.com": "2.2.2.2|2001:db8::2|ipv6",
    })
    assert "svqout_a_com" in block and "svqout_b_com" in block
    # b.com prefiere ipv6
    assert "2001:db8::2" in block


def test_transport_name_sanitiza():
    mm = _mm()
    assert mm._transport_name("mi-dominio.com") == "svqout_mi_dominio_com"
