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
import re
import subprocess
import logging

try:
    from scripts.dovecot_version import is_dovecot_24_plus
except ImportError:  # ejecución directa fuera del paquete
    from dovecot_version import is_dovecot_24_plus

logger = logging.getLogger(__name__)

# Dovecot ejecuta en orden los scripts de este directorio (sieve_before).
SIEVE_BEFORE_DIR = "/var/lib/dovecot/sieve.d"
SPAM_SIEVE = os.path.join(SIEVE_BEFORE_DIR, "10-spam-to-junk.sieve")
# Drop-in que activa sieve_before apuntando a nuestro directorio.
SIEVE_CONF_DROPIN = "/etc/dovecot/conf.d/91-svqpanel-spam-junk.conf"

# 10-master.conf de Dovecot (donde está el service lmtp) y socket en el chroot
# de Postfix para que la entrega pase por Dovecot LMTP.
DOVECOT_MASTER = "/etc/dovecot/conf.d/10-master.conf"
POSTFIX_LMTP_SOCK = "/var/spool/postfix/private/dovecot-lmtp"

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
    """Asegura el drop-in que activa sieve_before. True si cambió.

    IMPORTANTE: para que un Sieve se ejecute EN LA ENTREGA, el plugin 'sieve'
    debe estar en mail_plugins de los protocolos que entregan (lmtp y lda). Por
    defecto Dovecot NO lo incluye ahí (solo imap_sieve en imap, para aprendizaje),
    así que sieve_before nunca corría en la entrega. Lo añadimos aquí."""
    if is_dovecot_24_plus():
        # Dovecot 2.4 (Debian 13): mail_plugins es un bloque y el script global
        # 'before' se declara con sieve_script { type = before; path = ... }.
        content = (
            "# SVQPanel — Sieve global 'before' para mover spam a Junk (Dovecot 2.4).\n"
            "# NO editar. El plugin 'sieve' en lmtp/lda ejecuta los Sieve EN LA ENTREGA.\n"
            "protocol lmtp {\n"
            "  mail_plugins {\n"
            "    sieve = yes\n"
            "  }\n"
            "}\n"
            "protocol lda {\n"
            "  mail_plugins {\n"
            "    sieve = yes\n"
            "  }\n"
            "}\n"
            "sieve_script spam-to-junk {\n"
            "  type = before\n"
            f"  path = {SPAM_SIEVE}\n"
            "}\n"
        )
    else:
        # Dovecot 2.3 (Debian 12): bloque plugin {} y mail_plugins aditivo.
        content = (
            "# SVQPanel — Sieve global 'before' para mover spam a Junk. NO editar.\n"
            "# El plugin 'sieve' en lmtp/lda es lo que ejecuta los Sieve EN LA ENTREGA\n"
            "# (sin esto, sieve_before y el sieve del usuario no se aplican al recibir).\n"
            "protocol lmtp {\n"
            "  mail_plugins = $mail_plugins sieve\n"
            "}\n"
            "protocol lda {\n"
            "  mail_plugins = $mail_plugins sieve\n"
            "}\n"
            "plugin {\n"
            # IMPORTANTE: apuntar al FICHERO .sieve, no al directorio. Con
            # 'file:<directorio>' Dovecot NO carga el script en LMTP (sí en LDA),
            # y el spam se queda en INBOX. Con el fichero concreto funciona en ambos.
            f"  sieve_before = {SPAM_SIEVE}\n"
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


def ensure_lmtp_delivery() -> bool:
    """Hace que Postfix entregue el correo local vía Dovecot LMTP (no con su
    agente 'virtual'). Sin esto, la entrega NO pasa por Dovecot y NINGÚN Sieve
    se ejecuta (ni spam→Junk ni las reglas/filtros del usuario). Idempotente.

    1) Añade un unix_listener LMTP dentro del chroot de Postfix al service lmtp
       de Dovecot (10-master.conf).
    2) postconf virtual_transport = lmtp:unix:private/dovecot-lmtp.
    Devuelve True si cambió algo (para saber si reiniciar)."""
    changed = False

    # 1) Listener LMTP en el chroot de Postfix.
    try:
        with open(DOVECOT_MASTER) as f:
            master = f.read()
    except OSError:
        master = ""
    if master and POSTFIX_LMTP_SOCK not in master:
        block = (
            "service lmtp {\n"
            "  unix_listener lmtp {\n"
            "    #mode = 0666\n"
            "  }\n\n"
            "  # SVQPanel — listener LMTP en el chroot de Postfix para que la\n"
            "  # entrega pase por Dovecot (y se ejecuten los Sieve).\n"
            f"  unix_listener {POSTFIX_LMTP_SOCK} {{\n"
            "    mode = 0600\n"
            "    user = postfix\n"
            "    group = postfix\n"
            "  }\n"
            "}"
        )
        new_master, n = re.subn(r"service lmtp \{.*?\n\}", block, master,
                                count=1, flags=re.DOTALL)
        if n == 1:
            with open(DOVECOT_MASTER, "w") as f:
                f.write(new_master)
            changed = True
        else:
            logger.warning("No se encontró 'service lmtp' en 10-master.conf")

    # 2) virtual_transport → LMTP.
    try:
        cur = subprocess.run(["postconf", "-h", "virtual_transport"],
                             capture_output=True, text=True, timeout=15).stdout.strip()
        if cur != "lmtp:unix:private/dovecot-lmtp":
            subprocess.run(["postconf", "-e",
                            "virtual_transport = lmtp:unix:private/dovecot-lmtp"],
                           check=True, capture_output=True, timeout=15)
            changed = True
    except Exception as e:
        logger.warning(f"No se pudo fijar virtual_transport: {e}")

    return changed


def apply(enabled: bool) -> dict:
    """Instala/actualiza el Sieve global de spam→Junk y la entrega vía LMTP.
    Idempotente.

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
    lmtp_changed = ensure_lmtp_delivery()

    if dropin_changed or lmtp_changed:
        # Cambios en mail_plugins de protocolo / service lmtp → restart (reload
        # no recarga los plugins de protocolo de forma fiable).
        try:
            subprocess.run(["systemctl", "restart", "dovecot"],
                           check=False, capture_output=True, timeout=30)
        except Exception as e:
            logger.warning(f"No se pudo reiniciar dovecot: {e}")
    if lmtp_changed:
        try:
            subprocess.run(["systemctl", "restart", "postfix"],
                           check=False, capture_output=True, timeout=30)
        except Exception as e:
            logger.warning(f"No se pudo reiniciar postfix: {e}")

    # Salvaguarda CRÍTICA: si tras pasar a LMTP el socket no existe (Dovecot no
    # lo creó), revertir a la entrega 'virtual' para NO dejar el correo sin
    # entregar. La feature spam→Junk no merece romper la recepción de correo.
    lmtp_ok = True
    if lmtp_changed:
        import time as _t
        _t.sleep(1)
        if not os.path.exists(POSTFIX_LMTP_SOCK):
            logger.error("Socket LMTP ausente tras configurar; revirtiendo a "
                         "virtual_transport=virtual para no romper la entrega")
            try:
                subprocess.run(["postconf", "-e", "virtual_transport = virtual"],
                               check=False, capture_output=True, timeout=15)
                subprocess.run(["systemctl", "restart", "postfix"],
                               check=False, capture_output=True, timeout=30)
            except Exception:
                pass
            lmtp_ok = False

    return {"success": compiled, "enabled": enabled, "compiled": compiled,
            "lmtp_delivery": lmtp_ok}
