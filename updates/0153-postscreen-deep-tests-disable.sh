#!/bin/bash
# 0153-postscreen-deep-tests-disable.sh
#
# Desactiva (enable = no) los tres deep protocol tests de postscreen. Es la pieza
# que le faltaba al 0152 y la que de verdad acaba con el "peaje de entrada".
#
# ── LA DIFERENCIA ENTRE action E enable ───────────────────────────────────────
# El 0152 puso las ACCIONES en ignore, pero dejó los tests HABILITADOS. Y ahí
# está el matiz que costó cinco diagnósticos:
#
#   *_action = ignore  → qué hacer con el RESULTADO de la prueba
#   *_enable = no      → si la prueba SE HACE siquiera
#
# Con enable = yes, postscreen ejecuta los deep protocol tests igualmente, y para
# ejecutarlos TIENE que cortar la sesión SMTP en curso (así obliga al cliente a
# reintentar). El rechazo se produce antes de que action llegue a opinar.
#
# ── LA PRUEBA: LOS DOS SERVIDORES EN PARALELO ─────────────────────────────────
# Tras aplicar el 0152 a ambos, en 2 horas de tráfico real:
#
#                       SERVIDOR 1        SERVIDOR 2
#   conexiones            93                51
#   rechazos 450           0                10
#   entregas               8                11
#   bots (PREGREET)        5                 1
#   *_enable              no               yes      ← la única diferencia
#   *_action              ignore           ignore
#
# El servidor 1, con casi el DOBLE de tráfico, no rechazó ni un solo correo. Y
# aun así el pregreet cazó 5 bots (el pregreet no es deep test: se resuelve
# dentro de la misma sesión, sin cortar nada).
#
# El servidor 1 los tenía ya en "no" de antes — coincide con la nota del
# proyecto: "greet_action en IGNORE a propósito porque los clientes se quejaban
# de retrasos". Llevaba meses funcionando bien así.
#
# ── EL CASO QUE LO DESTAPÓ ────────────────────────────────────────────────────
# HubSpot intentando entregar a mjverpin@coriaweb.es (buzón de cliente):
#   23:03 → 143.244.94.155
#   23:13 → 143.244.94.243
#   23:33 → 143.244.94.203
#   23:55 → 143.244.94.176
# 4 intentos, 0 entregas. Rota IP en cada reintento, así que nunca sale de "IP
# nueva" y el peaje se cobra siempre.
#
# ── QUÉ QUEDA ACTIVO ──────────────────────────────────────────────────────────
# postscreen SIGUE en master.cf y SIGUE haciendo el pregreet (su test más útil,
# 5 bots en 2h) y cacheando veredictos de IP. Detrás siguen Rspamd, Bayes, 19
# RBLs, SPF/DKIM/DMARC, fuzzy, antivirus y CrowdSec.
#
# Idempotente y no interactivo.
set -e

MAIN=/etc/postfix/main.cf

echo "→ 0153: deep protocol tests de postscreen → enable = no…"

if [ ! -f "$MAIN" ]; then
    echo "  · no hay Postfix instalado; nada que hacer"
    exit 0
fi

if ! grep -q '^postscreen_greet_action' "$MAIN"; then
    echo "  · postscreen no está activo; nada que hacer"
    exit 0
fi

CAMBIOS=0
BAK="${MAIN}.bak-0153-$(date +%Y%m%d%H%M%S)"
cp -a "$MAIN" "$BAK"

for d in postscreen_pipelining_enable postscreen_non_smtp_command_enable \
         postscreen_bare_newline_enable; do
    ACTUAL=$(postconf -h "$d" 2>/dev/null || echo "")
    if [ "$ACTUAL" = "no" ]; then
        echo "  · $d ya estaba en no"
    else
        postconf -e "${d} = no"
        echo "  · $d: ${ACTUAL:-(default)} → no"
        CAMBIOS=1
    fi
done

if [ "$CAMBIOS" = "0" ]; then
    rm -f "$BAK"
    echo "  · nada que cambiar (ya estaba como el servidor de referencia)"
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

# El puerto 25 debe seguir escuchando: si no, el correo entrante se cae.
if ! ss -lnt 2>/dev/null | grep -q ':25 '; then
    echo "  ✗ el puerto 25 no escucha; revirtiendo"
    cp -a "$BAK" "$MAIN"
    systemctl restart postfix 2>/dev/null || true
    exit 1
fi

echo "  · config efectiva:"
postconf -n | grep -E 'postscreen_(pipelining|non_smtp_command|bare_newline)_enable' \
    | sed 's/^/      /'
echo "  ✓ el pregreet sigue activo (es el test que caza bots sin cortar la sesión)"
echo "✓ 0153: postscreen deja de cobrar peaje de entrada"
exit 0
