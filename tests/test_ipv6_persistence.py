"""
Tests de la persistencia de IPv6 vía systemd-networkd (drop-in) y del detector
de gateway IPv6. Funciones puras. Caza el bug que rompía la red al reiniciar:
el drop-in NO debe redefinir la interfaz (solo [Network] con Address=).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.ipv6_manager import build_dropin, _normalize_cidr


def test_dropin_es_aditivo_no_redefine_interfaz():
    out = build_dropin(["2001:678:ff4:163b::a/64"])
    # Debe ser un drop-in [Network] aditivo, NO un netplan que redefine eth0.
    assert "[Network]" in out
    assert "Address=2001:678:ff4:163b::a/64" in out
    # NO debe contener nada que redefina la interfaz (lo que rompía netplan).
    assert "ethernets" not in out
    assert "network:" not in out
    assert "eth0:" not in out


def test_dropin_varias_ips():
    out = build_dropin(["2001:db8::1/64", "2001:db8::2/64", "2001:db8::3/64"])
    assert out.count("Address=") == 3


def test_dropin_vacio():
    out = build_dropin([])
    assert "[Network]" in out
    assert "Address=" not in out


def test_normalize_cidr():
    assert _normalize_cidr("2001:0678:0FF4:163b::A/64") == "2001:678:ff4:163b::a/64"
    # Sin prefijo → asume /64
    assert _normalize_cidr("2001:db8::1") == "2001:db8::1/64"


def test_detect_gateway_del_netplan(tmp_path, monkeypatch):
    from scripts import ipv6_route_service as svc
    yaml = tmp_path / "01-svqpanel-net.yaml"
    yaml.write_text(
        'network:\n  version: 2\n  ethernets:\n    eth0:\n'
        '      routes:\n'
        '        - to: "0.0.0.0/0"\n          via: 185.104.188.254\n'
        '        - to: "::/0"\n          via: "2001:678:ff4:ffff::"\n          on-link: true\n'
    )
    monkeypatch.setattr(svc, "NETPLAN_MAIN", str(yaml))
    assert svc.detect_ipv6_gateway() == "2001:678:ff4:ffff::"


def test_detect_gateway_sin_ruta_ipv6(tmp_path, monkeypatch):
    from scripts import ipv6_route_service as svc
    yaml = tmp_path / "net.yaml"
    yaml.write_text('network:\n  ethernets:\n    eth0:\n      addresses: [1.2.3.4/24]\n')
    monkeypatch.setattr(svc, "NETPLAN_MAIN", str(yaml))
    assert svc.detect_ipv6_gateway() is None
