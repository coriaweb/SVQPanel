"""
Firewall: los puertos cerrados y la allowlist de MySQL remoto deben sobrevivir
a cada `nft -f /etc/nftables.conf`, y las reglas custom / listas IP deben ir
ANTES del accept de los puertos base (update 0174, 0.274.0).
"""
import re
from pathlib import Path
from types import SimpleNamespace

from api.utils import nftables_helper as nft
from api.utils import ip_list_fetcher

ROOT = Path(__file__).resolve().parent.parent


def _install_nft_template() -> str:
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    m = re.search(r"cat > /etc/nftables.conf << 'NFTEOF'\n(.*?)\nNFTEOF", text, re.S)
    assert m, "no se encuentra la plantilla de nftables.conf en install.sh"
    return m.group(1)


# nftables.conf tal como lo dejaba install.sh hasta 0.273.0 (resumido).
OLD_CONF = """#!/usr/sbin/nft -f
table inet svqpanel {}
delete table inet svqpanel

table inet svqpanel {
    set whitelist_v4 { type ipv4_addr; flags interval; }
    set whitelist_v6 { type ipv6_addr; flags interval; }
    set f2b_v4 { type ipv4_addr; flags timeout; }
    set f2b_v6 { type ipv6_addr; flags timeout; }
    set base_tcp_ports {
        type inet_service
        flags interval
        elements = { 22, 80, 443, 25, 587, 465, 143, 993, 110, 995, 53, 8083 }
    }
    set base_udp_ports {
        type inet_service
        flags interval
        elements = { 443, 53, 8083 }
    }

    chain input {
        type filter hook input priority filter; policy drop;
        iif "lo" accept
        ct state { established, related } accept
        ip  saddr @f2b_v4 drop
        ip6 saddr @f2b_v6 drop
        ip  saddr @whitelist_v4 accept
        ip6 saddr @whitelist_v6 accept
        tcp dport @base_tcp_ports accept
        udp dport @base_udp_ports accept
    }
}

include "/etc/nftables/svqpanel-iplists.nft"
include "/etc/nftables/svqpanel-rules.nft"
"""


def _assert_new_layout(conf: str):
    def pos(s):
        i = conf.find(s)
        assert i >= 0, f"falta: {s}"
        return i
    # includes: ports y mysql DESPUÉS de la tabla (pisan los de fábrica)
    assert pos("delete table inet svqpanel") < pos('include "/etc/nftables/svqpanel-ports.nft"')
    assert pos("udp dport @base_udp_ports accept") < pos('include "/etc/nftables/svqpanel-ports.nft"')
    assert pos('include "/etc/nftables/svqpanel-ports.nft"') < pos('include "/etc/nftables/svqpanel-iplists.nft"')
    assert pos('include "/etc/nftables/svqpanel-mysql-remote.nft"') < pos('include "/etc/nftables/svqpanel-iplists.nft"')
    # svq_pre (custom) y svq_lists (listas IP) con jump tras la whitelist,
    # antes de los puertos base; svq_lists deja fuera el SMTP 25
    assert re.search(r"^\s*chain svq_pre \{", conf, re.M)
    assert re.search(r"^\s*chain svq_lists \{\n\s*tcp dport 25 return\n\s*\}", conf, re.M)
    assert (pos("ip6 saddr @whitelist_v6 accept") < pos("jump svq_pre")
            < pos("jump svq_lists") < pos("tcp dport @base_tcp_ports accept"))
    assert re.search(r"^\s*set mysql_remote_allow \{", conf, re.M)
    assert "tcp dport 3306 ip saddr @mysql_remote_allow accept" in conf


def test_install_template_layout():
    _assert_new_layout(_install_nft_template())


def test_install_creates_new_include_files():
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert ": > /etc/nftables/svqpanel-ports.nft" in text
    assert ": > /etc/nftables/svqpanel-mysql-remote.nft" in text


def test_patch_old_conf():
    new, changes = nft.patch_main_conf(OLD_CONF)
    assert new is not None, changes
    _assert_new_layout(new)
    assert len(changes) == 8


