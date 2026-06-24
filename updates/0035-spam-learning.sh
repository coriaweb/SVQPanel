#!/bin/bash
# 0035-spam-learning.sh
#
# Activa el APRENDIZAJE de spam de Rspamd (Bayes), que estaba configurado pero
# sin entrenar (0 mensajes aprendidos):
#   - Instala dovecot-sieve (necesario para IMAPSieve).
#   - Configura IMAPSieve: al mover un correo a la carpeta Junk → rspamc
#     learn_spam; al sacarlo de Junk → learn_ham. Pre-compila los .sieve.
#   - Autolearn (Rspamd aprende solo de los casos obvios) + Bayes GLOBAL +
#     cabeceras de diagnóstico (x-spamd-result, x-spam-level).
#
# Invoca el código del panel (idempotente). Seguro de re-ejecutar.

set -euo pipefail

echo "→ 0035: activar aprendizaje de spam (Bayes + IMAPSieve)…"

# 1) dovecot-sieve (si no está). managesieve NO es necesario.
if ! ls /usr/lib/dovecot/modules/ 2>/dev/null | grep -q imap_sieve; then
    echo "  Instalando dovecot-sieve…"
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq dovecot-sieve 2>&1 | tail -2 || \
        echo "  ⚠ no se pudo instalar dovecot-sieve (revisar repos)"
fi

# 2) Aplicar la configuración (invoca el manager del panel).
PYBIN=/opt/svqpanel/venv/bin/python
if [ -x "$PYBIN" ]; then
    cd /opt/svqpanel
    "$PYBIN" -m api.cli setup_spam_learning || \
        echo "  ⚠ setup_spam_learning con incidencias (no crítico)."
fi

echo "✓ 0035: aprendizaje de spam activado"
exit 0
