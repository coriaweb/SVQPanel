"""Los emails de alerta dicen de qué servidor vienen (hay varios)."""
from types import SimpleNamespace

from scripts import alerts_manager as A


def test_asunto_y_cuerpo_con_el_servidor(monkeypatch):
    import scripts.panel_ssl_manager as P
    monkeypatch.setattr(P, "_detect_panel_web_port", lambda: 8083)
    s = SimpleNamespace(panel_hostname="svqhostpanel.svqhost.red", server_ipv4="185.104.188.71")
    subj, body = A.tag_with_server("[SVQPanel] ⚠ Carga alta: load_5=6.36", "Alerta de monitorización…", s)
    assert subj == "[SVQPanel · svqhostpanel] ⚠ Carga alta: load_5=6.36"
    assert "Servidor: svqhostpanel.svqhost.red" in body and "IP: 185.104.188.71" in body
    assert "Panel: https://svqhostpanel.svqhost.red:8083" in body
    # Un asunto sin la etiqueta también la lleva
    assert A.tag_with_server("Prueba", "x", s)[0] == "[SVQPanel · svqhostpanel] Prueba"


def test_sin_hostname_del_panel(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getfqdn", lambda: "svq-beyuri1.svqhost.red")
    subj, body = A.tag_with_server("[SVQPanel] x", "y", SimpleNamespace(panel_hostname=None, server_ipv4=None))
    assert subj == "[SVQPanel · svq-beyuri1] x" and "Panel:" not in body
