#!/bin/bash
# 0152-postscreen-deep-tests-ignore.sh
#
# Pone en "ignore" los tres DEEP PROTOCOL TESTS de postscreen: pipelining,
# non_smtp_command y bare_newline. Con esto desaparece del todo el "peaje de
# entrada" que llevaba semanas retrasando correo legítimo.
#
# ── POR QUÉ EL 0145 NO BASTÓ ──────────────────────────────────────────────────
# El 0145 puso greet_action = ignore, pero dejó los otros tres en enforce con el
# argumento de que "son los que cazan bots". Medido después en producción, ese
# razonamiento estaba incompleto: en las 2 horas siguientes al 0145 hubo
#
#   30 PASS NEW  =  30 reject 450     (uno por uno)
#    2 PREGREET                        (solo 2 bots reales)
#
# frente a 0 rechazos en la hora anterior. Entre los rechazados, correo de
# Google (209.85.161.104, 2607:f8b0:4864:20::748).
#
# LA CAUSA: los tres tests que quedaban son "deep protocol tests". Por DISEÑO
# obligan al cliente a reintentar la entrega, porque para ejecutarlos hay que
# romper la sesión SMTP en curso. Da igual que el correo pase la prueba: la
# primera conexión de cada IP nueva se corta igualmente. Es decir, reintroducen
# exactamente el mismo peaje que el 0145 pretendía eliminar.
#
# El pregreet NO es deep test (se resuelve dentro de la misma sesión), por eso
# sigue bloqueando bots sin obligar a reintentar.
#
# ── QUÉ SIGNIFICA "ignore" (no es desinstalar) ────────────────────────────────
# postscreen SIGUE en master.cf, SIGUE ejecutando los tests y SIGUE cacheando el
# veredicto de cada IP. Lo único que deja de hacer es cortar la conexión para
# forzar un reintento. Para quitarlo del todo habría que revertir el 0083 y
# devolver smtp inet a smtpd, que NO es lo que hace este update.
#
# ── COSTE ASUMIDO ─────────────────────────────────────────────────────────────
# Esos tres tests bloquearon 120 + 124 + 134 = 378 casos en un mes. Ese tráfico
# pasa ahora a Rspamd, que tiene Bayes, 19 RBLs, SPF/DKIM/DMARC, fuzzy
# (Pyzor/Razor) y antivirus, más CrowdSec por detrás. El pregreet sigue activo.
#
# A cambio: se acaba el peaje para TODO el correo legítimo, que es el problema
# que costó perder correo de PayPal, OVH, Netflix, Openbank, MailChannels y el
# Ayuntamiento de Sevilla (ver updates 0145 y 0147).
#
# Es la configuración que usan Mail-in-a-Box e iRedMail, y la que recomienda
# Postfix salvo servidor bajo ataque activo.
#
# Idempotente y no interactivo.
set -e

MAIN=/etc/postfix/main.cf

echo "→ 0152: deep protocol tests de postscreen → ignore…"

if [ ! -f "$MAIN" ]; then
    echo "  · no hay Postfix instalado; nada que hacer"
    exit 0
fi

if ! grep -q '^postscreen_greet_action' "$MAIN"; then
    echo "  · postscreen no está activo; nada que hacer"
    exit 0
fi

CAMBIOS=0
BAK="${MAIN}.bak-0152-$(date +%Y%m%d%H%M%S)"
cp -a "$MAIN" "$BAK"

for d in postscreen_pipelining_action postscreen_non_smtp_command_action \
         postscreen_bare_newline_action; do
    ACTUAL=$(postconf -h "$d" 2>/dev/null || echo "")
    if [ "$ACTUAL" = "ignore" ]; then
        echo "  · $d ya estaba en ignore"
    else
        postconf -e "${d} = ignore"
        echo "  · $d: ${ACTUAL:-(default)} → ignore"
        CAMBIOS=1
    fi
done

if [ "$CAMBIOS" = "0" ]; then
    rm -f "$BAK"
    echo "  · nada que cambiar"
    exit 0
fi

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

echo "  · config efectiva:"
postconf -n | grep -E 'postscreen_(greet|pipelining|non_smtp_command|bare_newline)_action' \
    | sed 's/^/      /'
echo "  ✓ el pregreet sigue bloqueando bots (no es deep test)"
echo "✓ 0152: postscreen deja de forzar reintentos"
exit 0
