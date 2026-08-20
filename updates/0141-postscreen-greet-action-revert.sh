#!/bin/bash
# 0141-postscreen-greet-action-revert.sh
#
# Revierte el 0139: postscreen_greet_action vuelve de ignore a enforce.
#
# POR QUÉ SE REVIERTE:
# El 0139 puso greet_action = ignore creyendo que era la causa del correo diferido.
# Medido después en producción, NO lo era: con ignore aplicado seguían apareciendo
# rechazos 450 (4 en los primeros 25 minutos, ratio 18% — dentro del rango 9-33%
# que ya había antes del cambio). O sea: no arregló el problema.
#
# Y a cambio tenía un coste real: con ignore, el test de pregreet deja de bloquear
# bots por sí solo (~44/día en el servidor de referencia). Se pagaba un precio sin
# obtener el beneficio.
#
# La causa real era que las granjas grandes (Microsoft/Google/Amazon SES) reintentan
# desde una IP distinta cada vez, así que nunca salen del "IP nueva" → lo arregla el
# 0140 con una allowlist quirúrgica de esos rangos, dejando el portero intacto para
# el resto de Internet.
#
# ORDEN IMPORTANTE: este update va DESPUÉS del 0140. Primero se exime a las granjas
# grandes, y solo entonces se vuelve a armar el enforce para todos los demás.
#
# Idempotente y no interactivo.
set -e

MAIN=/etc/postfix/main.cf

echo "→ 0141: postscreen_greet_action vuelve a enforce (revierte el 0139)…"

if [ ! -f "$MAIN" ]; then
    echo "  · no hay Postfix instalado; nada que hacer"
    exit 0
fi

if ! grep -q '^postscreen_greet_action' "$MAIN"; then
    echo "  · postscreen no está activo; nada que hacer"
    exit 0
fi

# Seguridad: no rearmar enforce si la allowlist del 0140 no está puesta, o
# volveríamos a diferir a Microsoft/Google (que es justo lo que se quiere evitar).
if ! postconf -h postscreen_access_list 2>/dev/null | grep -q 'postscreen_access.cidr'; then
    echo "  ⚠ la allowlist del 0140 no está activa; NO se rearma enforce"
    echo "    (ejecuta antes updates/0140-postscreen-allowlist-grandes.sh)"
    exit 0
fi

ACTUAL=$(postconf -h postscreen_greet_action 2>/dev/null || echo "")
if [ "$ACTUAL" = "enforce" ]; then
    echo "  · postscreen_greet_action ya está en enforce; nada que hacer"
    exit 0
fi

echo "  · valor actual: ${ACTUAL:-(default)} → enforce"
BAK="${MAIN}.bak-0141-$(date +%Y%m%d%H%M%S)"
cp -a "$MAIN" "$BAK"
postconf -e 'postscreen_greet_action = enforce'

if ! postfix check 2>/dev/null; then
    echo "  ✗ postfix check falló; revirtiendo"
    cp -a "$BAK" "$MAIN"
    exit 1
fi

systemctl reload postfix 2>/dev/null || systemctl restart postfix 2>/dev/null || true
sleep 2
if ! systemctl is-active --quiet postfix; then
    echo "  ✗ Postfix no quedó activo; revirtiendo"
    cp -a "$BAK" "$MAIN"
    systemctl restart postfix 2>/dev/null || true
    exit 1
fi

echo "  ✓ pregreet vuelve a bloquear bots (con las granjas grandes exentas)"
echo "✓ 0141: greet_action restaurado a enforce"
exit 0
