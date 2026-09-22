#!/bin/bash
# 0145-postscreen-greet-action-ignore-definitivo.sh
#
# postscreen_greet_action = ignore, DEFINITIVO. Deja de cobrar un "peaje de
# entrada" a cada IP que postscreen no tiene en caché.
#
# ── EL BUG, bien diagnosticado esta vez ──────────────────────────────────────
# Con greet_action = enforce, postscreen RECHAZA la primera conexión de toda IP
# que no esté en su caché (450 4.3.2 Service currently unavailable) — PASE O NO
# PASE las pruebas. El veredicto se registra DESPUÉS del rechazo:
#
#   CONNECT from [173.0.84.1]        ← mx12.slc.paypal.com
#   reject: 450 4.3.2 ...
#   PASS NEW [173.0.84.1]            ← aprueba el test, pero ya fue rechazada
#
# Los números de un mes en producción (svq1coriahosting) no dejan lugar a dudas:
#
#   PASS NEW : 930     ← IPs "nuevas" (o con la caché caducada)
#   450      : 953     ← rechazos
#
# Uno por uno: cada IP paga exactamente un rechazo al entrar. Y con
# postscreen_cache_retention_time = 7d, un remitente que escribe cada 8 días
# paga el peaje SIEMPRE. La prueba definitiva, la MISMA IP de PayPal:
#
#   5-sep  173.0.84.1 → 450 reject   (caché caducada → paga peaje)
#   9-sep  173.0.84.1 → PASS OLD     (en caché → entra sin problema)
#
# ── POR QUÉ LA ALLOWLIST (0140) NO ERA LA SOLUCIÓN ───────────────────────────
# El 0140 metió en allowlist a Microsoft/Google/Amazon/register.it/srv2.de/
# Sophos. Pero el problema no son "las granjas que rotan IP": es CUALQUIER IP
# cuya caché haya expirado. Mantener la lista significa perseguir a PayPal, OVH,
# Openbank, Netflix, MailChannels, TrendMicro, el Ayuntamiento de Sevilla… y al
# siguiente que aparezca. Siempre vas por detrás del correo que ya se perdió.
# Correo legítimo con CERO entregas en un mes por este motivo: Netflix (24
# rechazos), OVH (19), pctcartuja/TrendMicro (12), PayPal (10), Openbank (9),
# facoan/MailChannels (8), Ayto. Sevilla (1).
#
# ── QUÉ HACE (Y QUÉ NO HACE) ignore ──────────────────────────────────────────
# ignore NO desactiva la prueba: postscreen SIGUE haciendo el test de pregreet y
# SIGUE registrando el veredicto en su caché. Lo único que cambia es que no
# rechaza a una IP por el mero hecho de no conocerla todavía.
#
# Los otros tres tests de protocolo siguen en enforce y son los que cazan bots
# de verdad (mismo mes, mismo servidor):
#   pipelining   : 120 bloqueos
#   non_smtp_cmd : 124 bloqueos
#   bare_newline : 134 bloqueos
# Y detrás siguen Rspamd, Bayes, SPF/DKIM/DMARC, antivirus y CrowdSec.
#
# ── QUÉ HACE EL RESTO DEL SECTOR ─────────────────────────────────────────────
#   cPanel          : no usa postscreen (Exim), sin greylisting por defecto
#   Plesk           : Postfix SIN postscreen; greylisting módulo opcional
#   Mail-in-a-Box   : greet_action = ignore
#   iRedMail        : no activa postscreen
#   Postfix upstream: el DEFAULT es ignore
# enforce es config de admin experto para un servidor bajo ataque, no para
# hosting compartido con clientes reales.
#
# ── HISTORIAL (para que nadie lo vuelva a revertir) ──────────────────────────
#   0138 greet_wait 6s→2s        : no era la causa; solo acortó la espera.
#   0139 greet_action → ignore   : ERA CORRECTO, pero se midió mal (25 min de
#                                  tráfico nocturno) y se creyó que fallaba.
#   0140 allowlist               : parche; no escala (ver arriba).
#   0141 vuelta a enforce        : ERROR. Revirtió el 0139 bueno y además iba
#                                  contra una decisión previa ya documentada
#                                  ("greet_action en IGNORE a propósito: los
#                                  clientes se quejaban de retrasos").
#   0145 (este)                  : ignore, definitivo.
#
# ⚠️ NO volver a poner enforce. Si alguien lo propone, leer este bloque entero.
#
# Idempotente y no interactivo.
set -e

MAIN=/etc/postfix/main.cf

echo "→ 0145: postscreen_greet_action = ignore (fin del peaje de entrada)…"

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
BAK="${MAIN}.bak-0145-$(date +%Y%m%d%H%M%S)"
cp -a "$MAIN" "$BAK"
postconf -e 'postscreen_greet_action = ignore'

if ! postfix check 2>/dev/null; then
    echo "  ✗ postfix check falló; revirtiendo"
    cp -a "$BAK" "$MAIN"
    exit 1
fi

# reload basta: postscreen recoge la directiva nueva sin cortar el servicio.
systemctl reload postfix 2>/dev/null || systemctl restart postfix 2>/dev/null || true

sleep 2
if ! systemctl is-active --quiet postfix; then
    echo "  ✗ Postfix no quedó activo; revirtiendo"
    cp -a "$BAK" "$MAIN"
    systemctl restart postfix 2>/dev/null || true
    exit 1
fi

echo "  ✓ greet_action = ignore (backup en $BAK)"
echo "    Los tests de pipelining / non_smtp_command / bare_newline siguen en enforce."
echo "✓ 0145: postscreen deja de rechazar IPs solo por no conocerlas"
exit 0
