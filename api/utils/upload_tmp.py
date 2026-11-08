"""
Subidas grandes fuera de /tmp.

Starlette guarda cada fichero de un multipart en un SpooledTemporaryFile: pasado
1 MB lo vuelca a disco en el directorio temporal por defecto, /tmp. En Debian 13
/tmp es un tmpfs (en RAM): subir un backup de 5 GB al importador lo llenaba (o
se comía la memoria del servidor) antes de que nuestro código viera un byte.

install() hace que esos ficheros vayan a /var/lib/svqpanel/upload-tmp (disco
real, 0700, solo root: el panel es quien los lee). Son anónimos (se borran solos
al cerrarse), así que no dejan restos aunque el proceso muera.
"""

import logging
import os
from tempfile import SpooledTemporaryFile

logger = logging.getLogger(__name__)

UPLOAD_TMP_DIR = "/var/lib/svqpanel/upload-tmp"


def _make_class(directory: str):
    class DiskSpooledTemporaryFile(SpooledTemporaryFile):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("dir", directory)
            super().__init__(*args, **kwargs)
    return DiskSpooledTemporaryFile


def install(directory: str = UPLOAD_TMP_DIR) -> bool:
    """Redirige el búfer de subidas de Starlette a `directory`. Solo en el
    servidor (POSIX); si no se puede crear el directorio, se queda en /tmp."""
    if os.name != "posix":
        return False
    try:
        os.makedirs(directory, mode=0o700, exist_ok=True)
    except OSError as e:
        logger.warning(f"Subidas: no se pudo crear {directory} ({e}); se usará /tmp")
        return False
    try:
        import starlette.formparsers as fp
    except ImportError:
        return False
    if not hasattr(fp, "SpooledTemporaryFile"):
        logger.warning("Subidas: Starlette ya no usa SpooledTemporaryFile; se usará /tmp")
        return False
    fp.SpooledTemporaryFile = _make_class(directory)
    return True
