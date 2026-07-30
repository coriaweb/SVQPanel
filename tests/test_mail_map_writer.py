"""
Integridad de los ficheros de configuración de correo que escribe el panel
(scripts/mail_manager.py: _write_map y _write_dovecot_users).

Ambos formatos son "una entrada por línea":
  - /etc/postfix/virtual_alias → «clave<TAB>valor»
  - /etc/dovecot/users         → campos separados por ':'

Un salto de línea en cualquier valor insertaría una entrada extra que el panel no
gestiona ni muestra (un alias arbitrario, o un buzón completo con su hash y su
home). Los schemas ya lo validan, pero no todos los caminos pasan por Pydantic
—el importador de Hestia construye los objetos directamente—, así que el escritor
tiene que protegerse solo.
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
    m.DOVECOT_USERS = str(tmp_path / "users")
    monkeypatch.setattr(m, "execute_command", lambda *a, **k: None, raising=False)
    return m


# ─────────────────────────── _write_map ─────────────────────────────────────

def test_escribe_entradas_normales(mgr):
    mgr._write_map("virtual_alias", {"info@e.com": "dest@e.com",
                                     "hola@e.com": "otro@e.com"})
    leido = mgr._read_map("virtual_alias")
    assert leido == {"info@e.com": "dest@e.com", "hola@e.com": "otro@e.com"}


def test_descarta_entrada_con_salto_de_linea_en_el_valor(mgr):
    """El caso de inyección: un \\n en el destino añadiría un alias extra."""
    mgr._write_map("virtual_alias", {
        "info@e.com": "dest@bueno.com\nvictima\tatacante@malo.com",
        "ok@e.com":   "legitimo@e.com",
    })
    leido = mgr._read_map("virtual_alias")
    assert "victima" not in leido, "se inyectó una entrada extra en el mapa"
    assert "info@e.com" not in leido, "la entrada peligrosa debe descartarse"
    assert leido == {"ok@e.com": "legitimo@e.com"}, "las buenas deben sobrevivir"


def test_descarta_entrada_con_salto_de_linea_en_la_clave(mgr):
    mgr._write_map("virtual_alias", {"a@e.com\nb@e.com": "d@e.com",
                                     "ok@e.com": "legitimo@e.com"})
    leido = mgr._read_map("virtual_alias")
    assert leido == {"ok@e.com": "legitimo@e.com"}


def test_descarta_retorno_de_carro(mgr):
    mgr._write_map("virtual_alias", {"a@e.com": "d@e.com\rx@y.com"})
    assert mgr._read_map("virtual_alias") == {}


def test_el_fichero_no_gana_lineas_inesperadas(mgr):
    """Comprobación directa sobre el fichero: nº de líneas de datos == entradas."""
    mgr._write_map("virtual_alias", {
        "uno@e.com": "a@e.com",
        "dos@e.com": "b@e.com\nINYECTADO\tx@y.com",
        "tres@e.com": "c@e.com",
    })
    with open(os.path.join(mgr.POSTFIX_DIR, "virtual_alias"), encoding="utf-8") as f:
        datos = [l for l in f.read().splitlines()
                 if l.strip() and not l.startswith("#")]
    assert len(datos) == 2                      # la peligrosa se descartó
    assert not any("INYECTADO" in l for l in datos)


def test_valor_none_no_rompe(mgr):
    mgr._write_map("virtual_alias", {"a@e.com": None})
    assert mgr._read_map("virtual_alias") == {"a@e.com": ""}


# ────────────────────── _write_dovecot_users ────────────────────────────────

def test_dovecot_escribe_lineas_normales(mgr):
    mgr._write_dovecot_users({
        "a@e.com": "a@e.com:{SHA512-CRYPT}xxx:5000:5000::/home/u/mail/e/a::",
        "b@e.com": "b@e.com:{SHA512-CRYPT}yyy:5000:5000::/home/u/mail/e/b::",
    })
    with open(mgr.DOVECOT_USERS, encoding="utf-8") as f:
        datos = [l for l in f.read().splitlines()
                 if l.strip() and not l.startswith("#")]
    assert len(datos) == 2


def test_dovecot_descarta_linea_con_salto(mgr):
    """Un \\n inyectaría un buzón entero, con su hash y su home."""
    mgr._write_dovecot_users({
        "a@e.com": "a@e.com:{SHA512-CRYPT}xxx:5000:5000::/home/u/mail/e/a::",
        "mal@e.com": ("mal@e.com:{X}h:5000:5000::/h::\n"
                      "intruso@e.com:{X}h:5000:5000::/home/otro::"),
    })
    with open(mgr.DOVECOT_USERS, encoding="utf-8") as f:
        contenido = f.read()
    assert "intruso@e.com" not in contenido, "se inyectó un buzón"
    datos = [l for l in contenido.splitlines()
             if l.strip() and not l.startswith("#")]
    assert len(datos) == 1
