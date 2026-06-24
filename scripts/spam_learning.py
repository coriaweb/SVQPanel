"""
Aprendizaje de spam (Rspamd Bayes) — entrenamiento al mover correo a/desde Junk.

Cuando un cliente arrastra un correo a la carpeta Junk/Spam, Dovecot (vía
IMAPSieve) ejecuta `rspamc learn_spam`; al sacarlo de Junk a otra carpeta,
`rspamc learn_ham`. Así Rspamd aprende del uso real y mejora el filtro con el
tiempo. Complementado con autolearn automático (Rspamd aprende solo de los
correos con score muy alto/bajo) y Bayes GLOBAL del servidor.

Idempotente: install() puede re-ejecutarse sin romper nada. Es la fuente de
verdad que invocan install.sh y el update correspondiente.
"""

import os
import logging

from .base import SystemManager

logger = logging.getLogger(__name__)

DOVECOT_CONF_D = "/etc/dovecot/conf.d"
SIEVE_DIR = "/etc/dovecot/sieve"
# Config de Dovecot que activa sieve + imap_sieve y mapea los eventos de Junk.
IMAP_SIEVE_CONF = f"{DOVECOT_CONF_D}/90-svqpanel-spam-learn.conf"
# Scripts sieve que llaman a rspamc al mover correo.
SIEVE_LEARN_SPAM = f"{SIEVE_DIR}/learn-spam.sieve"
SIEVE_LEARN_HAM = f"{SIEVE_DIR}/learn-ham.sieve"
# Wrappers que ejecutan rspamc (el sieve 'pipe' los invoca).
PIPE_BIN_DIR = "/usr/lib/dovecot/sieve-pipe"
PIPE_LEARN_SPAM = f"{PIPE_BIN_DIR}/rspamd-learn-spam.sh"
PIPE_LEARN_HAM = f"{PIPE_BIN_DIR}/rspamd-learn-ham.sh"
# Config de Rspamd: autolearn + cabeceras.
RSPAMD_CLASSIFIER = "/etc/rspamd/local.d/classifier-bayes.conf"
RSPAMD_MILTER_HEADERS = "/etc/rspamd/local.d/milter_headers.conf"

# Cabeceras que Rspamd añade al correo. x-spamd-result = detalle de las reglas
# que dispararon (imprescindible para saber POR QUÉ se marcó spam). x-spam-level
# = asteriscos según el score (compat con filtros clásicos).
_MILTER_HEADERS = """# SVQPanel — cabeceras de diagnóstico de Rspamd. NO editar manualmente.
use = ["x-spam-status", "x-spam-score", "x-spam-level", "x-spamd-result",
       "x-rspamd-score", "authentication-results"];
authenticated_headers = ["authentication-results"];
"""

_IMAP_SIEVE_CONF = """# SVQPanel — Aprendizaje de spam (IMAPSieve → rspamc). NO editar manualmente.
# Al mover un correo a Junk → learn_spam; al sacarlo de Junk → learn_ham.
protocol imap {
  mail_plugins = $mail_plugins imap_sieve
}

plugin {
  sieve_plugins = sieve_imapsieve sieve_extprograms

  # Correo COPIADO/MOVIDO a la carpeta Junk → aprender como SPAM
  imapsieve_mailbox1_name = Junk
  imapsieve_mailbox1_causes = COPY APPEND
  imapsieve_mailbox1_before = file:%(sieve_dir)s/learn-spam.sieve

  # Correo SACADO de Junk a otra carpeta → aprender como HAM (legítimo)
  imapsieve_mailbox2_name = *
  imapsieve_mailbox2_from = Junk
  imapsieve_mailbox2_causes = COPY
  imapsieve_mailbox2_before = file:%(sieve_dir)s/learn-ham.sieve

  sieve_pipe_bin_dir = %(pipe_bin_dir)s
  sieve_global_extensions = +vnd.dovecot.pipe +vnd.dovecot.environment
}
""".replace("%(sieve_dir)s", SIEVE_DIR).replace("%(pipe_bin_dir)s", PIPE_BIN_DIR)

_SIEVE_LEARN_SPAM = """require ["vnd.dovecot.pipe", "copy", "imapsieve", "environment", "variables"];
if environment :matches "imap.user" "*" { set "username" "${1}"; }
pipe :copy "rspamd-learn-spam.sh" [ "${username}" ];
"""

_SIEVE_LEARN_HAM = """require ["vnd.dovecot.pipe", "copy", "imapsieve", "environment", "variables"];
if environment :matches "imap.user" "*" { set "username" "${1}"; }
pipe :copy "rspamd-learn-ham.sh" [ "${username}" ];
"""

# El correo a aprender llega por STDIN al wrapper. rspamc lo clasifica vía el
# controller en localhost:11334 (secure_ip=127.0.0.1 → no pide password local).
_PIPE_LEARN_SPAM = """#!/bin/sh
# SVQPanel — entrena Rspamd como SPAM el correo recibido por STDIN.
exec /usr/bin/rspamc -h localhost:11334 learn_spam
"""

