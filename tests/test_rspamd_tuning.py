"""
Tests de los umbrales antispam por defecto del panel (rspamd_tuning).
No tocan el sistema; verifican constantes y generación de config.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import rspamd_tuning as rt


def test_defaults_estrictos_v0221():
    # Política v0.221.0: 3/4/10 (más estricto que el 4/6/15 de fábrica).
    assert rt.DEFAULT_ACTIONS["greylist"] == 3.0
    assert rt.DEFAULT_ACTIONS["add header"] == 4.0
    assert rt.DEFAULT_ACTIONS["reject"] == 10.0


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
    assert '"add header" = 4.00;' in out
    assert '"reject" = 10.00;' in out
    assert "actions {" not in out
