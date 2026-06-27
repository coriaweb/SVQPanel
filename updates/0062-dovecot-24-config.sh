#!/bin/bash
# 0062-dovecot-24-config.sh
#
# Regenera la config de correo de Dovecot en sintaxis 2.4 (Debian 13/trixie).
#
# Contexto: Dovecot 2.4 cambió la sintaxis respecto a 2.3 (bookworm). Los
# generadores del panel (spam_learning, dovecot_spam_sieve, mail_tls_manager,
# install_mail.sh) ya detectan la versión y emiten 2.4, pero un servidor que se
# actualizó de Debian 12 a 13 puede tener todavía dropins con sintaxis 2.3
# (o neutralizados como .disabled-trixie por el dist-upgrade). Este update los
# regenera invocando el código del panel (patrón recomendado).
#
# Idempotente y SEGURO en Dovecot 2.3 (Debian 12): si la versión es < 2.4 no
# hace nada (los managers ya emiten 2.3 y este update no toca la config).

set -euo pipefail

echo "→ 0062: Regenerando config de correo para Dovecot 2.4 (si aplica)..."

# ¿Hay Dovecot? Si no, nada que hacer.
if ! command -v dovecot >/dev/null 2>&1; then
    echo "  Dovecot no instalado — nada que hacer."
    exit 0
fi

DOVECOT_MAJOR=$(dovecot --version 2>/dev/null | grep -oE '^[0-9]+\.[0-9]+' | head -1)
# >= 2.4 si al ordenar (2.4, version) queda 2.4 primero (2.4 <= version).
# < 2.4 → no aplica (el servidor sigue en sintaxis 2.3, ya soportada)
if ! printf '2.4\n%s\n' "$DOVECOT_MAJOR" | sort -V -C; then
    echo "  Dovecot $DOVECOT_MAJOR (< 2.4): config 2.3, nada que regenerar."
    exit 0
fi

echo "  Dovecot $DOVECOT_MAJOR (>= 2.4): regenerando dropins en sintaxis 2.4..."

VENV_PY=/opt/svqpanel/venv/bin/python
[[ -x "$VENV_PY" ]] || VENV_PY=python3

# Limpiar restos neutralizados por el dist-upgrade
rm -f /etc/dovecot/conf.d/*.disabled-trixie 2>/dev/null || true

# 1) Aprendizaje de spam (IMAPSieve) + 2) spam→Junk: vía el código del panel,
#    que ya emite 2.4 al detectar la versión.
"$VENV_PY" - <<'PYEOF'
import sys
sys.path.insert(0, "/opt/svqpanel")
try:
    from scripts.spam_learning import SpamLearningManager
    r = SpamLearningManager().install(reload=False)
    print("  spam_learning:", r.get("success"))
except Exception as e:
    print("  spam_learning ERROR:", e)
try:
    from scripts.dovecot_spam_sieve import apply as spam_to_junk_apply
    r = spam_to_junk_apply(True)
    print("  spam_to_junk:", r.get("success"))
except Exception as e:
    print("  spam_to_junk ERROR:", e)
PYEOF

# 3) Quota de correo en sintaxis 2.4 (idempotente)
if ! grep -q 'driver = count' /etc/dovecot/conf.d/90-svqpanel-quota.conf 2>/dev/null; then
    cat > /etc/dovecot/conf.d/90-svqpanel-quota.conf <<'EOF'
# SVQPanel: cuotas por buzon (Dovecot 2.4)
mail_plugins {
  quota = yes
}
protocol imap {
  mail_plugins {
    imap_quota = yes
  }
}
quota "User quota" {
  driver = count
}
quota_exceeded_message = Buzon lleno: el usuario %{user} ha superado su cuota de almacenamiento.
EOF
    echo "  quota 2.4 regenerada."
fi

# 4) SNI por dominio (mail_tls_manager) en 2.4: regenerar desde la BD si hay
#    dominios con TLS. Si el manager no expone un punto simple, se regenera al
#    próximo cambio de TLS; aquí solo migramos la sintaxis del fichero existente.
if [[ -f /etc/dovecot/conf.d/99-svqpanel-sni.conf ]]; then
    sed -i 's|ssl_cert[[:space:]]*=[[:space:]]*<|ssl_server_cert_file = |g; s|ssl_key[[:space:]]*=[[:space:]]*<|ssl_server_key_file = |g' \
        /etc/dovecot/conf.d/99-svqpanel-sni.conf
fi

# Validar y recargar
if doveconf -n >/dev/null 2>/tmp/svq-0062-doveconf.err; then
    systemctl restart dovecot
    echo "  ✓ Dovecot recargado con config 2.4 válida."
else
    echo "  ✗ doveconf reporta errores tras regenerar — NO reinicio:"
    head -5 /tmp/svq-0062-doveconf.err
    exit 1
fi

echo "✓ 0062: config de Dovecot 2.4 regenerada."
exit 0
