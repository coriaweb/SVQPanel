#!/bin/bash
# 0151-peso-mixed-charset.sh
#
# Sube el peso de R_MIXED_CHARSET de 0.63 a 2.50.
#
# ── QUÉ DETECTA ───────────────────────────────────────────────────────────────
# El correo DECLARA un juego de caracteres que no coincide con su contenido
# real. El caso típico en producción: charset="windows-1251" (alfabeto cirílico)
# con el texto escrito en español, con eñes y tildes.
#
# No es un descuido que ocurra solo: es la huella de herramientas de envío
# masivo configuradas en otro idioma, a las que se les meten plantillas en
# español sin cambiar la codificación.
#
# ── POR QUÉ ESTE Y NO OTROS ───────────────────────────────────────────────────
# Se midieron todos los símbolos candidatos contra el correo REAL de dos
# servidores, cruzando apariciones en spam vs en correo limpio. Descartados:
#
#   MISSING_XM_UA          228 apariciones, 176 en correo LIMPIO (77%)
#   RCVD_VIA_SMTP_AUTH      51 apariciones,  19 en correo LIMPIO (37%)
#   PREVIOUSLY_DELIVERED    99 apariciones, sale en Gmail, ONCE, Obramat
#   DWL_DNSWL_NONE          70 apariciones, sale en Stripe, Amazon, Gmail
#   RECEIVED_SPAMHAUS_PBL    4 apariciones, salta en un despacho LEGÍTIMO
#
# Ese último merece explicación porque engaña: el PBL de Spamhaus NO es una
# lista de spammers, es la lista de rangos domésticos que no deberían enviar
# correo directamente. Salta porque la IP residencial del REMITENTE queda
# anotada en las cabeceras Received. Penalizarlo castigaría a todo el que
# escriba desde su casa u oficina.
#
# R_MIXED_CHARSET, en cambio:
#   13 apariciones → 12 spam, 1 legítima (un Mailchimp con score 1.63)
#
# Y detecta algo cualitativamente distinto: una INCOHERENCIA INTERNA del correo,
# no una característica de su origen. Por eso discrimina.
#
# ── EFECTO MEDIDO ─────────────────────────────────────────────────────────────
#   cofund.solutions      1.60 → 3.47   (sigue entrando, pero al borde de Junk)
#   preciosbajos.store    7.30 → 9.17   (ya se rechazaba)
#   Mailchimp legítimo    1.63 → 3.50   (sigue entrando; Junk está en 4.00)
#
# Ningún correo legítimo medido cruza el umbral. Honestamente: esto SOLO no
# arregla cofund.solutions, le faltan 0.53 puntos. Lo que debe cerrar ese hueco
# es el Bayes, ahora que el 0150 le devolvió su alimentación.
#
# ── DÓNDE VA EL PESO ──────────────────────────────────────────────────────────
# En groups.conf, que es de donde Rspamd lee los overrides. Como ese fichero lo
# regenera entero el panel desde la BD, el símbolo va TAMBIÉN en BASE_WEIGHTS de
# scripts/rspamd_tuning.py para que sobreviva a cada guardado de ajustes.
#
# Idempotente y no interactivo. Reversible: quitar la línea de groups.conf (o
# ajustarlo desde Administración → Ajuste antispam).
set -e

SVQ_GROUPS=/etc/rspamd/local.d/groups.conf
WANT='  "R_MIXED_CHARSET" { weight = 2.50; }'

echo "→ 0151: peso de R_MIXED_CHARSET 0.63 → 2.50…"

if [ ! -d /etc/rspamd ]; then
    echo "  · Rspamd no instalado; nada que hacer"
    exit 0
fi

if [ -f "$SVQ_GROUPS" ] && grep -q 'R_MIXED_CHARSET' "$SVQ_GROUPS"; then
    echo "  · R_MIXED_CHARSET ya tenía override; nada que hacer"
    exit 0
fi

if [ -f "$SVQ_GROUPS" ] && grep -q '^symbols {' "$SVQ_GROUPS"; then
    cp -a "$SVQ_GROUPS" "${SVQ_GROUPS}.bak-0151-$(date +%Y%m%d%H%M%S)"
    awk -v want="$WANT" '{ print; if ($0 ~ /^symbols \{/) print want }' \
        "$SVQ_GROUPS" > "${SVQ_GROUPS}.tmp" && mv "${SVQ_GROUPS}.tmp" "$SVQ_GROUPS"
    echo "  · añadido sin tocar los overrides existentes"
else
    [ -f "$SVQ_GROUPS" ] && cp -a "$SVQ_GROUPS" "${SVQ_GROUPS}.bak-0151-$(date +%Y%m%d%H%M%S)"
    {
        echo "# SVQPanel — overrides de peso de símbolos (admin). NO editar a mano."
        echo "symbols {"
        echo "$WANT"
        echo "}"
    } > "$SVQ_GROUPS"
    echo "  · groups.conf creado con R_MIXED_CHARSET = 2.50"
fi
chmod 644 "$SVQ_GROUPS"

if systemctl is-active --quiet rspamd 2>/dev/null; then
    systemctl reload rspamd 2>/dev/null || systemctl restart rspamd 2>/dev/null || true
    sleep 2
    if ! systemctl is-active --quiet rspamd; then
        echo "  ✗ Rspamd no quedó activo; revirtiendo"
        cp -a "$(ls -t ${SVQ_GROUPS}.bak-0151-* | head -1)" "$SVQ_GROUPS"
        systemctl restart rspamd 2>/dev/null || true
        exit 1
    fi
fi

# Verificar el peso EFECTIVO: rspamadm configdump NO lista símbolos, hay que
# mirarlos con rspamc counters.
EFECTIVO=$(rspamc counters 2>/dev/null | grep -oP '\|\s*R_MIXED_CHARSET\s*\|\s*\K-?[0-9.]+' | head -1)
echo "  · peso efectivo de R_MIXED_CHARSET: ${EFECTIVO:-?}"
case "${EFECTIVO:-?}" in
    2.5|2.50) echo "  ✓ aplicado" ;;
    ?)        echo "  ⚠ no se pudo leer el peso efectivo" ;;
    *)        echo "  ⚠ el peso efectivo es ${EFECTIVO}, revisar $SVQ_GROUPS" ;;
esac

echo "✓ 0151: R_MIXED_CHARSET penaliza el charset incoherente"
exit 0
