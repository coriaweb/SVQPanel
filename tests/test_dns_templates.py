"""
La regeneración de una zona DNS debe respetar la PLANTILLA elegida
(dns/web/mail/default), no aplicar siempre la completa.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.routes.dns import _build_template_records

NS1, NS2 = "nssvq1.svqhost.red", "nssvq2.svqhost.red"


def _recs(template):
    return _build_template_records("ejemplo.com", "1.2.3.4", "2001:db8::1",
                                   NS1, NS2, template=template)


def _types(template):
    return [r["record_type"] for r in _recs(template)]


def test_solo_dns_minima():
    t = _types("dns")
    assert t == ["NS", "NS", "A", "AAAA"]
    assert "MX" not in t and "TXT" not in t and "CNAME" not in t


def test_solo_web_sin_correo():
    recs = _recs("web")
    types = [r["record_type"] for r in recs]
    assert "CNAME" in types and any(r["name"] == "www" for r in recs)
    # sin nada de correo
    assert "MX" not in types and "TXT" not in types and "SRV" not in types


def test_solo_correo_sin_web():
    recs = _recs("mail")
    types = [r["record_type"] for r in recs]
    assert "MX" in types
    assert any(r["name"] == "_dmarc" for r in recs)
    assert any(r["record_type"] == "TXT" and r["content"].startswith("v=spf1") for r in recs)
    # mail trae A de 'mail' y webmail, pero NO www ni el A de '@'
    assert not any(r["record_type"] == "CNAME" and r["name"] == "www" for r in recs)
    assert not any(r["record_type"] == "A" and r["name"] == "@" for r in recs)


def test_completa():
    t = _types("default")
    for needed in ("NS", "A", "AAAA", "CNAME", "MX", "TXT", "SRV", "CAA"):
        assert needed in t, f"falta {needed} en la plantilla default"


def test_alias_minimal_es_dns():
    assert _types("minimal") == _types("dns")


def test_template_desconocida_cae_en_default():
    assert _types("inventada") == _types("default")
