"""
Migración instantánea: al terminar la importación desde un Hestia por SSH, los
registros A que apuntan a la IP vieja pasan a la de este servidor (TTL corto) y
se comprueba en los NS del clúster. Si los esclavos tienen una versión de zona
por encima del maestro (caso real empanadaspineda.es) se sube y se reenvía.
"""
import json
import os
import subprocess
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.routes import migrations as mig

OLD, NEW = "185.104.188.41", "185.104.188.223"


def _zone(records):
    return {"domain": "ejemplo.es", "ip": OLD, "_records": records}


def test_origin_ips_zonas_y_host_ssh():
    manifest = {"dns": [{"domain": "a.es", "ip": "1.1.1.1"}, {"domain": "b.es", "ip": ""}]}
    assert mig._origin_ips(manifest, {"host": " 2.2.2.2 "}) == {"1.1.1.1", "2.2.2.2"}
    # Un nombre de host no se añade (no se resuelve).
    assert mig._origin_ips(manifest, {"host": "hestia.ejemplo.es"}) == {"1.1.1.1"}
    assert mig._origin_ips({}, None) == set()


def test_plan_solo_cambia_a_que_apuntan_al_origen():
    z = _zone([
        {"RECORD": "@", "TYPE": "A", "VALUE": OLD},
        {"RECORD": "www", "TYPE": "A", "VALUE": OLD},
        {"RECORD": "tienda", "TYPE": "A", "VALUE": "9.9.9.9"},     # externo: no se toca
        {"RECORD": "@", "TYPE": "MX", "VALUE": "mail.ejemplo.es"},
        {"RECORD": "@", "TYPE": "TXT", "VALUE": f"v=spf1 ip4:{OLD} -all"},
    ])
    plan = mig.instant_dns_plan([z], {OLD}, NEW, None)
    assert plan == [{"domain": "ejemplo.es", "warnings": [], "changes": [
        {"record": "@", "type": "A", "old": OLD, "new": NEW},
        {"record": "www", "type": "A", "old": OLD, "new": NEW},
    ]}]


def test_plan_aaaa_con_y_sin_ipv6():
    z = _zone([
        {"RECORD": "@", "TYPE": "A", "VALUE": OLD},
        {"RECORD": "@", "TYPE": "AAAA", "VALUE": "2a01::41"},
        {"RECORD": "otro", "TYPE": "AAAA", "VALUE": "2a01::99"},   # sin A al origen: no se toca
    ])
    con = mig.instant_dns_plan([z], {OLD}, NEW, "2a01::223")[0]
    assert {"record": "@", "type": "AAAA", "old": "2a01::41", "new": "2a01::223"} in con["changes"]
    assert len(con["changes"]) == 2 and not con["warnings"]
    sin = mig.instant_dns_plan([z], {OLD}, NEW, None)[0]
    assert len(sin["changes"]) == 1 and "IPv6" in sin["warnings"][0]


def test_fqdn():
    assert mig._fqdn("@", "e.es") == "e.es"
    assert mig._fqdn("www", "e.es") == "www.e.es"


# ── instant_dns_switch con SSH y dig simulados ──────────────────────────────

RECORDS = {
    "1": {"RECORD": "@", "TYPE": "A", "VALUE": OLD},
    "2": {"RECORD": "www", "TYPE": "A", "VALUE": OLD},
    "3": {"RECORD": "@", "TYPE": "NS", "VALUE": "ns1.hcp.es."},
    "4": {"RECORD": "@", "TYPE": "NS", "VALUE": "ns2.hcp.es."},
    "5": {"RECORD": "@", "TYPE": "MX", "VALUE": "mail.ejemplo.es", "PRIORITY": "10"},
}


class _FakeSession:
    def __init__(self, cfg):
        self.hestia_user = "cliente"

    def ssh(self, cmd):
        return cmd, {}

    def close(self):
        pass


