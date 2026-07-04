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
    block = mm._build_master_bind_block({"@ejemplo.com": "1.2.3.4|2001:db8::1|ipv4"})
    assert "svqout_ejemplo_com" in block
    assert "smtp_bind_address=1.2.3.4" in block
    # Con pref ipv4 NO se declara la IPv6, aunque el dominio la tenga: la IPv6
    # dedicada casi nunca tiene PTR → sin declararla, el correo sale por IPv4
    # (con PTR) y no rebota en Gmail. El bind6 es opt-in (pref ipv6).
    assert "smtp_bind_address6" not in block
    assert "smtp_address_preference=ipv4" in block


def test_bloque_ipv6_preferida():
    mm = _mm()
    block = mm._build_master_bind_block({"@ejemplo.com": "1.2.3.4|2001:db8::1|ipv6"})
    assert "smtp_bind_address=1.2.3.4" in block
    # Solo al elegir ipv6 explícitamente se declara el bind6.
    assert "smtp_bind_address6=2001:db8::1" in block
    assert "smtp_address_preference=ipv6" in block


def test_pref_ipv6_sin_ipv6_cae_a_ipv4():
    # Si pide ipv6 pero no hay IPv6, no debe forzar preferencia ipv6 ni bind6.
    mm = _mm()
    block = mm._build_master_bind_block({"@ejemplo.com": "1.2.3.4||ipv6"})
    assert "smtp_address_preference=ipv4" in block
    assert "smtp_address_preference=ipv6" not in block
    assert "smtp_bind_address6" not in block


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


def test_helo_propio_con_ip_dedicada():
    # Bind con IP DEDICADA (≠ IP global del servidor) → HELO mail.{dominio},
    # que es a lo que apunta el PTR de esa IP. Sin esto el receptor ve
    # SPF_HELO_SOFTFAIL y el par PTR↔HELO roto (visto con globatel.es).
    mm = _mm()
    block = mm._build_master_bind_block(
        {"@globatel.es": "185.104.188.44||ipv4"}, server_ipv4="185.104.188.71")
    assert "smtp_helo_name=mail.globatel.es" in block


def test_sin_helo_propio_con_ip_del_servidor():
    # Bind con la IP global del servidor → HELO por defecto (hostname), que
    # coincide con el PTR de esa IP. No debe inyectarse smtp_helo_name.
    mm = _mm()
    block = mm._build_master_bind_block(
        {"@a.com": "185.104.188.71||ipv4"}, server_ipv4="185.104.188.71")
    assert "smtp_helo_name" not in block


def test_sin_helo_si_no_se_conoce_la_ip_del_servidor():
    # Sin server_ipv4 (entorno raro/dev) no se puede distinguir → no tocar HELO.
    mm = _mm()
    block = mm._build_master_bind_block({"@a.com": "1.2.3.4||ipv4"})
    assert "smtp_helo_name" not in block
