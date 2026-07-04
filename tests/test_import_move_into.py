"""
_move_into: mueve el contenido de un dir dentro de otro (merge, pisa) liberando
el origen sobre la marcha — es el reemplazo de _copy_into en la restauración de
maildirs/web para que el pico de disco de una importación grande sea ~1x el
tamaño de los datos y no ~3-4x (ENOSPC visto con un correo de 30GB).
Debe respetar la semántica de _copy_into: mezclar carpetas existentes y pisar
ficheros existentes.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scripts.hestia_import as hi


def _write(path, content="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def test_mezcla_con_esqueleto_existente_y_vacia_origen(tmp_path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    # Origen: un buzón con correos (como el accounts.tar extraído).
    _write(str(src / "buzon1" / "cur" / "msg1"), "correo1")
    _write(str(src / "buzon1" / "new" / "msg2"), "correo2")
    # Destino: el esqueleto que dejó create_mailbox (cur/ existe y con un fichero).
    _write(str(dest / "buzon1" / "cur" / "previo"), "ya estaba")
    os.makedirs(str(dest / "buzon1" / "tmp"))

    hi._move_into(str(src), str(dest))

    # Mezcla: lo movido Y lo que ya estaba conviven.
    assert open(str(dest / "buzon1" / "cur" / "msg1")).read() == "correo1"
    assert open(str(dest / "buzon1" / "new" / "msg2")).read() == "correo2"
    assert open(str(dest / "buzon1" / "cur" / "previo")).read() == "ya estaba"
    assert os.path.isdir(str(dest / "buzon1" / "tmp"))
    # El origen quedó vacío (liberado sobre la marcha).
    assert os.listdir(str(src)) == []


def test_pisa_ficheros_existentes_como_copy_into(tmp_path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    _write(str(src / "maildirsize"), "nuevo")
    _write(str(dest / "maildirsize"), "viejo")

    hi._move_into(str(src), str(dest))

    assert open(str(dest / "maildirsize")).read() == "nuevo"


def test_crea_destino_si_no_existe(tmp_path):
    src = tmp_path / "src"
    dest = tmp_path / "no_existe" / "dest"
    _write(str(src / "a" / "b.txt"), "hola")

    hi._move_into(str(src), str(dest))

    assert open(str(dest / "a" / "b.txt")).read() == "hola"
