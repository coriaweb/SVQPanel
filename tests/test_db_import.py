"""Importador de BDs grandes: filtro del SQL y subida por trozos reanudable."""
import gzip
import os
import zipfile

import pytest

from scripts import db_import as imp


def test_quita_definer_y_cambio_de_bd():
    sql = (b"CREATE DATABASE /*!32312 IF NOT EXISTS*/ `otra` /*!40100 DEFAULT CHARACTER SET utf8mb4 */;\n"
           b"USE `otra`;\n"
           b"/*!50013 DEFINER=`root`@`localhost` SQL SECURITY DEFINER */\n"
           b"CREATE DEFINER=`viejo`@`%` PROCEDURE p() BEGIN END;\n"
           b"/*!50017 DEFINER=`root`@`localhost`*/ /*!50003 TRIGGER t BEFORE INSERT ON a FOR EACH ROW SET @x=1 */;\n"
           b"INSERT INTO a VALUES ('USER manual');\n")
    out = imp.filter_sql(sql)
    assert b"DEFINER=" not in out
    assert b"CREATE DATABASE" not in out and b"USE `otra`" not in out
    assert b"CREATE PROCEDURE p()" in out
    assert b"SQL SECURITY DEFINER" in out
    assert b"INSERT INTO a VALUES ('USER manual');" in out


@pytest.mark.parametrize("name,ok", [
    ("volcado.sql", True), ("v.sql.gz", True), ("copia.zip", True),
    ("../x.sql", False), (".oculto.sql", False), ("a/b.sql", False),
    ("programa.php", False), ("", False),
])
def test_nombres(name, ok):
    assert imp.valid_name(name) is ok


def test_fuentes_comprimidas(tmp_path):
    sql = b"INSERT INTO t VALUES (1);\n" * 1000
    gz = tmp_path / "a.sql.gz"
    gz.write_bytes(gzip.compress(sql))
    zp = tmp_path / "a.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("leeme.txt", "x")
        z.writestr("dump/a.sql", sql)
    for p in (gz, zp):
        with open(p, "rb") as raw:
            src, progress = imp._open_source(raw, p.name)
            assert src.read(10**7) == sql
            assert progress() == pytest.approx(1.0, abs=0.01)


@pytest.mark.skipif(os.name == "nt", reason="O_NOFOLLOW/fchown: solo Linux")
def test_subida_por_trozos_reanudable(tmp_path, monkeypatch):
    monkeypatch.setattr(imp, "_owner",
                        lambda u: (os.getuid(), os.getgid(), str(tmp_path)))
    data = os.urandom(25 * 1024)
    assert imp.upload_offset("cli", "big.sql.gz", len(data)) == 0
    r = imp.append_chunk("cli", "big.sql.gz", len(data), 0, data[:10240])
    assert r == {"offset": 10240, "done": False}
    # Un trozo repetido (reintento tras corte) no se duplica: devuelve el offset bueno.
    r = imp.append_chunk("cli", "big.sql.gz", len(data), 0, data[:10240])
    assert r["mismatch"] and r["offset"] == 10240
    assert imp.list_files("cli")["partial"][0]["received"] == 10240
    r = imp.append_chunk("cli", "big.sql.gz", len(data), 10240, data[10240:])
    assert r == {"offset": len(data), "done": True}
    assert (tmp_path / "imports" / "big.sql.gz").read_bytes() == data
    assert [f["name"] for f in imp.list_files("cli")["files"]] == ["big.sql.gz"]


@pytest.mark.skipif(os.name == "nt", reason="symlinks/O_NOFOLLOW: solo Linux")
def test_no_sigue_symlinks(tmp_path, monkeypatch):
    monkeypatch.setattr(imp, "_owner",
                        lambda u: (os.getuid(), os.getgid(), str(tmp_path)))
    secreto = tmp_path / "secreto.txt"
    secreto.write_text("x")
    imp.list_files("cli")
    os.symlink(secreto, tmp_path / "imports" / "robo.sql")
    assert imp.list_files("cli")["files"] == []
    with pytest.raises(OSError):
        imp.delete_file("cli", "robo.sql")
    assert secreto.exists()
