"""
Tests del helper de versión de Dovecot y de la generación de la línea passwd-file
(la quota usa un campo userdb distinto en 2.3 vs 2.4).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import dovecot_version as dv


def test_is_24_plus_con_varias_versiones(monkeypatch):
    casos = {
        (2, 3): False,
        (2, 4): True,
        (2, 5): True,
        (3, 0): True,
    }
    for ver, esperado in casos.items():
        monkeypatch.setattr(dv, "dovecot_version", lambda v=ver: v)
        assert dv.is_dovecot_24_plus() is esperado, f"{ver} → {esperado}"


def test_version_fallback_es_23_si_no_detecta(monkeypatch):
    # Si `dovecot --version` no existe/falla, asume 2.3 (sintaxis histórica).
    def _boom(*a, **k):
        raise FileNotFoundError("no dovecot")
    monkeypatch.setattr(dv.subprocess, "run", _boom)
    assert dv.dovecot_version() == (2, 3)
    assert dv.is_dovecot_24_plus() is False


def test_quota_userdb_field_segun_version(monkeypatch):
    """El campo de quota del passwd-file cambia entre 2.3 y 2.4:
    userdb_quota_rule (2.3) vs userdb_quota_storage_size (2.4)."""
    import scripts.mail_manager as mm

    # Evitar el require_root del __init__ y construir sin tocar el SO.
    mgr = mm.MailManager.__new__(mm.MailManager)

    monkeypatch.setattr(mm, "is_dovecot_24_plus", lambda: False)
    line_23 = mgr._dovecot_line(
        "user@dom.com", "{HASH}x", "panel", "dom.com", "user", 512)
    assert "userdb_quota_rule=*:storage=512M" in line_23

    monkeypatch.setattr(mm, "is_dovecot_24_plus", lambda: True)
    line_24 = mgr._dovecot_line(
        "user@dom.com", "{HASH}x", "panel", "dom.com", "user", 512)
    assert "userdb_quota_storage_size=512M" in line_24
    assert "userdb_quota_rule" not in line_24
