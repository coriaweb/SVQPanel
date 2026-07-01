"""
Test: cada pool de dominio nace con memory_limit por defecto (128M) explícito,
independiente del php.ini global. Un override del dominio para memory_limit gana
sobre el default. Así el consumo por sitio es contenido por defecto y solo lo
sube quien lo necesite (hasta el techo del global).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.php_ini_manager import _pool_content, DOMAIN_DEFAULT_OVERRIDES


def test_pool_lleva_memory_limit_por_defecto():
    content = _pool_content("ejemplo.com", "user1", overrides={})
    assert "php_admin_value[memory_limit] = 128M" in content, \
        "el pool debe nacer con memory_limit 128M explícito"


def test_override_del_dominio_gana_sobre_el_default():
    # Si el dominio pide 256M, ese valor manda (no el default 128M).
    content = _pool_content("tienda.com", "user1", overrides={"memory_limit": "256M"})
    assert "php_admin_value[memory_limit] = 256M" in content
    assert "php_admin_value[memory_limit] = 128M" not in content


def test_default_es_128():
    # Documenta la política: el default por dominio es 128M.
    assert DOMAIN_DEFAULT_OVERRIDES.get("memory_limit") == "128M"
