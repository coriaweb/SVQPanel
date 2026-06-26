"""
Mover el spam marcado por Rspamd a la carpeta Junk del buzón (vía Sieve global).

Rspamd marca el correo con la cabecera `X-Spam: Yes` cuando supera el umbral
"add header" (por defecto score >= 6). Pero esa cabecera por sí sola NO hace
nada: el correo llega igualmente a la bandeja de entrada. Aquí instalamos un
script Sieve GLOBAL "before" en Dovecot que, en el momento de la entrega (LMTP),
mueve esos correos a la carpeta `Junk` (estándar IMAP, la misma que ya usa el
aprendizaje imapsieve).

Arquitectura del override por dominio (importante):
  - El move a Junk es GLOBAL y trivial: "si X-Spam: Yes → Junk".
  - La exclusión POR DOMINIO se hace en Rspamd, NO aquí: para un dominio con
    spam_to_junk desactivado, Rspamd sube el umbral "add header" a 999 → no
    añade `X-Spam: Yes` → este Sieve no lo mueve. Eso lo aplica RspamdManager
    en settings.conf. Así el Sieve no necesita lógica frágil de dominios.

El script "before" se ejecuta ANTES del Sieve personal del usuario, así que sus
reglas propias siguen funcionando después.
"""
from __future__ import annotations

import os
import subprocess
import logging

logger = logging.getLogger(__name__)

# Dovecot ejecuta en orden los scripts de este directorio (sieve_before).
SIEVE_BEFORE_DIR = "/var/lib/dovecot/sieve.d"
SPAM_SIEVE = os.path.join(SIEVE_BEFORE_DIR, "10-spam-to-junk.sieve")
# Drop-in que activa sieve_before apuntando a nuestro directorio.
SIEVE_CONF_DROPIN = "/etc/dovecot/conf.d/91-svqpanel-spam-junk.conf"

JUNK_FOLDER = "Junk"


def _script(enabled: bool) -> str:
    """Contenido del Sieve global. Si enabled=False queda como no-op válido
    (desactivar es seguro y reversible)."""
    if not enabled:
        return (
            "# SVQPanel — mover spam a Junk: DESACTIVADO globalmente. NO editar.\n"
            'require ["fileinto"];\n'
        )
    return f"""\
# SVQPanel — mover spam (X-Spam: Yes) a la carpeta {JUNK_FOLDER}. NO editar.
# La exclusión por dominio la aplica Rspamd (no marca X-Spam en dominios
# excluidos), por eso aquí basta una regla global.
require ["fileinto", "mailbox"];

if header :is "X-Spam" "Yes" {{
    fileinto :create "{JUNK_FOLDER}";
    stop;
}}
"""


def _compile_sieve(path: str) -> bool:
    """Compila el .sieve a .svbin con sievec. Devuelve True si compiló."""
    try:
        subprocess.run(["sievec", path], check=True,
                       capture_output=True, text=True, timeout=30)
        return True
    except Exception as e:
        logger.error(f"sievec falló para {path}: {e}")
        return False


def _ensure_dropin() -> bool:
    """Asegura el drop-in que activa sieve_before. True si cambió."""
    content = (
        "# SVQPanel — activa el Sieve global 'before' para mover spam a Junk.\n"
        "# NO editar manualmente.\n"
        "plugin {\n"
        f"  sieve_before = file:{SIEVE_BEFORE_DIR}\n"
        "}\n"
    )
    cur = ""
    if os.path.exists(SIEVE_CONF_DROPIN):
        with open(SIEVE_CONF_DROPIN) as f:
            cur = f.read()
    if cur == content:
        return False
    with open(SIEVE_CONF_DROPIN, "w") as f:
        f.write(content)
    return True


def apply(enabled: bool) -> dict:
    """Instala/actualiza el Sieve global de spam→Junk. Idempotente.

    enabled=False deja un script no-op (no mueve nada) pero mantiene la
    instalación, de modo que reactivar es solo reescribir el script.
    """
    os.makedirs(SIEVE_BEFORE_DIR, exist_ok=True)

    tmp = SPAM_SIEVE + ".tmp"
    with open(tmp, "w") as f:
        f.write(_script(enabled))
    os.replace(tmp, SPAM_SIEVE)

    compiled = _compile_sieve(SPAM_SIEVE)
    dropin_changed = _ensure_dropin()

    if dropin_changed:
        try:
            subprocess.run(["systemctl", "reload", "dovecot"],
                           check=False, capture_output=True, timeout=30)
        except Exception as e:
            logger.warning(f"No se pudo recargar dovecot: {e}")

    return {"success": compiled, "enabled": enabled, "compiled": compiled}
