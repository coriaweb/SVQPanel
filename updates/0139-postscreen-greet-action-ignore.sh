#!/bin/bash
# 0139-postscreen-greet-action-ignore.sh
#
# postscreen_greet_action: enforce → ignore. Deja de rechazar el correo legítimo.
#
# EL BUG (el de verdad; el 0138 se equivocó de causa):
# Con greet_action = enforce, postscreen RECHAZA a toda IP desconocida en su
# PRIMERA conexión con "450 4.3.2 Service currently unavailable", pase o no las
# pruebas. El PASS se registra a continuación, pero el correo ya se rechazó:
#
#   18:56:20.79  CONNECT from [52.101.94.128]     ← Microsoft
#   18:56:22.89  reject: 450 4.3.2 Service currently unavailable
#   18:56:22.90  PASS NEW [52.101.94.128]         ← pasa el test, pero ya da igual
#
# Eso es greylisting. Un emisor pequeño reintenta desde la MISMA IP y entra al
# segundo intento, pero las granjas grandes (Microsoft, Google, Hotmail) reintentan
# desde una IP DISTINTA cada vez, así que cada reintento vuelve a ser "IP nueva" =
# otro rechazo, y la caché de 7d no les sirve de nada:
#
#   52.101.94.128 → .93.77 → .90.130 → .93.104 → .93.120 → .92.74 → .92.129 → …
#
# POR QUÉ EL 0138 NO BASTÓ: bajar greet_wait de 6s a 2s solo acorta la espera; el
# rechazo se produce igual al terminarla. Medido en producción: 450 rechazos el día
# del cambio (449 DESPUÉS de aplicarlo) frente a 221 el día anterior.
#
# PRUEBA de que el rechazo no es por fallar tests: de las 445 IPs rechazadas en un
# día, CERO tenían un PREGREET asociado. No fallaban nada — se las rechazaba solo
# por ser nuevas.
#
# EL FIX: greet_action = ignore. postscreen sigue HACIENDO la prueba y registrando
# el veredicto en su caché, pero no rechaza por ella: el correo entra a la primera.
#
# COSTE ACEPTADO: el pregreet deja de bloquear bots por sí solo (~44/día en el
# servidor de referencia). Se mantienen activos los otros tres tests de protocolo
# (pipelining, non_smtp_command, bare_newline), que NO molestan a Outlook/Gmail, y
# detrás siguen Rspamd, el greylisting propio y CrowdSec. Compensa: 44 bots frente
# a 450 correos legítimos retrasados horas.
#
# Idempotente: si ya está en ignore, no hace nada. No interactivo.
set -e

MAIN=/etc/postfix/main.cf

echo "→ 0139: postscreen_greet_action = ignore (dejar de rechazar correo legítimo)…"

if [ ! -f "$MAIN" ]; then
    echo "  · no hay Postfix instalado; nada que hacer"
    exit 0
fi

# Si postscreen no está activo (0083 no aplicado o Postfix sin correo), no tocamos.
if ! grep -q '^postscreen_greet_action' "$MAIN"; then
    echo "  · postscreen no está activo; nada que hacer"
    exit 0
fi

ACTUAL=$(postconf -h postscreen_greet_action 2>/dev/null || echo "")
if [ "$ACTUAL" = "ignore" ]; then
    echo "  · postscreen_greet_action ya está en ignore; nada que hacer"
    exit 0
fi

echo "  · valor actual: ${ACTUAL:-(default)} → ignore"
BAK="${MAIN}.bak-0139-$(date +%Y%m%d%H%M%S)"
cp -a "$MAIN" "$BAK"
postconf -e 'postscreen_greet_action = ignore'

# Validar antes de recargar: si la config quedó mal, revertimos y fallamos.
if ! postfix check 2>/dev/null; then
    echo "  ✗ postfix check falló; revirtiendo"
    cp -a "$BAK" "$MAIN"
    exit 1
fi

# reload basta (no hace falta parar Postfix): postscreen recoge la directiva nueva.
# La caché de postscreen NO se toca: sus entradas son veredictos de test, y con
# ignore ya no se usan para rechazar.
systemctl reload postfix 2>/dev/null || systemctl restart postfix 2>/dev/null || true

sleep 2
if systemctl is-active --quiet postfix; then
    echo "  ✓ postscreen_greet_action = ignore aplicado (backup en $BAK)"
else
    echo "  ✗ Postfix no quedó activo tras el cambio; revirtiendo"
    cp -a "$BAK" "$MAIN"
    systemctl restart postfix 2>/dev/null || true
    exit 1
fi

echo "✓ 0139: postscreen deja de diferir el correo legítimo"
exit 0
