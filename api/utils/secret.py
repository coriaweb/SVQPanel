"""
Acceso centralizado a la SECRET_KEY del panel (firma de JWT, derivación de
claves de cifrado).

Endurecimiento de seguridad: si SECRET_KEY no está definida o tiene un valor
placeholder conocido, fallamos de forma RUIDOSA en producción (DEBUG distinto de
true) en vez de firmar tokens con un secreto público — lo que permitiría a
cualquiera forjar JWTs y suplantar a admin.

El install.sh genera una SECRET_KEY aleatoria (secrets.token_hex(32)), así que
en una instalación normal esto nunca se dispara.
"""

import os
import logging

logger = logging.getLogger(__name__)

# Valores placeholder que NUNCA deben usarse para firmar en producción.
_PLACEHOLDERS = {
    "",
    "change-this-in-production",
    "dev-secret-key-cambiar-en-produccion",
    "svqpanel-insecure-default",
    "tu_secreto_aqui",
}

# Secreto de desarrollo estable (solo cuando DEBUG=true): evita romper el
# entorno local, pero jamás se usa en producción.
_DEV_SECRET = "svqpanel-dev-only-not-for-production"


def _is_debug() -> bool:
    return os.getenv("DEBUG", "false").strip().lower() in ("1", "true", "yes")


def get_secret_key() -> str:
    """
    Devuelve la SECRET_KEY. Si falta o es un placeholder:
      - en producción (DEBUG != true): RuntimeError (fail-safe).
      - en desarrollo (DEBUG = true): un secreto de dev fijo + warning.
    """
    key = os.getenv("SECRET_KEY", "")
    if key and key not in _PLACEHOLDERS:
        return key

    if _is_debug():
        logger.warning(
            "SECRET_KEY no configurada o placeholder; usando secreto de DESARROLLO. "
            "NO usar en producción."
        )
        return _DEV_SECRET

    raise RuntimeError(
        "SECRET_KEY no está configurada (o es un valor de ejemplo). "
        "Define una SECRET_KEY fuerte en el .env "
        "(p. ej. `python -c \"import secrets; print(secrets.token_hex(32))\"`)."
    )
