#!/bin/bash
# 0056-spam-to-junk.sh
#
# Mueve el spam marcado por Rspamd (cabecera X-Spam: Yes, score >= 6) a la
# carpeta Junk del buzón, vía un Sieve global "before" de Dovecot. Hasta ahora
# ese spam "intermedio" llegaba a la bandeja de entrada porque la cabecera por
# sí sola no hace nada y no había sieve_before que lo filtrara.
#
# Invoca el código del panel (idempotente): cmd_setup_spam_to_junk instala/
# compila el Sieve y activa sieve_before, respetando Settings.spam_to_junk_enabled.
# Luego regenera Rspamd para aplicar el override por dominio (un dominio con
# spam_to_junk desactivado no marca X-Spam, así su spam no se mueve).
#
# Idempotente y no interactivo.

set -u

echo "→ 0056: mover spam a la carpeta Junk (Sieve global)…"

PYBIN=/opt/svqpanel/venv/bin/python
if [ ! -x "$PYBIN" ]; then
    echo "✓ 0056: sin venv del panel; nada que hacer"
    exit 0
fi

# Sin Dovecot/sieve instalado (servidor sin correo) no aplica.
if ! command -v sievec >/dev/null 2>&1; then
    echo "✓ 0056: dovecot-sieve no instalado (¿servidor sin correo?); nada que hacer"
    exit 0
fi

cd /opt/svqpanel

# 1) Instalar el Sieve global spam→Junk (idempotente).
"$PYBIN" -m api.cli setup_spam_to_junk || echo "  ⚠ setup_spam_to_junk con incidencias"

# 2) Regenerar Rspamd para aplicar el override por dominio (add-header a 999 en
#    los dominios excluidos). No crítico si falla.
"$PYBIN" - <<'PYEOF' || echo "  ⚠ no se pudo regenerar Rspamd (no crítico)"
import sys
sys.path.insert(0, "/opt/svqpanel")
from api.models.database import SessionLocal, load_all_models
load_all_models()
from api.models.models_mail import MailDomain
from scripts.rspamd_manager import RspamdManager
db = SessionLocal()
RspamdManager().rebuild_from_db(db.query(MailDomain).all())
print("  ✓ Rspamd regenerado (override spam→Junk por dominio)")
db.close()
PYEOF

echo "✓ 0056: spam → carpeta Junk configurado"
exit 0
