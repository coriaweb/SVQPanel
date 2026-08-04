#!/bin/bash
# 0132-flag-nonjunk-no-entrena-ham.sh
#
# El aprendizaje de spam por FLAG (update 0036) trataba el flag NonJunk como
# "el usuario dice que este correo es legítimo" → rspamc learn_ham. Pero el
# filtro antispam PROPIO de Thunderbird pone NonJunk AUTOMÁTICAMENTE a cada
# correo nuevo que su clasificador cree bueno, sin intervención del usuario:
# cada spam que Thunderbird no reconocía entrenaba el Bayes del SERVIDOR como
# ham un segundo después de la entrega (visto en producción: campañas enteras
# aprendidas como ham, incluso de madrugada; el usuario lo movía a Junk y solo
# entonces se rectificaba). Resultado: Bayes envenenado que puntuaba spam
# evidente con <1 punto y correo que se colaba a la bandeja de entrada.
#
# Este update hace dos cosas:
#   1) Reaplica la config de aprendizaje (setup_spam_learning): el sieve
#      learn-flag ya SOLO aprende spam por el flag Junk; el ham queda en las
#      vías fiables (sacar de Junk + autolearn de Rspamd con score <= 0.5).
#   2) Resetea el Bayes contaminado en el Redis de Rspamd (tokens RS_*,
#      índices BAYES_*_keys y el caché learned_ids). Se reconstruye solo en
#      pocos días con el autolearn y los movimientos a/desde Junk
#      (min_learns=20 antes de volver a puntuar).
#
# Idempotente (re-ejecutarlo reaplica config y vuelve a vaciar el Bayes, que
# se reentrena) y no interactivo.

set -euo pipefail

echo "→ 0132: el flag NonJunk automático de Thunderbird ya no entrena ham…"

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }

# 1) Reaplicar sieve + config IMAPSieve (invoca el código del panel).
cd /opt/svqpanel
"$PYBIN" -m api.cli setup_spam_learning || \
    echo "  ⚠ setup_spam_learning con incidencias (no crítico)."

# 2) Resetear el Bayes contaminado. Solo si este servidor tiene correo
#    (Rspamd + su Redis); en servidores sin correo no hay nada que limpiar.
if command -v redis-cli >/dev/null 2>&1 && command -v rspamc >/dev/null 2>&1; then
    # El Redis de Rspamd puede llevar requirepass (redis_manager.secure_rspamd_redis).
    PASS_FILE=/etc/svqpanel/redis_rspamd.pass
    if [ -r "$PASS_FILE" ]; then
        export REDISCLI_AUTH="$(cat "$PASS_FILE")"
    fi

    if redis-cli ping 2>/dev/null | grep -q PONG; then
        ANTES=$(rspamc -h localhost:11334 stat 2>/dev/null | grep -c "Statfile" || true)
        # Tokens del Bayes (RS_<hash>, prefijo por defecto del classifier) +
        # clave de usuario "RS" + índices + caché de mensajes ya aprendidos.
        # Los demás datos de Rspamd en este Redis (greylist, ratelimit…) usan
        # otros prefijos y NO se tocan.
        N=$(redis-cli --scan --pattern 'RS*' | wc -l)
        redis-cli --scan --pattern 'RS*' | xargs -r -n 500 redis-cli unlink >/dev/null
        redis-cli unlink BAYES_SPAM_keys BAYES_HAM_keys learned_ids >/dev/null 2>&1 || true
        echo "  Bayes reseteado: $N claves de tokens eliminadas (statfiles antes: $ANTES)."
        echo "  Se reentrena solo (autolearn + movimientos a/desde Junk)."
    else
        echo "  ⚠ Redis de Rspamd no responde — Bayes sin resetear (no crítico)."
    fi
else
    echo "  Sin Rspamd/Redis en este servidor — nada que resetear."
fi

echo "✓ 0132: aprendizaje de ham solo por vías humanas (sacar de Junk) + autolearn"
exit 0
