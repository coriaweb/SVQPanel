"""
Tests de la decisión de sincronización de registros AAAA al activar/desactivar
IPv6 en un dominio (api.routes.dns.compute_aaaa_changes).

Función PURA: dada la lista de registros existentes y la IPv6 (o None), decide
qué AAAA crear/actualizar (upsert) y cuáles borrar. No toca BD ni BIND.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.routes.dns import compute_aaaa_changes, build_spf, apply_ip6_to_spf


def _rec(t, name, content=""):
    return {"record_type": t, "name": name, "content": content}


def test_activar_crea_aaaa_para_cada_A():
    # Plantilla típica: @ y mail son A; www/ftp son CNAME (no llevan AAAA propio)
    existing = [
        _rec("A", "@", "1.2.3.4"),
        _rec("A", "mail", "1.2.3.4"),
        _rec("CNAME", "www", "dom.com."),
    ]
    plan = compute_aaaa_changes(existing, "2001:db8::1")
    names = sorted(n for n, _ in plan["upsert"])
    assert names == ["@", "mail"], "AAAA solo para los nombres que son A"
    assert all(c == "2001:db8::1" for _, c in plan["upsert"])
    assert plan["delete_names"] == []


def test_activar_no_duplica_si_ya_existe_con_misma_ip():
    existing = [
        _rec("A", "@", "1.2.3.4"),
        _rec("AAAA", "@", "2001:db8::1"),
    ]
    plan = compute_aaaa_changes(existing, "2001:db8::1")
    assert plan["upsert"] == [], "no debe re-crear un AAAA idéntico"
    assert plan["delete_names"] == []


def test_cambio_de_ipv6_actualiza_el_aaaa():
    existing = [
        _rec("A", "@", "1.2.3.4"),
        _rec("AAAA", "@", "2001:db8::OLD"),
    ]
    plan = compute_aaaa_changes(existing, "2001:db8::NEW")
    assert plan["upsert"] == [("@", "2001:db8::NEW")]


def test_desactivar_borra_todos_los_aaaa():
    existing = [
        _rec("A", "@", "1.2.3.4"),
        _rec("AAAA", "@", "2001:db8::1"),
        _rec("AAAA", "mail", "2001:db8::1"),
    ]
    plan = compute_aaaa_changes(existing, None)
    assert plan["upsert"] == []
    assert plan["delete_names"] == ["@", "mail"]


def test_build_spf_con_ipv4_y_ipv6():
    spf = build_spf("1.2.3.4", "2001:db8::1")
    assert spf == "v=spf1 a mx ip4:1.2.3.4 ip6:2001:db8::1 -all"


def test_build_spf_solo_ipv4():
    assert build_spf("1.2.3.4", None) == "v=spf1 a mx ip4:1.2.3.4 -all"


def test_apply_ip6_anade_a_spf_existente():
    spf = "v=spf1 a mx ip4:1.2.3.4 -all"
    assert apply_ip6_to_spf(spf, "2001:db8::1") == "v=spf1 a mx ip4:1.2.3.4 ip6:2001:db8::1 -all"


def test_apply_ip6_quita_cuando_se_desactiva():
    spf = "v=spf1 a mx ip4:1.2.3.4 ip6:2001:db8::1 -all"
    assert apply_ip6_to_spf(spf, None) == "v=spf1 a mx ip4:1.2.3.4 -all"


def test_apply_ip6_idempotente_no_duplica():
    spf = "v=spf1 a mx ip4:1.2.3.4 ip6:2001:db8::1 -all"
    # Re-aplicar la misma IPv6 no debe duplicar el mecanismo
    assert apply_ip6_to_spf(spf, "2001:db8::1") == spf


def test_apply_ip6_actualiza_ipv6_distinta():
    spf = "v=spf1 a mx ip6:2001:db8::OLD -all"
    assert apply_ip6_to_spf(spf, "2001:db8::NEW") == "v=spf1 a mx ip6:2001:db8::NEW -all"


def test_apply_ip6_respeta_softfail_tilde_all():
    spf = "v=spf1 a mx ip4:1.2.3.4 ~all"
    assert apply_ip6_to_spf(spf, "2001:db8::1") == "v=spf1 a mx ip4:1.2.3.4 ip6:2001:db8::1 ~all"


def test_apply_ip6_no_toca_si_no_es_spf():
    assert apply_ip6_to_spf("v=DMARC1; p=quarantine", "2001:db8::1") == "v=DMARC1; p=quarantine"


def test_aaaa_huerfano_se_limpia_al_activar():
    # Un AAAA de un nombre que ya no tiene A debe eliminarse
    existing = [
        _rec("A", "@", "1.2.3.4"),
        _rec("AAAA", "@", "2001:db8::1"),
        _rec("AAAA", "viejo", "2001:db8::1"),
    ]
    plan = compute_aaaa_changes(existing, "2001:db8::1")
    assert plan["delete_names"] == ["viejo"]
    assert plan["upsert"] == []  # @ ya está correcto
