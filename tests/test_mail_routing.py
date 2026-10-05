"""
Enrutado del correo local / remoto (scripts/mail_manager.py: set_mail_routing).

"Remoto" = el correo del dominio está fuera (Google, M365…). Postfix NO debe
tratarlo como local: fuera de virtual_domains y sin sus alias (que se apartan,
no se borran). Lo crítico es que:
  - nada vuelva a meter el dominio en los mapas mientras está en remoto
    (crear un alias, un reenvío, el catch-all…), y
  - al volver a local todo quede EXACTAMENTE como estaba.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.mail_manager import MailManager


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    """MailManager sin root, escribiendo en un directorio temporal."""
    import scripts.base
    monkeypatch.setattr(scripts.base.SystemManager, "__init__",
                        lambda self, *a, **k: None, raising=False)
    m = MailManager()
    m.POSTFIX_DIR = str(tmp_path)
    monkeypatch.setattr(m, "execute_command", lambda *a, **k: (0, "", ""), raising=False)
    monkeypatch.setattr(m, "_reload_postfix", lambda: None)
    monkeypatch.setattr(m, "sync_srs_excludes", lambda: None)
    m._write_map("virtual_domains", {"web.com": "OK", "otro.com": "OK"})
    m._write_map("virtual_alias", {
        "info@web.com": "jefe@gmail.com",
        "@web.com": "todo@web.com",
        "ventas@otro.com": "x@otro.com",
    })
    return m


def test_remoto_saca_el_dominio_y_aparta_sus_alias(mgr):
    res = mgr.set_mail_routing("web.com", "remote")
    assert res["aliases_moved"] == 2
    assert "web.com" not in mgr._read_map("virtual_domains")
    assert "otro.com" in mgr._read_map("virtual_domains")
    assert mgr._read_map("virtual_alias") == {"ventas@otro.com": "x@otro.com"}
    assert mgr._read_map(mgr.PARKED_ALIAS_MAP) == {
        "info@web.com": "jefe@gmail.com", "@web.com": "todo@web.com"}
    assert mgr.get_mail_routing("web.com") == "remote"
    assert mgr.get_mail_routing("otro.com") == "local"


def test_volver_a_local_lo_deja_igual(mgr):
    antes_alias = mgr._read_map("virtual_alias")
    antes_dom = mgr._read_map("virtual_domains")
    mgr.set_mail_routing("web.com", "remote")
    mgr.set_mail_routing("web.com", "local")
    assert mgr._read_map("virtual_alias") == antes_alias
    assert mgr._read_map("virtual_domains") == antes_dom
    assert mgr._read_map(mgr.PARKED_ALIAS_MAP) == {}
    assert mgr.get_mail_routing("web.com") == "local"


def test_idempotente(mgr):
    mgr.set_mail_routing("web.com", "remote")
    mgr.set_mail_routing("web.com", "remote")
    assert len(mgr._read_map(mgr.PARKED_ALIAS_MAP)) == 2
    mgr.set_mail_routing("web.com", "local")
    mgr.set_mail_routing("web.com", "local")
    assert len(mgr._read_map("virtual_alias")) == 3


def test_en_remoto_un_alias_nuevo_se_aparta(mgr):
    """Crear un alias/reenvío en remoto NO debe reactivar la entrega local."""
    mgr.set_mail_routing("web.com", "remote")
    mgr.create_alias("web.com", "nuevo", "alguien@gmail.com")
    mgr.set_forward("web.com", "info", ["otro@gmail.com"], keep_copy=False)
    assert not any(k.endswith("@web.com") for k in mgr._read_map("virtual_alias"))
    parked = mgr._read_map(mgr.PARKED_ALIAS_MAP)
    assert parked["nuevo@web.com"] == "alguien@gmail.com"
    assert parked["info@web.com"] == "otro@gmail.com"
    # Y al volver a local se aplican.
    mgr.set_mail_routing("web.com", "local")
    assert mgr._read_map("virtual_alias")["nuevo@web.com"] == "alguien@gmail.com"


def test_en_remoto_borrar_alias_lo_quita_de_los_apartados(mgr):
    mgr.set_mail_routing("web.com", "remote")
    mgr.delete_alias("web.com", "info")
    mgr.remove_catch_all("web.com")
    assert mgr._read_map(mgr.PARKED_ALIAS_MAP) == {}
    mgr.set_mail_routing("web.com", "local")
    assert not any(k.endswith("@web.com") for k in mgr._read_map("virtual_alias"))


def test_en_remoto_no_se_reintroduce_en_virtual_domains(mgr):
    mgr.set_mail_routing("web.com", "remote")
    mgr._map_set("virtual_domains", "web.com", "OK")
    assert "web.com" not in mgr._read_map("virtual_domains")


def test_borrar_el_dominio_limpia_la_marca_de_remoto(mgr, tmp_path, monkeypatch):
    monkeypatch.setattr(mgr, "_reload_dovecot", lambda: None)
    monkeypatch.setattr(mgr, "_dovecot_remove_by_domain", lambda d: None)
    mgr.set_mail_routing("web.com", "remote")
    mgr.delete_mail_domain("web.com", "usuario")
    assert mgr._read_map(mgr.REMOTE_DOMAINS_MAP) == {}
    assert mgr._read_map(mgr.PARKED_ALIAS_MAP) == {}
    # Si se vuelve a crear, nace en local.
    monkeypatch.setattr(mgr, "_tag_mail_project", lambda *a: None)
    monkeypatch.setattr("os.makedirs", lambda *a, **k: None)
    mgr.create_mail_domain("web.com", "usuario")
    assert "web.com" in mgr._read_map("virtual_domains")


def test_modo_invalido(mgr):
    with pytest.raises(ValueError):
        mgr.set_mail_routing("web.com", "fuera")
