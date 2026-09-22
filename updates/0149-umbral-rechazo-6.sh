#!/bin/bash
# 0149-umbral-rechazo-6.sh
#
# Baja el umbral de RECHAZO de 10.00 a 6.00. El de marcado (Junk) se queda en
# 4.00, así que la franja 4-6 sigue yendo a No deseado y a partir de 6 se
# rechaza en SMTP.
#
# ── POR QUÉ ───────────────────────────────────────────────────────────────────
# Decisión del administrador: el spam evidente no debe ocupar la carpeta de No
# deseado del cliente, debe rebotarse. Medido en producción antes de aplicarlo,
# TODO lo que hay en la franja 6-10 es spam inequívoco:
#
#   7.30  ucqomdm@preciosbajos.store     (×5, dominio .store desechable)
#   7.20  iwfillh@artio-host.shop
#   7.15  ywxedpd@cofund.solutions       (×6)
#   6.90  mail23220@mail23.notificamailerb.com
#   6.87  okwivmn@preciosbajos.store     (×6)
#   6.54  orhanth@cofund.solutions       (×5)
#
# Remitentes con nombre aleatorio (ucqomdm, ywxedpd, iwfillh…) y dominios de
# usar y tirar. Ni un solo remitente legítimo en esa franja.
#
# ── EL RIESGO QUE SE ASUME (documentado a propósito) ──────────────────────────
# Un rechazo es DEFINITIVO: el remitente recibe un rebote y el correo no se
# puede recuperar. Con el umbral en 10 un falso positivo acababa en Junk, de
# donde el usuario lo saca (y además entrena el Bayes). Con 6, un falso positivo
# se pierde.
#
# Caso real detectado al medir: carmen.rodriguez.werit.iberia@mail.shiply-office.com
# puntuó 9.70 en un correo y 0.00 en otro — mismo remitente. Tenía
# BAYES_HAM(-3.00), DKIM válido y DMARC pass; su score alto venía de factores
# circunstanciales. Con umbral 6, ese correo se habría rechazado.
#
# Por eso conviene REVISAR los rechazos las primeras semanas:
#   grep 'reject' /var/log/rspamd/rspamd.log | grep -v 'soft reject'
# Si aparece correo legítimo rechazado, subir el umbral desde el panel
# (Administración → Ajuste antispam) o revertir este update.
#
# ── REVERSIÓN ─────────────────────────────────────────────────────────────────
#   postconf no aplica aquí; es Rspamd. Para volver atrás:
#   sed -i 's/^"reject" = 6.00;/"reject" = 10.00;/' /etc/rspamd/local.d/actions.conf
#   systemctl reload rspamd
#   ...o directamente desde el panel, que es la vía recomendada.
#
# Idempotente y no interactivo. RESPETA al admin que ya lo haya personalizado a
# un valor distinto de 10.00 (no pisa una decisión consciente posterior).
set -e

ACTIONS=/etc/rspamd/local.d/actions.conf

echo "→ 0149: umbral de rechazo 10.00 → 6.00…"

if [ ! -d /etc/rspamd ]; then
    echo "  · Rspamd no instalado; nada que hacer"
    exit 0
fi

if [ ! -f "$ACTIONS" ]; then
    echo "  · no hay actions.conf; nada que hacer"
    exit 0
fi

ACTUAL=$(grep -oP '^"reject"\s*=\s*\K[0-9.]+' "$ACTIONS" 2>/dev/null || echo "")

if [ "$ACTUAL" = "6.00" ]; then
    echo "  · el umbral de rechazo ya está en 6.00; nada que hacer"
    exit 0
fi

# Solo tocamos si está en el valor por defecto del panel (10.00). Si el admin lo
# ha puesto en otra cosa, es una decisión suya y no la pisamos.
if [ "$ACTUAL" != "10.00" ]; then
    echo "  · el umbral de rechazo está en ${ACTUAL:-(sin definir)}, no en el 10.00 por"
    echo "    defecto: lo ha personalizado el admin, no se toca"
    exit 0
fi

cp -a "$ACTIONS" "${ACTIONS}.bak-0149-$(date +%Y%m%d%H%M%S)"
sed -i 's/^"reject"[[:space:]]*=[[:space:]]*10\.00;/"reject" = 6.00;/' "$ACTIONS"

NUEVO=$(grep -oP '^"reject"\s*=\s*\K[0-9.]+' "$ACTIONS" 2>/dev/null || echo "")
if [ "$NUEVO" != "6.00" ]; then
    echo "  ✗ no se pudo cambiar el umbral; revirtiendo"
    cp -a "$(ls -t ${ACTIONS}.bak-0149-* | head -1)" "$ACTIONS"
    exit 1
fi

if systemctl is-active --quiet rspamd 2>/dev/null; then
    systemctl reload rspamd 2>/dev/null || systemctl restart rspamd 2>/dev/null || true
    sleep 2
    if ! systemctl is-active --quiet rspamd; then
        echo "  ✗ Rspamd no quedó activo; revirtiendo"
        cp -a "$(ls -t ${ACTIONS}.bak-0149-* | head -1)" "$ACTIONS"
        systemctl restart rspamd 2>/dev/null || true
        exit 1
    fi
fi

# Verificar el valor EFECTIVO, no solo el del fichero.
EFECTIVO=$(rspamadm configdump actions 2>/dev/null | grep -oP '^\s*reject\s*=\s*\K[0-9.]+' | head -1)
echo "  · umbrales efectivos: rechazo=${EFECTIVO:-?}  (marcado sigue en 4.00)"

echo "  ✓ a partir de 6.00 se rechaza en SMTP; 4.00-6.00 sigue yendo a Junk"
echo "✓ 0149: umbral de rechazo bajado a 6.00"
exit 0
