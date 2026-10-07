"""
Tests de los umbrales antispam por defecto del panel (rspamd_tuning).
No tocan el sistema; verifican constantes y generación de config.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import rspamd_tuning as rt


def test_defaults_estrictos_v0221():
    # Política v0.241.0: 3/4/6. El rechazo bajó de 10 a 6 (update 0149) porque
    # todo lo medido en la franja 6-10 era spam inequívoco y no debe ocupar la
    # carpeta de No deseado del cliente.
    assert rt.DEFAULT_ACTIONS["greylist"] == 3.0
    assert rt.DEFAULT_ACTIONS["add header"] == 4.0
    assert rt.DEFAULT_ACTIONS["reject"] == 6.0


def test_defaults_mantienen_escalera():
    # La escalera greylist < marcar < rechazar debe conservarse: si "marcar"
    # baja al nivel del greylist, la banda de greylist desaparece.
    a = rt.DEFAULT_ACTIONS
    assert a["greylist"] < a["add header"] < a["reject"]


def test_defaults_dentro_de_limites():
    for key, val in rt.DEFAULT_ACTIONS.items():
        lo, hi = rt.ACTION_BOUNDS[key]
        assert lo <= val <= hi, f"{key}={val} fuera de [{lo},{hi}]"


def test_build_actions_formato():
    # Formato que espera Rspamd en local.d/actions.conf (sin envolver en
    # actions{}) y que install.sh replica en su heredoc.
    out = rt._build_actions(dict(rt.DEFAULT_ACTIONS))
    assert '"greylist" = 3.00;' in out
    # add_header (como el actions.conf de fábrica), no "add header": con la
    # forma con espacio Rspamd veía las dos claves y avisaba en cada arranque.
    assert '"add_header" = 4.00;' in out
    assert '"add header"' not in out
    assert '"reject" = 6.00;' in out
    assert "actions {" not in out


def test_get_actions_lee_ambas_formas(tmp_path, monkeypatch):
    for content in ('"greylist" = 2.00;\n"add header" = 5.50;\n"reject" = 9.00;\n',
                    '"greylist" = 2.00;\n"add_header" = 5.50;\n"reject" = 9.00;\n',
                    'greylist = 2;\nadd_header = 5.5;\nreject = 9;\n'):
        f = tmp_path / "actions.conf"
        f.write_text(content)
        monkeypatch.setattr(rt, "ACTIONS_FILE", str(f))
        assert rt.get_actions() == {"greylist": 2.0, "add header": 5.5, "reject": 9.0}


def test_install_sh_usa_add_header():
    # install.sh replica _build_actions en un heredoc: deben coincidir.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "install.sh"), encoding="utf-8") as fh:
        txt = fh.read()
    assert '"add_header" = 4.00;' in txt
    assert '"add header" = 4.00;' not in txt
