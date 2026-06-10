"""
Tests del catálogo de geo-bloqueo (países).

Funciones puras: generan la URL de descarga de la zona del país y el nombre de la
lista IP. El catálogo se ordena alfabéticamente y bloquea códigos inválidos.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.utils.country_blocklist import (
    country_url, list_name_for, is_valid_cc, catalog,
)


def test_country_url_formato():
    url = country_url("ES")
    assert url.endswith("es-aggregated.zone")
    assert "ipdeny.com" in url
    # Debe usar minúsculas aunque entre en mayúsculas
    assert "ES" not in url


def test_list_name_for():
    assert list_name_for("ES") == "geo_es"
    assert list_name_for("LT") == "geo_lt"


def test_is_valid_cc():
    # is_valid_cc = "está en el catálogo de países BLOQUEABLES" (lista curada de
    # riesgo), no "es un código de país válido". Normaliza a minúsculas.
    assert is_valid_cc("lt")      # Lituania (la que faltaba y se añadió)
    assert is_valid_cc("cn")
    assert is_valid_cc("CN")      # normaliza mayúsculas → sí está en el catálogo
    assert not is_valid_cc("es")  # España NO se bloquea (no está en el catálogo)
    assert not is_valid_cc("zz")  # código inexistente
    assert not is_valid_cc("")


def test_catalogo_ordenado_alfabeticamente():
    cat = catalog()
    nombres = [c["name"] for c in cat]
    assert nombres == sorted(nombres, key=lambda n: n.lower()), \
        "el catálogo debe estar ordenado alfabéticamente por nombre"


def test_catalogo_incluye_lituania():
    cat = catalog()
    assert any(c["cc"] == "lt" for c in cat), "Lituania debe estar en el catálogo"


def test_catalogo_cada_pais_tiene_url_y_lista():
    cat = catalog()
    for c in cat[:5]:
        assert c.get("url", "").endswith(".zone")
        assert c.get("list_name", "").startswith("geo_")
