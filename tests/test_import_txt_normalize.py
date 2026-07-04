"""
Normalización de TXT importados de backups: los ficheros de zona traen los
TXT con comillas dentro del contenido, en trozos (claves DKIM largas) y con
puntos y coma escapados. Guardados así, los buscadores del panel sobre TXT
(LIKE 'v=spf1%', apply_ip6_to_spf, detector de SPF duplicado…) no los ven —
gotcha aparecido TRES veces en producción con zonas de Hestia.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.hestia_import import _normalize_txt_content


def test_quita_las_comillas_del_formato_de_zona():
    assert _normalize_txt_content('"v=spf1 a mx ip4:1.2.3.4 -all"') == \
        "v=spf1 a mx ip4:1.2.3.4 -all"


def test_concatena_trozos_de_claves_largas():
    # Un TXT >255 chars va en trozos que se concatenan (RFC 1035).
    assert _normalize_txt_content('"v=DKIM1; k=rsa; p=AAAA" "BBBB"') == \
        "v=DKIM1; k=rsa; p=AAAABBBB"


def test_desescapa_puntos_y_coma():
    assert _normalize_txt_content('"v=DKIM1\\; k=rsa\\; p=XYZ"') == \
        "v=DKIM1; k=rsa; p=XYZ"


def test_contenido_ya_limpio_no_cambia():
    limpio = "v=spf1 a mx ~all"
    assert _normalize_txt_content(limpio) == limpio


def test_vacio_no_revienta():
    assert _normalize_txt_content("") == ""
    assert _normalize_txt_content(None) == ""
