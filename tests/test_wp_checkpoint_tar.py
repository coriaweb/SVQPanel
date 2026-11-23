"""
La actualización segura de WordPress fallaba con «No pude crear el checkpoint
de archivos: tar: ./wp-content: file changed as we read it». GNU tar sale con 1
cuando un fichero cambia mientras lo lee (cachés/logs de una web viva): es un
aviso y el .tar.gz es válido. Solo el 2+ es error real.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scripts.wp_staging as ws


def _fake_tar(rc):
    def fake(cmd, timeout=None, **kw):
        dest = cmd[cmd.index("-czf") + 1]
        if rc in (0, 1):
            open(dest, "wb").close()
        return rc, "", "tar: ./wp-content: file changed as we read it"
    return fake


def test_rc1_file_changed_es_valido(tmp_path):
    dest = str(tmp_path / "files.tar.gz")
    with patch.object(ws, "_run", _fake_tar(1)):
        ok, _err = ws._tar_docroot(str(tmp_path), dest)
    assert ok


def test_rc2_es_error(tmp_path):
    dest = str(tmp_path / "files.tar.gz")
    with patch.object(ws, "_run", _fake_tar(2)):
        ok, _err = ws._tar_docroot(str(tmp_path), dest)
    assert not ok


def test_rc0_sin_archivo_es_error(tmp_path):
    with patch.object(ws, "_run", lambda cmd, timeout=None, **kw: (0, "", "")):
        ok, _err = ws._tar_docroot(str(tmp_path), str(tmp_path / "x.tar.gz"))
    assert not ok
