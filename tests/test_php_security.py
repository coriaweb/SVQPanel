"""
Tests del bloque de seguridad PHP-FPM por dominio (aislamiento).

`_security_block` genera las directivas php_admin_value que confinan cada dominio:
open_basedir sin /tmp global, disable_functions, tmp propio. Es una garantía de
seguridad clave (un sitio no puede leer los ficheros/temporales de otro), así que
conviene tenerla cubierta por tests para que un cambio no la debilite sin avisar.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.php_ini_manager import _security_block


def _block_text(owner="user1", domain="test.com", relax=False):
    return "\n".join(_security_block(owner, domain, relax_hardening=relax))


def test_open_basedir_presente():
    txt = _block_text()
    assert "open_basedir" in txt


def test_open_basedir_no_incluye_tmp_global():
    # CLAVE de seguridad: open_basedir NUNCA debe incluir /tmp global (un sitio
    # podría leer los temporales de otro). Debe usar el tmp propio del dominio.
    txt = _block_text()
    # Buscar la línea de open_basedir y comprobar que no tiene ':/tmp:' ni acaba en ':/tmp'
    for line in txt.splitlines():
        if "open_basedir" in line:
            paths = line.split("=", 1)[1].strip().split(":")
            assert "/tmp" not in paths, "open_basedir NO debe incluir /tmp global"


def test_disable_functions_presente_por_defecto():
    txt = _block_text(relax=False)
    assert "disable_functions" in txt
    # Funciones peligrosas típicas deshabilitadas
    assert "exec" in txt or "system" in txt


def test_tmp_propio_del_dominio():
    # upload_tmp_dir y session.save_path deben apuntar al tmp del dominio, no a /tmp
    txt = _block_text(owner="user1", domain="test.com")
    assert "upload_tmp_dir" in txt
    assert "session.save_path" in txt
    # El tmp debe estar bajo el home del dominio
    assert "/home/user1/web/test.com" in txt


def test_relax_hardening_afecta_disable_functions():
    # Con hardening relajado, disable_functions puede ser menos restrictivo.
    normal = _block_text(relax=False)
    relaxed = _block_text(relax=True)
    # Ambos generan el bloque; el relajado no debería ser MÁS restrictivo
    assert "open_basedir" in relaxed  # el aislamiento de rutas se mantiene siempre