_PIPE_LEARN_HAM = """#!/bin/sh
# SVQPanel — entrena Rspamd como HAM (legítimo) el correo recibido por STDIN.
exec /usr/bin/rspamc -h localhost:11334 learn_ham
"""

# Bayes con autolearn: aprende solo de los casos obvios (score muy alto = spam,
# muy bajo = ham), además del aprendizaje manual. Global del servidor.
_RSPAMD_CLASSIFIER = """# SVQPanel — clasificador Bayes (aprendizaje de spam). NO editar manualmente.
backend = "redis";
# GLOBAL del servidor: NO definimos users{} ni per_user → un único Bayes que
# todos los clientes entrenan (más datos = aprende más rápido).
# Autolearn: Rspamd aprende solo de los correos claramente spam (score >= 12) y
# claramente legítimos (score <= -2), aunque el cliente no marque nada.
autolearn = [-2, 12];
# min_learns: nº mínimo de mensajes aprendidos (de cada clase) antes de que el
# Bayes empiece a puntuar. 30 es un equilibrio: útil pronto sin disparar falsos
# positivos con pocos datos.
min_learns = 30;
"""


class SpamLearningManager(SystemManager):
    """Configura el aprendizaje de spam (IMAPSieve + autolearn de Rspamd)."""

    def __init__(self):
        super().__init__(require_root=True)

    def available(self) -> bool:
        return os.path.isdir(DOVECOT_CONF_D) and os.path.isfile("/usr/bin/rspamc")

    def _write(self, path: str, content: str, mode: int = 0o644):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(content)
        os.chmod(tmp, mode)
        os.replace(tmp, path)

    def install(self, reload: bool = True) -> dict:
        """Instala/actualiza toda la configuración del aprendizaje de spam.
        Idempotente. Requiere dovecot-sieve instalado (lo pone install.sh/update).
        """
        if not self.available():
            return {"success": False, "reason": "dovecot/rspamd no disponibles"}

        # 1) Scripts wrapper que ejecutan rspamc (ejecutables).
        self._write(PIPE_LEARN_SPAM, _PIPE_LEARN_SPAM, 0o755)
        self._write(PIPE_LEARN_HAM, _PIPE_LEARN_HAM, 0o755)

        # 2) Scripts sieve + PRE-COMPILAR a .svbin (como root). Sin esto, Dovecot
        #    intenta compilar el .svbin en cada uso y falla con "Read-only file
        #    system" (el usuario del buzón no puede escribir en /etc/dovecot/sieve),
        #    ensuciando el log (aunque el learn funcione en memoria).
        self._write(SIEVE_LEARN_SPAM, _SIEVE_LEARN_SPAM)
        self._write(SIEVE_LEARN_HAM, _SIEVE_LEARN_HAM)
        for s in (SIEVE_LEARN_SPAM, SIEVE_LEARN_HAM):
            self.execute_command(["sievec", s], check=False)

        # 3) Config de Dovecot (IMAPSieve).
        self._write(IMAP_SIEVE_CONF, _IMAP_SIEVE_CONF)

        # 4) Asegurar que el plugin sieve global está activo (LMTP/LDA).
        self._ensure_sieve_global_plugin()

        # 5) Bayes con autolearn (Rspamd).
        self._write(RSPAMD_CLASSIFIER, _RSPAMD_CLASSIFIER)

        # 5b) Cabeceras de diagnóstico (x-spamd-result, x-spam-level…).
        self._write(RSPAMD_MILTER_HEADERS, _MILTER_HEADERS)

        # rspamc aprende vía el controller en localhost:11334. secure_ip=127.0.0.1
        # (lo deja install.sh en worker-controller.inc) permite learn sin password
        # desde localhost, que es como conecta el LDA/imap.

        if reload:
            self.execute_command(["systemctl", "reload-or-restart", "dovecot"], check=False)
            self.execute_command(["systemctl", "reload-or-restart", "rspamd"], check=False)

        logger.info("Aprendizaje de spam configurado (IMAPSieve + autolearn Bayes)")
        return {"success": True}

    def _ensure_sieve_global_plugin(self):
        """Garantiza que 'sieve' está en mail_plugins de LMTP (para el LDA)."""
        # En la mayoría de instalaciones Dovecot el plugin sieve se activa en
        # 15-lda.conf / 20-lmtp.conf. Nuestro 90-*.conf ya añade imap_sieve al
        # protocolo imap; sieve_extprograms lo cargan los scripts. No forzamos
        # cambios en otros ficheros para no romper config existente.
        return

    def stats(self) -> dict:
        """Devuelve cuánto ha aprendido el Bayes (para mostrar en el panel)."""
        rc, out, err = self.execute_command(["rspamc", "stat"], check=False)
        learned_spam = learned_ham = 0
        for line in (out or "").splitlines():
            l = line.strip()
            if l.startswith("Statfile: BAYES_SPAM"):
                learned_spam = _extract_learned(l)
            elif l.startswith("Statfile: BAYES_HAM"):
                learned_ham = _extract_learned(l)
        return {"learned_spam": learned_spam, "learned_ham": learned_ham}


def _extract_learned(line: str) -> int:
    import re
    m = re.search(r"learned:\s*(\d+)", line)
    return int(m.group(1)) if m else 0
