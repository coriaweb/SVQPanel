"""
Cabeceras de los correos que ENVÍA el panel (scripts/panel_mailer.py).

RFC 5322 §3.6: 'Date' y 'Message-ID' son cabeceras OBLIGATORIAS de un mensaje, y
la librería email de Python NO las añade sola. Sin ellas los filtros antispam
suman puntos (MISSING_DATE ~1.4, MISSING_MID ~2.5 en Rspamd/SpamAssassin), y
justamente estos son los correos que no pueden acabar en spam: alertas de cuota,
expiración de certificados, fallos de backup.

Lo que la librería SÍ hace por nosotros (y por tanto no hay que reimplementar):
plegar cabeceras largas, codificar el cuerpo respetando el límite de 998
caracteres por línea del §2.1.1, y rechazar cabeceras con saltos de línea.
"""
import os
import sys
import re

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.panel_mailer import _send


class _FakeSMTP:
    """Captura el mensaje en vez de enviarlo."""
    enviado = None

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port

    def ehlo(self): pass
    def starttls(self): pass
    def login(self, u, p): pass
    def quit(self): pass

    def sendmail(self, frm, to, msg):
        _FakeSMTP.enviado = msg


@pytest.fixture
def cfg():
    return {"host": "smtp.x.com", "port": 587, "security": "starttls",
            "username": "", "password": "",
            "from_email": "avisos@midominio.com", "from_name": "SVQPanel"}


@pytest.fixture(autouse=True)
def _fake_smtp(monkeypatch):
    import scripts.panel_mailer as pm
    _FakeSMTP.enviado = None
    monkeypatch.setattr(pm.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(pm.smtplib, "SMTP_SSL", _FakeSMTP)


def _cabeceras(raw):
    return raw.split("\n\n", 1)[0]


# ───────────────────── cabeceras obligatorias del RFC 5322 ──────────────────

def test_incluye_date(cfg):
    _send(cfg, "cliente@x.com", "Aviso", "cuerpo")
    assert re.search(r"^Date: .+", _cabeceras(_FakeSMTP.enviado), re.M), \
        "falta Date (MISSING_DATE ~1.4 puntos de spam)"


def test_incluye_message_id(cfg):
    _send(cfg, "cliente@x.com", "Aviso", "cuerpo")
    assert re.search(r"^Message-ID: <.+>", _cabeceras(_FakeSMTP.enviado), re.M), \
        "falta Message-ID (MISSING_MID ~2.5 puntos de spam)"


def test_message_id_usa_el_dominio_del_remitente(cfg):
    """Con el hostname local sería incoherente con el From y el SPF."""
    _send(cfg, "cliente@x.com", "Aviso", "cuerpo")
    mid = re.search(r"^Message-ID: <([^>]+)>", _cabeceras(_FakeSMTP.enviado), re.M)
    assert mid and mid.group(1).endswith("@midominio.com")


def test_message_id_es_unico_por_mensaje(cfg):
    _send(cfg, "a@x.com", "Uno", "c")
    primero = re.search(r"^Message-ID: <([^>]+)>", _FakeSMTP.enviado, re.M).group(1)
    _send(cfg, "b@x.com", "Dos", "c")
    segundo = re.search(r"^Message-ID: <([^>]+)>", _FakeSMTP.enviado, re.M).group(1)
    assert primero != segundo


def test_from_y_to_presentes(cfg):
    _send(cfg, "cliente@x.com", "Aviso", "cuerpo")
    h = _cabeceras(_FakeSMTP.enviado)
    assert "avisos@midominio.com" in h and "cliente@x.com" in h


def test_from_email_sin_arroba_no_rompe(cfg):
    """make_msgid con domain=None usa el hostname; no debe lanzar."""
    cfg["from_email"] = "raro-sin-arroba"
    _send(cfg, "cliente@x.com", "Aviso", "cuerpo")
    assert re.search(r"^Message-ID: <.+>", _FakeSMTP.enviado, re.M)


# ──────────── lo que la librería ya garantiza (documentado con test) ────────

def test_lineas_no_superan_el_limite_del_rfc(cfg):
    """§2.1.1: máx 998 caracteres por línea. El cuerpo se codifica en base64
    partido, así que un cuerpo con una línea larguísima sale conforme."""
    _send(cfg, "cliente@x.com", "Asunto " * 40, "X" * 5000)
    peor = max(len(l) for l in _FakeSMTP.enviado.split("\n"))
    assert peor <= 998, f"línea de {peor} caracteres, incumple el RFC 5322"


def test_salto_de_linea_en_el_asunto_no_inyecta_cabeceras(cfg):
    """Python lanza HeaderParseError en vez de escribir la cabecera inyectada.
    Se fija con un test para que un cambio de política de email no lo silencie."""
    from email.errors import HeaderParseError
    with pytest.raises((HeaderParseError, ValueError)):
        _send(cfg, "cliente@x.com", "Aviso\nBcc: atacante@malo.com", "cuerpo")
    assert _FakeSMTP.enviado is None, "no debe enviarse nada"


def test_utf8_en_asunto_y_cuerpo(cfg):
    _send(cfg, "cliente@x.com", "Certificado añadido ✅", "Tildes: ñáéíóú")
    assert _FakeSMTP.enviado is not None


def test_html_alternativo_se_adjunta(cfg):
    _send(cfg, "cliente@x.com", "Aviso", "texto", "<b>html</b>")
    assert "text/html" in _FakeSMTP.enviado
    assert "multipart/alternative" in _FakeSMTP.enviado
