#!/bin/bash
# 0138-postscreen-greet-wait.sh
#
# Baja postscreen_greet_wait a 2s para que el correo legítimo NO se difiera.
#
# EL BUG: el update 0083 activó postscreen pero no fijó greet_wait, así que quedó
# el default de Postfix: ${stress?{2}:{6}}s (6s en operación normal). Con 6s de
# espera, la primera conexión de una IP desconocida se rechaza con
# "450 4.3.2 Service currently unavailable" y solo DESPUÉS se registra el PASS:
#
#   12:08:25  CONNECT from [52.101.92.102]      ← Microsoft/Outlook
#   12:08:32  reject: 450 4.3.2 Service currently unavailable
#   12:08:32  PASS NEW [52.101.92.102]          ← pasa el test justo tras rechazarlo
#
# Eso es greylisting de facto. Un emisor pequeño reintenta desde la MISMA IP y
# entra al segundo intento, pero las granjas grandes (Microsoft, Google, Hotmail)
# reintentan desde una IP DISTINTA cada vez, así que cada reintento es otro
# "PASS NEW" = otro rechazo, y la caché de 7d no les sirve de nada:
#
#   52.101.92.102 → .93.100 → .94.105 → .90.132 → .90.121 → .94.136 → .92.125 → .90.99
#
# Caso real: un correo de Outlook rechazado 8 veces (12:08→17:41) que entró a las
# 18:42 — 6h30 de retraso. 828 rechazos en un día, 806 de ellos "PASS NEW",
# repartidos entre 20+ dominios del servidor.
#
# EL FIX: greet_wait = 2s. Los emisores legítimos esperan a que el servidor
# termine de saludar antes de hablar, así que pasan a la primera. Los bots
# escupen el EHLO de inmediato (en los logs: 0.18-0.37s), así que el pregreet
# los sigue cazando con margen de sobra.
#
# Idempotente: si ya está en 2s, no hace nada.
set -e

MAIN=/etc/postfix/main.cf

echo "→ 0138: postscreen_greet_wait = 2s (evitar diferir correo legítimo)…"

if [ ! -f "$MAIN" ]; then
    echo "  · no hay Postfix instalado; nada que hacer"
    exit 0
fi

# Si postscreen no está activo (0083 no aplicado o Postfix sin correo), no tocamos.
if ! grep -q '^postscreen_greet_action' "$MAIN"; then
    echo "  · postscreen no está activo; nada que hacer"
    exit 0
fi

ACTUAL=$(postconf -h postscreen_greet_wait 2>/dev/null || echo "")
if [ "$ACTUAL" = "2s" ]; then
    echo "  · postscreen_greet_wait ya está en 2s; nada que hacer"
    exit 0
fi

echo "  · valor actual: ${ACTUAL:-(default)} → 2s"
cp -a "$MAIN" "${MAIN}.bak-0138-$(date +%Y%m%d%H%M%S)"
postconf -e 'postscreen_greet_wait = 2s'

# Validar antes de recargar: si la config quedó mal, revertimos y fallamos.
if ! postfix check 2>/dev/null; then
    echo "  ✗ postfix check falló; revirtiendo"
    cp -a "$(ls -t ${MAIN}.bak-0138-* | head -1)" "$MAIN"
    exit 1
fi

# Vaciar la caché de postscreen: arrastra hasta 7 días de veredictos tomados con
# el criterio viejo (retention_time = 7d). Sin esto, las IPs ya marcadas seguirían
# comportándose igual durante una semana. Se recrea sola al primer CONNECT.
systemctl stop postfix 2>/dev/null || true
rm -f /var/lib/postfix/postscreen_cache.db
systemctl start postfix 2>/dev/null || true

sleep 2
if systemctl is-active --quiet postfix; then
    echo "  ✓ postscreen_greet_wait = 2s aplicado (caché de postscreen vaciada)"
else
    echo "  ✗ Postfix no arrancó tras el cambio"
    exit 1
fi

echo "✓ 0138: postscreen_greet_wait ajustado"
exit 0
