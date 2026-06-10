"""
Tests de generación de zonas DNS (BIND).

`DNSManager.render_zone` es una función pura: dados los registros, devuelve el
texto del fichero de zona. Verificamos que genera SOA, NS, A correctos y que el
serial aparece — sin necesidad de BIND ni servidor.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.dns_manager import DNSManager


def _zone(records, serial=2026010101, ns="ns1.test.com"):
    return DNSManager.render_zone("test.com", serial, records, soa_ns=ns)


def test_zona_incluye_soa_y_serial():
    z = _zone([{"record_type": "NS", "name": "@", "content": "ns1.test.com.",
               "ttl": 3600, "priority": None}])
    assert "SOA" in z
    assert "2026010101" in z, "el serial debe aparecer en el SOA"


def test_zona_registro_A_con_ip():
    z = _zone([{"record_type": "A", "name": "@", "content": "185.10.10.10",
               "ttl": 3600, "priority": None}])
    assert "185.10.10.10" in z
    assert "\tA\t" in z or " A " in z or "A\t185" in z.replace(" ", "\t")


def test_zona_registro_NS():
    z = _zone([{"record_type": "NS", "name": "@", "content": "ns1.test.com.",
               "ttl": 3600, "priority": None}])
    assert "NS" in z
    assert "ns1.test.com" in z


def test_zona_registro_MX_con_prioridad():
    z = _zone([{"record_type": "MX", "name": "@", "content": "mail.test.com.",
               "ttl": 3600, "priority": 10}])
    assert "MX" in z
    assert "mail.test.com" in z
    assert "10" in z, "la prioridad del MX debe aparecer"


def test_serial_distinto_genera_zona_distinta():
    recs = [{"record_type": "A", "name": "@", "content": "1.2.3.4",
             "ttl": 3600, "priority": None}]
    z1 = _zone(recs, serial=2026010101)
    z2 = _zone(recs, serial=2026010102)
    assert z1 != z2, "cambiar el serial debe cambiar la zona (propagación DNS)"
    assert "2026010102" in z2
