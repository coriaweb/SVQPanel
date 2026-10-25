"""
"Optimizar wp-cron" fallaba con "Unable to locate placement anchor" en
wp-configs antiguos o editados a mano: wp-cli coloca las constantes nuevas antes
de la línea "/* That's all, stop editing! */" y, si no está, no sabe dónde.
Ahora se reintenta anclando justo tras "<?php" (probado con wp-cli real).
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scripts.wp_manager as wm

ANCHOR_ERR = (1, "", "Error: Could not process the 'wp-config.php' transformation.\n"
                     "Reason: Unable to locate placement anchor.")


def test_reintenta_con_anclaje_tras_php():
    llamadas = []

    def fake_wp(docroot, owner, args, timeout=300):
        llamadas.append(args)
        return ANCHOR_ERR if len(llamadas) == 1 else (0, "Success", "")

    with patch.object(wm, "_wp", side_effect=fake_wp):
        wm.wp_config_disable_cron("/w", "u", True)
    assert len(llamadas) == 2
    assert "--anchor=<?php" in llamadas[1] and "--placement=after" in llamadas[1]


def test_si_va_a_la_primera_no_reintenta():
    with patch.object(wm, "_wp", return_value=(0, "Success", "")) as wp:
        wm.wp_config_disable_cron("/w", "u", True)
    assert wp.call_count == 1


def test_otro_error_no_se_disfraza():
    # Un error distinto (permisos, wp-config ilegible) no debe reintentarse
    with patch.object(wm, "_wp", return_value=(1, "", "Error: permission denied")) as wp:
        try:
            wm.wp_config_disable_cron("/w", "u", True)
            raise AssertionError("debía fallar")
        except wm.WpError as e:
            assert "permission denied" in str(e)
    assert wp.call_count == 1


def test_endurecimiento_usa_el_mismo_respaldo():
    llamadas = []

    def fake_wp(docroot, owner, args, timeout=300):
        llamadas.append(args)
        if args[:2] == ["config", "set"] and not any(a.startswith("--anchor") for a in args):
            return ANCHOR_ERR
        return (0, "", "")

    with patch.object(wm, "_wp", side_effect=fake_wp):
        wm.wp_hardening_apply("/w", "u", ["disallow_file_edit"])
    assert any("DISALLOW_FILE_EDIT" in a and "--anchor=<?php" in a for a in llamadas)
