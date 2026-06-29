"""
Tests de safe_extract_tar: extracción en streaming de un .tar de Hestia.

Verifica que la extracción miembro a miembro (que evita cargar todos los
TarInfo en RAM → OOM con WordPress grandes) sigue cumpliendo el contrato:
- extrae los ficheros normales y devuelve TODOS los nombres del tar,
- aborta ante rutas que escapan del destino (path traversal),
- omite (sin abortar) symlinks que apuntan fuera del backup,
- en modo config_only NO extrae los datos pesados pero sí los reporta.
"""
import os
import sys
import io
import tarfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.hestia_import import safe_extract_tar, HestiaImportError


def _add_file(tar, name, data=b"x"):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


def _make_tar(path, builder):
    with tarfile.open(path, "w") as tar:
        builder(tar)
    return str(path)


def test_extrae_y_devuelve_todos_los_nombres(tmp_path):
    tar_path = _make_tar(tmp_path / "b.tar", lambda t: (
        _add_file(t, "hestia"),
        _add_file(t, "web/dom.com/public_html/index.php", b"<?php"),
        _add_file(t, "db/wp/wp.mysql.sql.gz", b"dump"),
    ))
    dest = tmp_path / "out"
    dest.mkdir()
    names = safe_extract_tar(tar_path, str(dest))
    # Devuelve TODOS los nombres del tar (los necesita el manifiesto).
    assert set(names) == {"hestia", "web/dom.com/public_html/index.php",
                          "db/wp/wp.mysql.sql.gz"}
    # Y los extrae de verdad.
    assert (dest / "web/dom.com/public_html/index.php").read_bytes() == b"<?php"
    assert (dest / "db/wp/wp.mysql.sql.gz").exists()


def test_config_only_omite_datos_pesados_pero_los_reporta(tmp_path):
    tar_path = _make_tar(tmp_path / "b.tar", lambda t: (
        _add_file(t, "hestia"),
        _add_file(t, "web/dom.com/domain_data.tar", b"data"),
        _add_file(t, "db/wp/wp.mysql.sql.gz", b"dump"),
    ))
    dest = tmp_path / "out"
    dest.mkdir()
    names = safe_extract_tar(tar_path, str(dest), config_only=True)
    # Los nombres se reportan TODOS (para saber qué datos existen)…
    assert "web/dom.com/domain_data.tar" in names
    assert "db/wp/wp.mysql.sql.gz" in names
    # …pero los datos pesados NO se extraen.
    assert not (dest / "web/dom.com/domain_data.tar").exists()
    assert not (dest / "db/wp/wp.mysql.sql.gz").exists()
    # El .conf ligero sí.
    assert (dest / "hestia").exists()


def test_aborta_ante_path_traversal(tmp_path):
    tar_path = _make_tar(tmp_path / "b.tar",
                         lambda t: _add_file(t, "../escape.txt", b"evil"))
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(HestiaImportError):
        safe_extract_tar(tar_path, str(dest))


def test_omite_symlink_fuera_del_destino_sin_abortar(tmp_path):
    def builder(t):
        _add_file(t, "web/dom.com/index.php", b"ok")
        link = tarfile.TarInfo("web/dom.com/ssl.conf")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/letsencrypt/live/dom.com/fullchain.pem"
        t.addfile(link)
    tar_path = _make_tar(tmp_path / "b.tar", builder)
    dest = tmp_path / "out"
    dest.mkdir()
    # No aborta; el symlink externo se omite, el fichero normal se extrae.
    names = safe_extract_tar(tar_path, str(dest))
    assert "web/dom.com/ssl.conf" in names           # reportado
    assert (dest / "web/dom.com/index.php").exists()  # extraído
    assert not (dest / "web/dom.com/ssl.conf").exists()  # omitido


def test_tar_invalido_da_error_claro(tmp_path):
    bad = tmp_path / "no.tar"
    bad.write_bytes(b"esto no es un tar")
    with pytest.raises(HestiaImportError):
        safe_extract_tar(str(bad), str(tmp_path / "out"))
