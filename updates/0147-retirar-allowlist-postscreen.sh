#!/bin/bash
# 0147-retirar-allowlist-postscreen.sh
#
# Retira la allowlist de postscreen que creó el 0140. Ya no sirve para nada.
#
# ── POR QUÉ SE RETIRA ─────────────────────────────────────────────────────────
# El 0140 metió en allowlist a Microsoft, Google, Amazon SES, register.it,
# srv2.de y Sophos para que no se les rechazara la primera conexión. Era un
# parche sobre un diagnóstico incompleto: se creyó que el problema eran "las
# granjas que rotan IP", cuando en realidad postscreen (con greet_action =
# enforce) rechazaba la primera conexión de CUALQUIER IP que no tuviera en
# caché — o sea, de Internet entero.
#
# El 0145 puso greet_action = ignore, que ataca la causa: ya no se rechaza a
# nadie por no conocerlo. Con eso, la allowlist no aporta nada:
#   · no cambia el comportamiento (ya nadie paga peaje de entrada),
#   · es deuda de mantenimiento (rangos IP que caducan y hay que revisar),
#   · y es un riesgo latente: una lista de rangos exentos que se queda obsoleta
#     acaba eximiendo a IPs que ya no son de quien creíamos.
#
# La lección del 0140 que sí conviene recordar: al copiar rangos de un SPF hay
# que copiarlo ENTERO. Se pusieron 2 de los 12 rangos de Amazon SES y a las
# pocas horas se coló un rechazo real de 54.240.65.34, en un /18 contiguo.
#
# ── QUÉ HACE ──────────────────────────────────────────────────────────────────
# 1) postscreen_access_list vuelve a 'permit_mynetworks' (las redes propias
#    SIEMPRE deben seguir exentas: son el propio servidor y su webmail).
# 2) Borra /etc/postfix/postscreen_access.cidr.
#
# SEGURIDAD: si greet_action NO está en ignore (alguien revirtió el 0145), este
# update NO hace nada — quitar la allowlist con enforce activo volvería a diferir
# correo de Microsoft/Google. Primero el 0145, después este.
#
# Idempotente y no interactivo.
set -e

MAIN=/etc/postfix/main.cf
ALLOW=/etc/postfix/postscreen_access.cidr

echo "→ 0147: retirar la allowlist de postscreen (ya no hace falta)…"

if [ ! -f "$MAIN" ]; then
    echo "  · no hay Postfix instalado; nada que hacer"
    exit 0
fi

if ! grep -q '^postscreen_greet_action' "$MAIN"; then
    echo "  · postscreen no está activo; nada que hacer"
    exit 0
fi

# Guard: sin ignore, la allowlist todavía está haciendo falta. No la tocamos.
GREET=$(postconf -h postscreen_greet_action 2>/dev/null || echo "")
if [ "$GREET" != "ignore" ]; then
    echo "  ⚠ greet_action = '${GREET}' (no es ignore): NO se retira la allowlist"
    echo "    Aplica antes updates/0145-postscreen-greet-action-ignore-definitivo.sh"
    exit 0
fi

ACTUAL=$(postconf -h postscreen_access_list 2>/dev/null || echo "")
if ! echo "$ACTUAL" | grep -q 'postscreen_access.cidr'; then
    echo "  · la allowlist ya no está referenciada; nada que hacer"
    rm -f "$ALLOW" 2>/dev/null || true
    exit 0
fi

echo "  · postscreen_access_list: '${ACTUAL}' → 'permit_mynetworks'"
BAK="${MAIN}.bak-0147-$(date +%Y%m%d%H%M%S)"
cp -a "$MAIN" "$BAK"
postconf -e 'postscreen_access_list = permit_mynetworks'

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

rm -f "$ALLOW"
echo "  ✓ allowlist retirada (backup de main.cf en $BAK)"
echo "✓ 0147: postscreen sin lista que mantener"
exit 0
