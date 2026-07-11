"""
validate_record: valida el contenido de un registro DNS ANTES de guardarlo.

POR QUÉ (caso real, jul 2026): un CAA se guardó con la comilla sin cerrar

    @  IN  CAA  0 issue "letsencrypt.org

y BIND no rechazó ese registro: rechazó la ZONA ENTERA ("unbalanced quotes →
zone not loaded"). Dos dominios estuvieron horas sin resolver en el master del
cluster, y el panel lo reportaba como "ns1 caído" — un síntoma que despista.

Un registro inválido no rompe un registro: rompe TODO el dominio.

Los tests de no-regresión (al final) son igual de importantes que los de
detección: el validador NO debe rechazar ni reescribir los registros que ya
funcionan en producción. La primera versión rechazaba los 25 SRV de correo de
la flota, porque el panel guarda la prioridad en su propia columna y en
`content` solo van 3 campos.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.dns_validator import validate_record as v


# ── CAA: el registro que nos tumbó dos zonas ────────────────────────────────

def test_caa_sin_comilla_de_cierre_se_rechaza():
    """EL BUG REAL. BIND descarta la zona entera por esto."""
    with pytest.raises(ValueError, match="comillas"):
        v("CAA", '0 issue "letsencrypt.org')


def test_caa_correcto_pasa():
    assert v("CAA", '0 issue "letsencrypt.org"') == '0 issue "letsencrypt.org"'
    assert v("CAA", '0 issuewild "letsencrypt.org"') == '0 issuewild "letsencrypt.org"'


def test_caa_tag_invalido_se_rechaza():
    with pytest.raises(ValueError, match="[Tt]ag"):
        v("CAA", '0 loquesea "letsencrypt.org"')


def test_caa_flag_fuera_de_rango_se_rechaza():
    with pytest.raises(ValueError, match="0 a 255"):
        v("CAA", '999 issue "letsencrypt.org"')


# ── Comillas desbalanceadas en TXT (mismo efecto: zona no carga) ─────────────

def test_txt_con_comilla_abierta_se_rechaza():
    with pytest.raises(ValueError, match="comillas"):
        v("TXT", '"v=spf1 a mx -all')


def test_txt_se_guarda_en_crudo_sin_tocarlo():
    """
    La BD guarda el TXT sin comillas a propósito: es DNSManager._txt_rdata()
    quien las pone y trocea a 255 al renderizar la zona. El validador NO debe
    reescribirlo (duplicaría comillas y cambiaría registros que ya funcionan).
    """
    spf = "v=spf1 a mx ip4:185.104.188.220 -all"
    assert v("TXT", spf) == spf


# ── IPs: el tipo debe corresponder con la familia ────────────────────────────

def test_a_con_ipv4_pasa():
    assert v("A", "185.104.188.220") == "185.104.188.220"


def test_a_con_ipv6_se_rechaza():
    with pytest.raises(ValueError, match="IPv4"):
        v("A", "2001:db8::1")


def test_aaaa_con_ipv6_pasa():
    assert v("AAAA", "2001:678:ff4:d48d::1") == "2001:678:ff4:d48d::1"


def test_aaaa_con_ipv4_se_rechaza():
    with pytest.raises(ValueError, match="IPv6"):
        v("AAAA", "185.104.188.220")


def test_a_con_texto_se_rechaza():
    with pytest.raises(ValueError):
        v("A", "no-es-una-ip")


# ── MX/CNAME apuntando a una IP: BIND lo acepta pero rompe el servicio ───────

def test_mx_con_ip_se_rechaza():
    """
    Un MX a una IP es sintácticamente válido para BIND (una IP "parece" un
    hostname), pero el correo deja de entregarse (RFC 2181 §10.3). Error muy
    común del cliente, y sin ninguna pista de por qué falla.
    """
    with pytest.raises(ValueError, match="IP"):
        v("MX", "185.104.188.220")


def test_mx_con_hostname_pasa():
    assert v("MX", "mail.dominio.com") == "mail.dominio.com"


def test_cname_con_ip_se_rechaza():
    with pytest.raises(ValueError, match="IP"):
        v("CNAME", "185.104.188.220")


# ── SRV: OJO, el panel guarda la prioridad en su propia columna ──────────────

def test_srv_formato_del_panel_3_campos():
    """
    NO-REGRESIÓN: así es como el panel guarda los SRV de correo (peso, puerto,
    destino). La prioridad va en DnsRecord.priority. La primera versión del
    validador rechazaba los 25 SRV de la flota por asumir 4 campos.
    """
    assert v("SRV", "0 587 mail.svqhost.com.") == "0 587 mail.svqhost.com."
    assert v("SRV", "0 993 mail.coriaweb.es.") == "0 993 mail.coriaweb.es."


def test_srv_formato_completo_4_campos_tambien_vale():
    assert v("SRV", "10 5 5060 sip.dominio.com") == "10 5 5060 sip.dominio.com"


def test_srv_incompleto_se_rechaza():
    with pytest.raises(ValueError, match="SRV"):
        v("SRV", "0 mail.dominio.com")


def test_srv_puerto_fuera_de_rango_se_rechaza():
    with pytest.raises(ValueError, match="0 a 65535"):
        v("SRV", "0 99999 mail.dominio.com")


# ── No regresión: los registros reales de producción no se tocan ─────────────

REGISTROS_REALES = [
    ("A", "185.104.188.220"),
    ("AAAA", "2001:678:ff4:d48d:b692:91a9:7dff:6d33"),
    ("CNAME", "coriaweb.es."),
    ("MX", "mail.coriaweb.es."),
    ("NS", "nssvq1.svqhost.red."),
    ("TXT", "v=spf1 a mx ip4:185.104.188.220 -all"),
    ("TXT", "v=DMARC1; p=quarantine; pct=100"),
    ("TXT", "v=DKIM1; k=rsa; p=" + "A" * 400),   # DKIM 2048: >255 chars
    ("CAA", '0 issue "letsencrypt.org"'),
    ("CAA", '0 issuewild "letsencrypt.org"'),
    ("SRV", "0 587 mail.svqhost.com."),
    ("SRV", "0 993 mail.coriaweb.hosting."),
]


@pytest.mark.parametrize("rtype,content", REGISTROS_REALES)
def test_registros_reales_ni_se_rechazan_ni_se_modifican(rtype, content):
    """El validador no debe tocar lo que ya funciona en producción."""
    assert v(rtype, content) == content.strip()
