"""
Test del precheck que evita que dos paneles gestionen el mismo dominio en el
mismo cluster DNS (zona duplicada en BIND). Se mockea el SSH remoto.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.dns_cluster import DNSCluster, DNSClusterError


def _cluster():
    c = DNSCluster(panel_id="panelAAA")
    return c


def test_precheck_rechaza_dominio_de_otro_panel(monkeypatch):
    c = _cluster()
    # El master "responde" que el dominio está en el panel panelBBB.
    monkeypatch.setattr(c, "_run_remote", lambda node, cmd, timeout=30: (0, "panelBBB\n", ""))
    with pytest.raises(DNSClusterError) as exc:
        c._check_zone_not_in_other_panel({"ssh_user": "root"}, "ejemplo.com", "")
    msg = str(exc.value)
    assert "ejemplo.com" in msg
    assert "panelBBB" in msg
    assert "otro panel" in msg.lower()


def test_precheck_permite_si_no_esta_en_otro_panel(monkeypatch):
    c = _cluster()
    # El master no encuentra el dominio en ningún otro panel (salida vacía).
    monkeypatch.setattr(c, "_run_remote", lambda node, cmd, timeout=30: (0, "", ""))
    # No debe lanzar.
    c._check_zone_not_in_other_panel({"ssh_user": "root"}, "ejemplo.com", "")


def test_precheck_excluye_el_propio_panel(monkeypatch):
    """El comando remoto debe excluir el panel_id propio (no autoconflicto)."""
    captured = {}
    c = _cluster()
    def fake_run(node, cmd, timeout=30):
        captured["cmd"] = cmd
        return (0, "", "")
    monkeypatch.setattr(c, "_run_remote", fake_run)
    c._check_zone_not_in_other_panel({"ssh_user": "root"}, "ejemplo.com", "")
    # El comando debe contener la exclusión del panel propio.
    assert 'panelAAA' in captured["cmd"]
    assert "continue" in captured["cmd"]  # salta el propio