def _setup(monkeypatch, *, ns_answer, serials=None, local_serial="2026102605"):
    """ns_answer(ns, name, rtype, state) → lista de respuestas de dig @ns."""
    state = {"cmds": [], "fixed": False}

    def fake_run(cmd, **kw):
        state["cmds"].append(cmd)
        out = ""
        if "v-list-dns-records" in cmd:
            out = json.dumps(RECORDS)
        elif "v-list-dns-domain" in cmd:
            out = json.dumps({"ejemplo.es": {"DNSSEC": "no", "SERIAL": local_serial}})
        elif "v-rebuild-dns-domain" in cmd:
            state["fixed"] = True
        return SimpleNamespace(returncode=0, stdout=out, stderr="")

    def fake_dig(name, rtype, server=None):
        if server is None:
            return ["ns1.hcp.es", "ns2.hcp.es"] if rtype == "NS" else []
        if rtype == "SOA":
            return f"ns1.hcp.es. root.ejemplo.es. {(serials or {}).get(server, local_serial)} 7200 3600 1209600 180".split()
        return ns_answer(server, name, rtype, state)

    monkeypatch.setattr(mig, "_SshSession", _FakeSession)
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(mig, "_dig", fake_dig)
    monkeypatch.setattr(mig.time, "sleep", lambda s: None)
    return state


def test_switch_cambia_y_verifica(monkeypatch):
    state = _setup(monkeypatch, ns_answer=lambda ns, n, t, st: [NEW])
    [res] = mig.instant_dns_switch({}, ["ejemplo.es"], {OLD}, NEW)
    assert res["error"] is None and res["verified"] is True
    assert [c["record"] for c in res["changed"]] == ["@", "www"]
    change = next(c for c in state["cmds"] if "v-change-dns-record" in c)
    assert change.count("v-change-dns-record") == 2
    assert f"{NEW} '' yes 300" in change            # TTL corto
    assert "MX" not in change                        # el correo no se toca
    assert not state["fixed"]


def test_switch_sube_serial_si_esclavo_por_encima(monkeypatch):
    # Los NS responden la IP vieja hasta que se reenvía la zona con serial mayor.
    ans = lambda ns, n, t, st: [NEW] if st["fixed"] else [OLD]
    state = _setup(monkeypatch, ns_answer=ans,
                   serials={"ns1.hcp.es": "2026102609", "ns2.hcp.es": "2026102609"})
    [res] = mig.instant_dns_switch({}, ["ejemplo.es"], {OLD}, NEW)
    assert res["verified"] is True and state["fixed"]
    fix = next(c for c in state["cmds"] if "v-rebuild-dns-domain" in c)
    assert "SERIAL='2026102610'" in fix
    assert any("2026102609" in w for w in res["warnings"])


def test_switch_sin_verificar_avisa(monkeypatch):
    _setup(monkeypatch, ns_answer=lambda ns, n, t, st: [OLD])
    [res] = mig.instant_dns_switch({}, ["ejemplo.es"], {OLD}, NEW)
    assert res["verified"] is False and res["changed"]
    assert any("aún no responden" in w for w in res["warnings"])


def test_switch_nada_que_cambiar(monkeypatch):
    state = _setup(monkeypatch, ns_answer=lambda ns, n, t, st: [NEW])
    [res] = mig.instant_dns_switch({}, ["ejemplo.es"], {"1.2.3.4"}, NEW)
    assert res["changed"] == [] and res["verified"] is True
    assert not any("v-change-dns-record" in c for c in state["cmds"])


def test_switch_ns_publicos_ajenos_avisa(monkeypatch):
    _setup(monkeypatch, ns_answer=lambda ns, n, t, st: [NEW])
    monkeypatch.setattr(mig, "_dig", lambda name, rtype, server=None:
                        ["ns.cloudflare.com"] if (rtype == "NS" and server is None) else [NEW])
    [res] = mig.instant_dns_switch({}, ["ejemplo.es"], {OLD}, NEW)
    assert any("no usa el DNS del Hestia" in w for w in res["warnings"])
