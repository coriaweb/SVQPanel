"""
normalize_hostname_content: el editor DNS añade el punto final a los
contenidos que son un FQDN (MX/CNAME/NS/PTR/DNAME y el target de SRV). Sin
él, BIND trata el valor como relativo y le pega la zona detrás — un cliente
que escribe `mail.sudominio.com` en un MX publicaba
`mail.sudominio.com.sudominio.com.` (correo caído; visto en producción).
El tecnicismo lo resuelve el editor, no el usuario final.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.routes.dns import normalize_hostname_content as norm


def test_mx_sin_punto_lo_gana():
    assert norm("MX", "mail.globatel.es") == "mail.globatel.es."


def test_mx_con_punto_no_se_duplica():
    assert norm("MX", "mail.globatel.es.") == "mail.globatel.es."


def test_nombre_relativo_sin_puntos_se_respeta():
    # `mail` a secas es un relativo válido (se completa con la zona a propósito)
    assert norm("CNAME", "mail") == "mail"


def test_cname_ns_ptr_dname_tambien():
    assert norm("CNAME", "webmail.dominio.com") == "webmail.dominio.com."
    assert norm("NS", "ns1.proveedor.net") == "ns1.proveedor.net."
    assert norm("PTR", "mail.dominio.com") == "mail.dominio.com."
    assert norm("DNAME", "otro.dominio.com") == "otro.dominio.com."


def test_srv_solo_el_target():
    assert norm("SRV", "0 993 mail.dominio.com") == "0 993 mail.dominio.com."
    assert norm("SRV", "0 993 mail.dominio.com.") == "0 993 mail.dominio.com."


def test_una_ip_no_gana_punto():
    # Contenido IP (aunque sea inválido en un MX) no debe convertirse en "IP."
    assert norm("MX", "185.104.188.44") == "185.104.188.44"


def test_tipos_de_datos_no_se_tocan():
    assert norm("A", "185.104.188.44") == "185.104.188.44"
    assert norm("TXT", "v=spf1 a mx -all") == "v=spf1 a mx -all"
    assert norm("AAAA", "2001:db8::1") == "2001:db8::1"
