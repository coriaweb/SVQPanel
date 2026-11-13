"""Carpeta destino de subcuentas SFTP: formas de escribir la ruta y etiqueta."""
import pytest

from scripts import sftp_account_manager as sam

WANT = "web/api.oskauto.com/private/sftp_clientes/inovpecas-sa"


@pytest.mark.parametrize("raw", [
    WANT,
    WANT + "/",
    "  " + WANT + "  ",
    "/home/oskarbiapi/" + WANT,
    "/" + WANT,                       # lo que enseña FileZilla (su raíz es el home)
    "oskarbiapi/" + WANT,             # Chrome autorrellenaba el usuario delante
    "~/" + WANT,
])
def test_normalize_subpath(raw):
    assert sam.normalize_subpath("oskarbiapi", raw) == WANT


def test_normalize_no_abre_salidas(tmp_path, monkeypatch):
    home = tmp_path / "home" / "u"
    (home / "web" / "d").mkdir(parents=True)
    monkeypatch.setattr(sam, "owner_home", lambda owner: str(home))
    # Una absoluta fuera del home pasa a ser relativa a él: nunca sale.
    assert sam.resolve_target("u", "/etc") == str((home / "etc").resolve())
    assert sam.resolve_target("u", "../../etc") is None
    assert sam.resolve_target("u", "/web/d") == str((home / "web" / "d").resolve())
    assert sam.resolve_target("u", "u/web/d") == str((home / "web" / "d").resolve())


def test_carpeta_llamada_como_el_usuario_se_respeta(tmp_path, monkeypatch):
    home = tmp_path / "home" / "u"
    (home / "u" / "x").mkdir(parents=True)
    monkeypatch.setattr(sam, "owner_home", lambda owner: str(home))
    assert sam.normalize_subpath("u", "u/x") == "u/x"


@pytest.mark.parametrize("label,ok", [
    ("inovpecas", True), ("inovpecas_sa", True), ("inovpecas-sa", False),
    ("1abc", False), ("a", False), ("a" * 17, False),
])
def test_label_re(label, ok):
    assert bool(sam.LABEL_RE.match(label)) is ok