def test_patch_conf_with_only_svq_pre():
    """Un conf a medio migrar (con svq_pre pero sin svq_lists) se completa."""
    half, _ = nft.patch_main_conf(OLD_CONF)
    half = half.replace("    chain svq_lists {\n        tcp dport 25 return\n    }\n", "")
    half = half.replace("        jump svq_lists\n", "")
    assert "svq_lists" not in half
    new, changes = nft.patch_main_conf(half)
    _assert_new_layout(new)
    assert changes == ["jump svq_lists", "chain svq_lists (con el 25 exento)"]


def test_patch_is_idempotent():
    new, _ = nft.patch_main_conf(OLD_CONF)
    again, changes = nft.patch_main_conf(new)
    assert again == new and changes == []
    # La plantilla nueva ya no necesita nada
    tpl = _install_nft_template()
    out, changes = nft.patch_main_conf(tpl)
    assert out == tpl and changes == []


def test_patch_refuses_unknown_conf():
    new, why = nft.patch_main_conf("table inet filter {\n chain input {\n }\n}\n")
    assert new is None and why


def test_move_rules_to_pre_chain():
    txt = ("add element inet svqpanel whitelist_v4 { 1.2.3.4 }\n"
           "add rule inet svqpanel input ip saddr @x drop\n")
    out = nft.move_rules_to_chain(txt, "svq_lists")
    assert "add rule inet svqpanel svq_lists ip saddr @x drop" in out
    assert "whitelist_v4 { 1.2.3.4 }" in out
    assert nft.move_rules_to_chain(out, "svq_lists") == out


def _rule(**kw):
    base = dict(id=1, action="deny", protocol="tcp", port_range="22", source_ip="10.0.0.0/8",
                description=None, is_whitelist=False, priority=100, is_active=True)
    base.update(kw)
    return SimpleNamespace(**base)


def test_rules_go_to_pre_chain():
    out = nft.render_rules_nft([_rule()], chain="svq_pre")
    assert "add rule inet svqpanel svq_pre ip saddr 10.0.0.0/8 tcp dport 22 drop" in out
    assert "svqpanel input" not in out


def test_block_everything_rule_is_skipped():
    out = nft.render_rules_nft(
        [_rule(id=7, protocol="any", port_range=None, source_ip=None)], chain="svq_pre")
    assert "add rule" not in out
    assert "#7 ignorada" in out
    # Un deny de un puerto concreto sin origen sí se genera
    out = nft.render_rules_nft([_rule(source_ip=None)], chain="svq_pre")
    assert "add rule inet svqpanel svq_pre tcp dport 22 drop" in out


def test_iplists_go_to_lists_chain():
    il = SimpleNamespace(id=3, name="geo_cn", enabled=True, action="block",
                         address_family="both")
    out = ip_list_fetcher.regenerate_iplists_nft([(il, ["1.2.3.0/24"], ["2001:db8::/32"])],
                                                 chain="svq_lists")
    rules = [l for l in out.splitlines() if l.startswith("add rule")]
    assert len(rules) == 2 and all(" svq_lists " in l for l in rules)


def test_chain_fallback_to_input_on_old_conf(tmp_path, monkeypatch):
    conf = tmp_path / "nftables.conf"
    conf.write_text(OLD_CONF)
    monkeypatch.setattr(nft, "NFT_MAIN_CONF", str(conf))
    assert nft.pre_chain() == "input" and nft.lists_chain() == "input"
    conf.write_text(nft.patch_main_conf(OLD_CONF)[0])
    assert nft.pre_chain() == "svq_pre" and nft.lists_chain() == "svq_lists"


def test_render_ports_nft():
    out = nft.render_ports_nft(["22", "80", "443"], ["443"])
    assert "flush set inet svqpanel base_tcp_ports" in out
    assert "add element inet svqpanel base_tcp_ports { 22, 80, 443 }" in out
    assert "add element inet svqpanel base_udp_ports { 443 }" in out
