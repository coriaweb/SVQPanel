#!/bin/bash
# 0150-autolearn-spam-6.sh
#
# Baja el umbral de autolearn de SPAM del Bayes de 10 a 6, para que coincida con
# el umbral de rechazo que fijó el 0149.
#
# ── EL PROBLEMA QUE CREÓ EL 0149 ──────────────────────────────────────────────
# El 0149 bajó el rechazo de 10.00 a 6.00. Pero el autolearn seguía en 10:
#
#   autolearn = [0.5, 10]   ← el Bayes solo aprendía spam con score >= 10
#   reject    = 6.00        ← pero desde 6 ya se rechazaba
#
# Resultado: los correos de la franja 6-10 se rechazan SIN llegar a aprenderse.
# Medido en producción, esa franja son 33 de los 56 casos de spam (59%): el
# Bayes perdía de golpe más de la mitad de su alimentación.
#
# El efecto es justo el contrario del que se buscaba al endurecer el umbral: el
# Bayes reconoce menos patrones → más spam se cuela con score bajo → acaba en la
# bandeja de entrada del cliente.
#
# ── EL CASO QUE LO DESTAPÓ ────────────────────────────────────────────────────
# El mismo remitente (cofund.solutions) oscilaba entre dos scores muy distintos
# según si el Bayes reconocía el patrón o no:
#
#   7.15  BAYES_SPAM(4.92) + R_MIXED_CHARSET(0.63)   → bloqueado
#   1.60  BAYES_SPAM(0.00) [24.24%]                  → entró en bandeja
#
# O sea: cuando el Bayes reconoce el patrón, el correo cae. Cuando no, se cuela.
# Alimentarlo bien es lo que decide el resultado.
#
# ── REGLA A RECORDAR ──────────────────────────────────────────────────────────
# El autolearn de spam DEBE COINCIDIR con el umbral de rechazo de actions.conf.
# Si alguien vuelve a mover "reject", hay que mover también este valor, o el
# Bayes se queda sin aprender la franja que se rechaza.
#
# ── RIESGO ────────────────────────────────────────────────────────────────────
# Si un correo legítimo cayera en la franja 6-10, ahora se aprendería como spam
# y envenenaría el Bayes (ya pasó algo así con el flag NonJunk de Thunderbird,
# update 0132). Se asume porque al medir la franja 6-10 no había ni un legítimo:
# eran dominios .store/.shop desechables con remitentes de nombre aleatorio. Aun
# así conviene vigilar los rechazos las primeras semanas.
#
# Patrón del proyecto: en vez de reescribir el fichero a mano, se invoca el
# código del panel (spam_learning.install(), idempotente), que es la fuente de
# verdad y ya trae el valor nuevo tras el git pull.
set -e

echo "→ 0150: autolearn de spam 10 → 6 (igualar al umbral de rechazo)…"

if [ ! -d /etc/rspamd ]; then
    echo "  · Rspamd no instalado; nada que hacer"
    exit 0
fi

CLASSIFIER=/etc/rspamd/local.d/classifier-bayes.conf
PYBIN=/opt/svqpanel/venv/bin/python

ACTUAL=$(grep -oP 'autolearn\s*=\s*\[[0-9.]+,\s*\K[0-9.]+' "$CLASSIFIER" 2>/dev/null || echo "")
if [ "$ACTUAL" = "6" ]; then
    echo "  · el autolearn de spam ya está en 6; nada que hacer"
    exit 0
fi

[ -f "$CLASSIFIER" ] && cp -a "$CLASSIFIER" "${CLASSIFIER}.bak-0150-$(date +%Y%m%d%H%M%S)"

if [ -x "$PYBIN" ]; then
    # Vía preferente: que lo escriba el propio panel (una sola fuente de verdad).
    cd /opt/svqpanel
    "$PYBIN" - <<'PYEOF' || echo "  ⚠ el panel no pudo reescribirlo; se intenta a mano"
import sys
sys.path.insert(0, "/opt/svqpanel")
from scripts.spam_learning import SpamLearningManager
r = SpamLearningManager().install(reload=True)
print("  · spam_learning.install():", r.get("success", r))
PYEOF
fi

# Red de seguridad: si el panel no estaba disponible o no dejó el valor bien.
ACTUAL=$(grep -oP 'autolearn\s*=\s*\[[0-9.]+,\s*\K[0-9.]+' "$CLASSIFIER" 2>/dev/null || echo "")
if [ "$ACTUAL" != "6" ]; then
    sed -i 's/^autolearn = \[0\.5, 10\];/autolearn = [0.5, 6];/' "$CLASSIFIER"
    systemctl reload rspamd 2>/dev/null || systemctl restart rspamd 2>/dev/null || true
    echo "  · autolearn ajustado directamente en $CLASSIFIER"
fi

sleep 2
if ! systemctl is-active --quiet rspamd; then
    echo "  ✗ Rspamd no quedó activo; revirtiendo"
    cp -a "$(ls -t ${CLASSIFIER}.bak-0150-* | head -1)" "$CLASSIFIER"
    systemctl restart rspamd 2>/dev/null || true
    exit 1
fi

# Verificar el valor EFECTIVO que ve Rspamd, no solo el del fichero.
EFECTIVO=$(rspamadm configdump classifier 2>/dev/null | grep -oP 'autolearn.*?\[\s*[0-9.]+,\s*\K[0-9.]+' | head -1)
REJECT=$(grep -oP '^"reject"\s*=\s*\K[0-9.]+' /etc/rspamd/local.d/actions.conf 2>/dev/null || echo "?")
echo "  · autolearn spam efectivo: ${EFECTIVO:-?}   umbral de rechazo: ${REJECT}"

if [ -n "$EFECTIVO" ] && [ "${EFECTIVO%.*}" != "${REJECT%.*}" ]; then
    echo "  ⚠ autolearn y rechazo NO coinciden: el Bayes dejará de aprender esa franja"
fi

echo "✓ 0150: el Bayes vuelve a aprender de todo lo que se rechaza"
exit 0
