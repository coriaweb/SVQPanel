"""
Paridad entre el instalador de PHP del panel (scripts/php_manager.py) y el de
install.sh: una versión PHP instalada desde Configuración → PHP debe nacer con
las MISMAS extensiones que una instalada por install.sh. Estuvieron
desincronizados (al panel le faltaban gmp/apcu/redis) y este test lo impide.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import php_manager

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_extensiones_opcionales_en_sincronia_con_install():
    with open(os.path.join(_REPO, "install.sh"), encoding="utf-8") as f:
        install = f.read()
    m = re.search(r"for EXT in ([a-z0-9 ]+); do", install)
    assert m, "No se encontró el loop de extensiones PHP en install.sh"
    assert m.group(1).split() == php_manager.OPTIONAL_EXTENSIONS


def test_redis_entre_las_extensiones_del_panel():
    # phpredis es necesario para el Redis por dominio: toda versión PHP nueva
    # (8.6, 9.0…) instalada desde el panel debe traerlo.
    assert "redis" in php_manager.OPTIONAL_EXTENSIONS
