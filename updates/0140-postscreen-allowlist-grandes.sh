#!/bin/bash
# 0140-postscreen-allowlist-grandes.sh
#
# Allowlist de las granjas de correo grandes en postscreen: Microsoft/Outlook,
# Google/Gmail y Amazon SES entran sin pasar por el portero.
#
# EL PROBLEMA (medido en producción, no supuesto):
# postscreen rechaza a toda IP desconocida en su primera conexión con
# "450 4.3.2 Service currently unavailable". Los emisores pequeños reintentan
# desde la MISMA IP y entran al 2º intento, pero las granjas grandes reintentan
# desde una IP DISTINTA cada vez, así que cada reintento vuelve a ser "IP nueva":
#
#   52.101.94.128 → .93.77 → .90.130 → .93.104 → .93.120 → .92.74 → .92.129 → …
#
# Resultado: correo legítimo retrasado horas. Caso real: un correo de Outlook
# rechazado 8 veces (12:08→17:41) que entró a las 18:42, 6h30 tarde.
#
# LOS NÚMEROS de un día en el servidor de referencia (488 rechazos totales):
#   · Microsoft/Outlook : 96
#   · Google/Gmail      : 99
#   · Amazon SES        : 56
#   → 251 de 488 (51%) son de estas tres granjas.
#
# Y son correo legítimo: los remitentes rechazados eran despachos de abogados,
# gestorías y empresas (ken@sasakiabogados.com, ana@administracionserranolobo.com,
# facturacion@eurocabos.es…), y se comprobó que acababan entregando tras varios
# reintentos — solo que horas más tarde.
#
# POR QUÉ ALLOWLIST Y NO BAJAR LAS DEFENSAS:
# Los intentos previos de arreglarlo tocando parámetros globales fallaron:
#   · 0138 (greet_wait 6s→2s): solo acorta la espera, el rechazo se produce igual.
#   · 0139 (greet_action → ignore): desarma el pregreet para TODO el mundo (~44
#     bots/día dejarían de bloquearse) y aun así siguieron apareciendo rechazos.
# La allowlist es quirúrgica: solo exime a tres granjas identificadas y verificadas,
# y deja el portero intacto para el resto de Internet (que es de donde vienen los
# bots). El correo de estas granjas SIGUE pasando por Rspamd, Bayes, SPF/DKIM/DMARC,
# antivirus y CrowdSec: postscreen no es un filtro de contenido.
#
# ORIGEN DE LOS RANGOS: los registros SPF oficiales, consultados en el momento de
# escribir este update:
#   dig TXT spf.protection.outlook.com   → Microsoft
#   dig TXT _spf.google.com              → Google
#   dig TXT amazonses.com                → Amazon SES
# Verificado además por rDNS: 52.101.94.128 → mail-…outbound.protection.outlook.com
#
# MANTENIMIENTO: estos rangos cambian de tanto en tanto. Si en el futuro vuelve a
# aparecer correo diferido de estas granjas, recomprobar los SPF y ampliar la lista.
#
# Idempotente y no interactivo. Reversible: basta borrar el fichero de la allowlist
# y quitar la referencia en main.cf.
set -e

MAIN=/etc/postfix/main.cf
ALLOW=/etc/postfix/postscreen_access.cidr

echo "→ 0140: allowlist de granjas grandes en postscreen…"

if [ ! -f "$MAIN" ]; then
    echo "  · no hay Postfix instalado; nada que hacer"
    exit 0
fi

# Si postscreen no está activo (0083 no aplicado), no tocamos nada.
if ! grep -q '^postscreen_greet_action' "$MAIN"; then
    echo "  · postscreen no está activo; nada que hacer"
    exit 0
fi

# 1) Fichero CIDR con los rangos. Se reescribe siempre (es la fuente de verdad),
#    así una re-ejecución actualiza la lista si este script cambió.
cat > "$ALLOW" << 'CIDREOF'
# SVQPanel — allowlist de postscreen. Generado por updates/0140. NO editar a mano.
#
# Granjas de correo grandes que reintentan desde una IP distinta en cada intento:
# sin esta lista, cada reintento cuenta como "IP nueva" y postscreen las difiere
# indefinidamente. Rangos tomados de sus registros SPF oficiales.
#
# permit = saltarse los tests de postscreen. NO significa saltarse el antispam:
# Rspamd, SPF/DKIM/DMARC, Bayes, antivirus y CrowdSec siguen aplicando después.

# ── Microsoft / Outlook / Office 365 (spf.protection.outlook.com) ──
40.92.0.0/15            permit
40.107.0.0/16           permit
52.100.0.0/15           permit
52.102.0.0/16           permit
52.103.0.0/17           permit
104.47.0.0/17           permit
2a01:111:f400::/48      permit
2a01:111:f403::/49      permit
2a01:111:f403:8000::/51 permit
2a01:111:f403:c000::/51 permit
2a01:111:f403:f000::/52 permit

# ── Google / Gmail (_spf.google.com) ──
35.190.247.0/24         permit
64.233.160.0/19         permit
66.102.0.0/20           permit
66.249.80.0/20          permit
72.14.192.0/18          permit
74.125.0.0/16           permit
108.177.8.0/21          permit
173.194.0.0/16          permit
209.85.128.0/17         permit
216.58.192.0/19         permit
216.239.32.0/19         permit
2001:4860:4000::/36     permit
2001:4860:4864::/56     permit
2404:6800:4000::/36     permit
2404:6800:4864::/56     permit
2607:f8b0:4000::/36     permit
2607:f8b0:4864::/56     permit
2800:3f0:4000::/36      permit
2800:3f0:4864::/56      permit
2a00:1450:4000::/36     permit
2a00:1450:4864::/56     permit
2c0f:fb50:4000::/36     permit
2c0f:fb50:4864::/56     permit

# ── Amazon SES (amazonses.com) ──
54.240.0.0/18           permit
76.223.176.0/20         permit
CIDREOF

chmod 644 "$ALLOW"
echo "  · allowlist escrita en $ALLOW"

# 2) Referenciarla en postscreen_access_list, DELANTE de permit_mynetworks.
#    Se conserva permit_mynetworks (redes propias) y se añade el cidr.
ACTUAL=$(postconf -h postscreen_access_list 2>/dev/null || echo "")
DESEADO="permit_mynetworks, cidr:${ALLOW}"

if [ "$ACTUAL" = "$DESEADO" ]; then
    echo "  · postscreen_access_list ya apunta a la allowlist; solo se refrescó el CIDR"
else
    echo "  · postscreen_access_list: '${ACTUAL}' → '${DESEADO}'"
    BAK="${MAIN}.bak-0140-$(date +%Y%m%d%H%M%S)"
    cp -a "$MAIN" "$BAK"
    postconf -e "postscreen_access_list = ${DESEADO}"

    if ! postfix check 2>/dev/null; then
        echo "  ✗ postfix check falló; revirtiendo"
        cp -a "$BAK" "$MAIN"
        exit 1
    fi
    echo "  · backup de main.cf en $BAK"
fi

# 3) Recargar y comprobar que Postfix sigue en pie.
systemctl reload postfix 2>/dev/null || systemctl restart postfix 2>/dev/null || true
sleep 2
if ! systemctl is-active --quiet postfix; then
    echo "  ✗ Postfix no quedó activo tras el cambio"
    exit 1
fi

echo "  ✓ allowlist activa (Microsoft + Google + Amazon SES)"
echo "✓ 0140: las granjas grandes ya no se difieren"
exit 0
