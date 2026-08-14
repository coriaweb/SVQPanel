"""
Logger de intentos de autenticación fallidos del panel SVQPanel.

Escribe líneas en /opt/svqpanel/logs/auth.log con el formato:
    YYYY-MM-DD HH:MM:SS auth_failed ip=<IP> user=<USER> reason=<REASON>

El filtro fail2ban [svqpanel-auth] (definido en install.sh) busca el patrón
'auth_failed ip=<HOST>' y banea la IP tras N intentos.

NUNCA lanza excepciones — un fallo de I/O al loguear no debe romper la
respuesta HTTP. Si el archivo no se puede escribir, se ignora silenciosamente.
"""

import os
import logging
from datetime import datetime
from typing import Optional
from fastapi import Request

# Re-export: la lógica vive en api.utils.client_ip (fuente única). Se mantiene
# el nombre aquí porque varios módulos hacen `from api.utils.auth_log import
# client_ip`. NO reimplementar: leer el primer valor del XFF es falsificable.
from api.utils.client_ip import client_ip  # noqa: F401

AUTH_LOG_PATH = "/opt/svqpanel/logs/auth.log"
_FALLBACK_LOG = logging.getLogger(__name__)


def _sanitize(value: str, max_len: int = 64) -> str:
    """Quita caracteres no imprimibles y trunca, para evitar log injection."""
    if not value:
        return "-"
    cleaned = "".join(c for c in value if c.isprintable() and c not in (" ", "\t", "\n", "\r"))
    return cleaned[:max_len] or "-"


def log_auth_failed(
    request: Optional[Request],
    username: Optional[str] = None,
    reason: str = "bad_credentials",
) -> None:
    """
    Registra un intento de autenticación fallido. Si no se puede escribir
    el archivo, no propaga el error.
    """
    ip = client_ip(request)
    if not ip:
        return  # Sin IP no podemos banear, no merece la pena loguear

    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    line = (
        f"{ts} auth_failed "
        f"ip={_sanitize(ip, 45)} "
        f"user={_sanitize(username or '-', 64)} "
        f"reason={_sanitize(reason, 32)}\n"
    )

    try:
        os.makedirs(os.path.dirname(AUTH_LOG_PATH), exist_ok=True)
        with open(AUTH_LOG_PATH, "a") as f:
            f.write(line)
    except Exception as e:
        _FALLBACK_LOG.warning(f"No se pudo escribir {AUTH_LOG_PATH}: {e}")
