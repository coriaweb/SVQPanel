"""
Tests del tuning de recursos del pool PHP-FPM por dominio (Fase 21).

Validan la resolución de presets, los caps del servidor (que un dominio no pueda
agotar la RAM del host) y la coherencia de directivas según el modo pm. Son
funciones puras: no tocan FPM ni la BD.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import php_ini_manager as p


def test_preset_por_defecto_es_medium():
    eff = p.resolve_fpm_tuning(None)
    assert eff["pm"] == "ondemand"
    assert eff["pm.max_children"] == 10


def test_preset_low_minima_ram():
    eff = p.resolve_fpm_tuning({"preset": "low"})
    assert eff["pm.max_children"] == 5
    assert eff["pm"] == "ondemand"


def test_preset_high_es_dynamic_con_spares():
    eff = p.resolve_fpm_tuning({"preset": "high"})
    assert eff["pm"] == "dynamic"
    # dynamic requiere las directivas *_servers
    assert "pm.start_servers" in eff
    assert "pm.min_spare_servers" in eff
    assert "pm.max_spare_servers" in eff
    # ondemand-only no debe colarse
    assert "pm.process_idle_timeout" not in eff


def test_preset_invalido_cae_a_medium():
    eff = p.resolve_fpm_tuning({"preset": "no-existe"})
    assert eff["pm.max_children"] == 10


def test_cap_max_children_no_supera_el_servidor():
    eff = p.resolve_fpm_tuning({"preset": "medium", "manual": {"pm.max_children": 9999}})
    assert eff["pm.max_children"] == p.FPM_MAX_CHILDREN_CAP


def test_cap_max_requests_no_supera_el_servidor():
    eff = p.resolve_fpm_tuning({"manual": {"pm.max_requests": 999999}})
    assert eff["pm.max_requests"] == p.FPM_MAX_REQUESTS_CAP


def test_dynamic_clampa_spares_a_max_children():
    # max_children=3 pero piden max_spare=20 → debe quedar <= max_children
    eff = p.resolve_fpm_tuning({"manual": {"pm": "dynamic", "pm.max_children": 3,
                                           "pm.max_spare_servers": 20}})
    assert eff["pm.max_spare_servers"] <= 3
    assert eff["pm.min_spare_servers"] <= eff["pm.max_spare_servers"]
    assert eff["pm.start_servers"] >= eff["pm.min_spare_servers"]
    assert eff["pm.start_servers"] <= eff["pm.max_spare_servers"]


def test_ondemand_quita_directivas_dynamic():
    eff = p.resolve_fpm_tuning({"manual": {"pm": "ondemand", "pm.start_servers": 4}})
    assert "pm.start_servers" not in eff
    assert eff["pm.process_idle_timeout"]  # ondemand sí lleva idle_timeout


def test_static_sin_idle_ni_spares():
    eff = p.resolve_fpm_tuning({"manual": {"pm": "static", "pm.max_children": 8}})
    assert eff["pm"] == "static"
    assert "pm.process_idle_timeout" not in eff
    assert "pm.start_servers" not in eff


# ── Validación ────────────────────────────────────────────────────────────────
def test_validate_acepta_preset_y_manual_correctos():
    ok, errors = p.validate_fpm_tuning({"preset": "high", "manual": {"pm.max_children": 20}})
    assert ok, errors


def test_validate_rechaza_preset_invalido():
    ok, errors = p.validate_fpm_tuning({"preset": "turbo"})
    assert not ok


def test_validate_rechaza_pm_desconocido():
    ok, errors = p.validate_fpm_tuning({"manual": {"pm": "magic"}})
    assert not ok


def test_validate_rechaza_negativos():
    ok, errors = p.validate_fpm_tuning({"manual": {"pm.max_children": -5}})
    assert not ok


def test_validate_rechaza_superar_cap():
    ok, errors = p.validate_fpm_tuning({"manual": {"pm.max_children": p.FPM_MAX_CHILDREN_CAP + 1}})
    assert not ok


def test_pool_content_incluye_pm_y_seguridad(monkeypatch):
    # _pool_content escribe a partir del tuning; comprobamos que mete pm.* y el
    # bloque de seguridad. Parcheamos utils para no depender del FS real.
    import scripts.php_ini_manager as mod
    monkeypatch.setattr(mod, "_security_block", lambda *a, **k: ["php_admin_value[open_basedir] = /x"])
    content = mod._pool_content("ejemplo.com", "user1", {"memory_limit": "256M"},
                                fpm_tuning={"preset": "high"})
    assert "pm = dynamic" in content
    assert "pm.max_children = 25" in content
    assert "php_admin_value[open_basedir]" in content
    assert "php_value[memory_limit] = 256M" not in content  # memory_limit es admin
    assert "php_admin_value[memory_limit] = 256M" in content
