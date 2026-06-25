"""
El análisis de un backup Hestia debe extraer SOLO los .conf (config_only), no los
datos pesados (web data, dumps, buzones). Extraer un backup de varios GB síncrono
en el request provocaba un 504. La importación real (sin config_only) sí extrae todo.
"""
import os
import sys
import tarfile
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.hestia_import import HestiaBackup


def _make_backup(tmp: str) -> str:
    """Crea un .tar Hestia mínimo con un dato web pesado y un dump de BD."""
    root = os.path.join(tmp, "back")
    os.makedirs(os.path.join(root, "hestia"))
    os.makedirs(os.path.join(root, "web", "ejemplo.com"))
    os.makedirs(os.path.join(root, "db", "ejemplo_db"))
    with open(os.path.join(root, "user.conf"), "w") as f:
        f.write("CONTACT=test@x.com\nFNAME=Test\n")
    with open(os.path.join(root, "web", "ejemplo.com", "web.conf"), "w") as f:
        f.write("DOMAIN=ejemplo.com\nBACKEND=PHP-8_2\nSSL=yes\nLETSENCRYPT=yes\n")
    # dato pesado (simulado): debe omitirse en config_only
    with open(os.path.join(root, "web", "ejemplo.com", "domain_data.tar.gz"), "wb") as f:
        f.write(b"\0" * (2 * 1024 * 1024))
    with open(os.path.join(root, "db", "ejemplo_db", "db.conf"), "w") as f:
        f.write("DB=ejemplo_db\nDBUSER=ej_user\nTYPE=mysql\n")
    with open(os.path.join(root, "db", "ejemplo_db", "ejemplo_db.mysql.sql.gz"), "wb") as f:
        f.write(b"\0" * (1 * 1024 * 1024))
    tar_path = os.path.join(tmp, "bk.tar")
    with tarfile.open(tar_path, "w:gz") as t:
        t.add(root, arcname=".")
    return tar_path


def test_config_only_omite_datos_pero_detecta_su_existencia():
    with tempfile.TemporaryDirectory() as tmp:
        tar_path = _make_backup(tmp)
        with HestiaBackup(tar_path, config_only=True) as b:
            m = b.analyze()
            web = m["web"][0]
            dbo = m["db"][0]
            # El manifiesto SÍ sabe que hay datos (vía la lista del tar).
            assert web["has_data"] is True
            assert dbo["has_dump"] is True
            # Pero el dato pesado NO se extrajo a disco.
            heavy = os.path.join(b.root, "web", "ejemplo.com", "domain_data.tar.gz")
            assert not os.path.isfile(heavy)
            dump = os.path.join(b.root, "db", "ejemplo_db", "ejemplo_db.mysql.sql.gz")
            assert not os.path.isfile(dump)
            # La config pequeña SÍ se extrajo.
            assert os.path.isfile(os.path.join(b.root, "web", "ejemplo.com", "web.conf"))


def test_modo_normal_extrae_todo():
    """La importación real (sin config_only) extrae también los datos pesados."""
    with tempfile.TemporaryDirectory() as tmp:
        tar_path = _make_backup(tmp)
        with HestiaBackup(tar_path, config_only=False) as b:
            heavy = os.path.join(b.root, "web", "ejemplo.com", "domain_data.tar.gz")
            assert os.path.isfile(heavy)
            assert os.path.getsize(heavy) == 2 * 1024 * 1024
