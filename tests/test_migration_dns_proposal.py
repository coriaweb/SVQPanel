"""
La propuesta DNS de una migración debe:
  - añadir los NS de ESTE servidor (no quedarse con los del origen),
  - descartar los NS/SOA del backup,
  - reescribir la IP del servidor antiguo en registros A y dentro del SPF.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.hestia_import import build_dns_proposal, _is_spf, _rewrite_spf_ip


def _zone():
    return {
        "domain": "ejemplo.es",
        "ip": "185.104.188.34",  # IP del servidor ANTIGUO
        "ttl": "14400",
        "_records": [
            {"TYPE": "NS", "RECORD": "@", "VALUE": "nshcp1.viejo.red.", "TTL": "14400"},
            {"TYPE": "NS", "RECORD": "@", "VALUE": "nshcp2.viejo.red.", "TTL": "14400"},
            {"TYPE": "A", "RECORD": "@", "VALUE": "185.104.188.34", "TTL": "14400"},
            {"TYPE": "A", "RECORD": "externo", "VALUE": "8.8.8.8", "TTL": "14400"},
            {"TYPE": "TXT", "RECORD": "@",
             "VALUE": '"v=spf1 a mx ip4:185.104.188.34 -all"', "TTL": "14400"},
        ],
    }


def test_propuesta_anade_ns_del_panel_y_descarta_los_del_backup():
    prop = build_dns_proposal(_zone(), "185.104.188.71", None, "185.104.188.34",
                              panel_ns=["nssvq1.svqhost.red", "nssvq2.svqhost.red"])
    adds = [p for p in prop if p["action"] == "add" and p["type"] == "NS"]
    disc = [p for p in prop if p["action"] == "discard" and p["type"] == "NS"]
    assert {p["content"] for p in adds} == {"nssvq1.svqhost.red.", "nssvq2.svqhost.red."}
    assert {p["content"] for p in disc} == {"nshcp1.viejo.red.", "nshcp2.viejo.red."}


def test_reescribe_ip_en_A_pero_respeta_ips_externas():
    prop = build_dns_proposal(_zone(), "185.104.188.71", None, "185.104.188.34")
    a_main = next(p for p in prop if p["type"] == "A" and p["name"] == "@")
    a_ext = next(p for p in prop if p["type"] == "A" and p["name"] == "externo")
    assert a_main["action"] == "rewrite" and a_main["new_content"] == "185.104.188.71"
    assert a_ext["action"] == "keep" and a_ext["content"] == "8.8.8.8"


def test_reescribe_la_ip_dentro_del_spf():
    prop = build_dns_proposal(_zone(), "185.104.188.71", None, "185.104.188.34")
    spf = next(p for p in prop if p["type"] == "TXT")
    assert spf["action"] == "rewrite"
    assert "ip4:185.104.188.71" in spf["new_content"]
    assert "185.104.188.34" not in spf["new_content"]


def test_rewrite_spf_conserva_mascara_y_resto():
    out = _rewrite_spf_ip('"v=spf1 ip4:1.2.3.4/24 include:x.com -all"',
                          "1.2.3.4", "9.9.9.9", None)
    assert "ip4:9.9.9.9/24" in out
    assert "include:x.com" in out


def test_is_spf():
    assert _is_spf('"v=spf1 -all"')
    assert _is_spf("v=spf1 a mx ~all")
    assert not _is_spf('"google-site-verification=abc"')
