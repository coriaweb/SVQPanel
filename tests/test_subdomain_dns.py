"""
Detección y tratamiento de SUBDOMINIOS en DNS: un subdominio cuya zona padre
está en el panel debe colgarse de esa zona (registro A/AAAA), no crear zona propia.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.routes.dns import subdomain_label


def test_subdomain_label_un_nivel():
    assert subdomain_label("gestion.zococoria.es", "zococoria.es") == "gestion"


def test_subdomain_label_varios_niveles():
    assert subdomain_label("a.b.zococoria.es", "zococoria.es") == "a.b"


def test_subdomain_label_mismo_dominio_es_arroba():
    assert subdomain_label("zococoria.es", "zococoria.es") == "@"


def test_subdomain_label_sin_relacion_devuelve_fqdn():
    # Si no es sufijo, devuelve el fqdn tal cual (no debería pasar en uso real).
    assert subdomain_label("otro.com", "zococoria.es") == "otro.com"
