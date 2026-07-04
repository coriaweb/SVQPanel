"""
extract_data_archive con .tar.zst: la descompresión va EN STREAMING directo a
la extracción (safe_extract_tar con fileobj, modo "r|*"), sin materializar el
.tar intermedio de tamaño completo — antes un accounts.tar.zst de 30GB creaba
otro .tar de 30GB durante toda la extracción (pico de disco duplicado).
Las validaciones de seguridad (rutas que escapan del destino) deben seguir
aplicando en modo streaming.
"""
import io
import os
import sys
import tarfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

zstandard = pytest.importorskip("zstandard")

import scripts.hestia_import as hi


def _make_tar_zst(path, members):
    """Crea un .tar.zst con {nombre: contenido}."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, content in members.items():
            data = content.encode()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    cctx = zstandard.ZstdCompressor()
    with open(path, "wb") as f:
        f.write(cctx.compress(buf.getvalue()))


def test_extrae_tar_zst_en_streaming_sin_tar_intermedio(tmp_path):
    archive = str(tmp_path / "accounts.tar.zst")
    dest = str(tmp_path / "dest")
    _make_tar_zst(archive, {
        "buzon1/cur/msg1": "correo 1",
        "buzon1/new/msg2": "correo 2",
    })

    hi.extract_data_archive(archive, dest)

    assert open(os.path.join(dest, "buzon1", "cur", "msg1")).read() == "correo 1"
    assert open(os.path.join(dest, "buzon1", "new", "msg2")).read() == "correo 2"
    # No quedó ningún .tar intermedio junto al archivo.
    leftovers = [f for f in os.listdir(str(tmp_path)) if "__tmp" in f]
    assert leftovers == []


def test_streaming_sigue_bloqueando_rutas_que_escapan(tmp_path):
    archive = str(tmp_path / "malo.tar.zst")
    dest = str(tmp_path / "dest")
    _make_tar_zst(archive, {"../fuera.txt": "escapo"})

    with pytest.raises(hi.HestiaImportError):
        hi.extract_data_archive(archive, dest)
    assert not os.path.exists(str(tmp_path / "fuera.txt"))
