"""
Detección de la versión major de Dovecot instalada.

Dovecot 2.4 (Debian 13/trixie) cambió la sintaxis de configuración respecto a
2.3 (Debian 12/bookworm): desaparecen los bloques `plugin { }`, `mail_plugins`
pasa a ser un bloque, quota/sieve/imapsieve usan claves nuevas, etc. Los
generadores de config del panel consultan esto para emitir la sintaxis correcta
según el servidor donde corran.

Ver docs/UPGRADE_DEBIAN_12_A_13.md y scripts/dist_upgrade_debian13.sh
(migrate_dovecot_24_config) para el detalle de los cambios.
"""
from __future__ import annotations

import re
import subprocess
import logging

logger = logging.getLogger(__name__)


def dovecot_version() -> tuple[int, int]:
    """Devuelve (major, minor) de Dovecot, p.ej. (2, 4). Si no se puede
    detectar, asume (2, 3) por seguridad (la sintaxis vieja es la histórica)."""
    try:
        out = subprocess.run(["dovecot", "--version"], capture_output=True,
                             text=True, timeout=10).stdout.strip()
        m = re.match(r"(\d+)\.(\d+)", out)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception as e:
        logger.warning(f"No se pudo detectar la versión de Dovecot: {e}")
    return (2, 3)


def is_dovecot_24_plus() -> bool:
    """True si Dovecot es >= 2.4 (sintaxis de config nueva)."""
    major, minor = dovecot_version()
    return (major, minor) >= (2, 4)
