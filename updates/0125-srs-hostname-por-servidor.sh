#!/bin/bash
# 0125-srs-hostname-por-servidor.sh
#
# BUG: postsrsd se configuraba con el dominio RAIZ del servidor
# (`postconf -h mydomain`), no con su hostname completo:
#
#     servidor svq1.svqhost.red  ->  SRS_DOMAIN=svqhost.red     (mal)
#     servidor svq2.svqhost.red  ->  SRS_DOMAIN=svqhost.red     (mal, el mismo!)
#
# Con UN servidor funciona. Pero lo normal es tener varios servidores como
# subdominios de un mismo dominio, y entonces TODOS reescriben el envelope-from
# de los reenvios al MISMO svqhost.red... que solo puede tener un SPF, y ese SPF
# solo lista las IPs de un servidor. El resto salen con spf=fail y Gmail/Outlook
# rechazan o marcan como spam sus reenvios de alias.
#
# FIX: cada servidor reescribe a SU hostname completo (svq1.svqhost.red), publica
# su propio SPF/DKIM en ese subdominio y es autonomo: montar el siguiente servidor
# no obliga a tocar la config de los demas.
#
# ⚠️ NO CAMBIA NADA POR SU CUENTA. El nuevo SRS_DOMAIN necesita que se publiquen
# SPF y DKIM en ese subdominio, y el DNS del dominio del servidor suele estar en un
# proveedor EXTERNO (el panel no puede tocarlo). Cambiarlo a ciegas dejaria el
# correo PEOR que antes: los reenvios saldrian con un dominio sin SPF ninguno.
#
# Asi que este update solo AVISA. La vista Correo -> "Salud de correo del servidor"
# da los valores exactos a publicar; una vez publicados, el admin aplica el cambio
# desde ahi (o a mano con las instrucciones de abajo).
#
# Idempotente y no interactivo.

set -u

echo "-> 0125: SRS por hostname de servidor (revision, no aplica cambios)..."

[ -f /etc/default/postsrsd ] || { echo "  . postsrsd no instalado; nada que hacer."; exit 0; }

SRS_ACTUAL="$(grep -E '^SRS_DOMAIN=' /etc/default/postsrsd 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'"'"'"' | xargs)"
HOSTNAME_FQDN="$(postconf -h myhostname 2>/dev/null || hostname -f)"

[ -z "$SRS_ACTUAL" ] && { echo "  . SRS_DOMAIN no configurado; nada que revisar."; exit 0; }

if [ "$SRS_ACTUAL" = "$HOSTNAME_FQDN" ]; then
    echo "  . SRS_DOMAIN ya es el hostname del servidor ($SRS_ACTUAL). Correcto."
    exit 0
fi

# ── El SRS apunta al dominio raiz. ¿Le pasa algo malo de verdad? ──────────────
# Solo es un problema si el SPF de ese dominio NO autoriza a ESTE servidor (que es
# justo lo que ocurre cuando hay un segundo servidor). Si el SPF ya lo cubre (caso
# de un servidor unico), no hay nada roto y no marear al admin.
IP4="$(curl -s --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"
SPF="$(dig +short TXT "$SRS_ACTUAL" @1.1.1.1 2>/dev/null | tr -d '"' | grep -i '^v=spf1' | head -1)"

if [ -n "$SPF" ] && [ -n "$IP4" ] && echo "$SPF" | grep -qF "$IP4"; then
    echo "  . SRS_DOMAIN=$SRS_ACTUAL y su SPF ya autoriza a este servidor ($IP4)."
    echo "  . Funciona, pero si añades OTRO servidor bajo el mismo dominio chocaran:"
    echo "    lo recomendable es SRS_DOMAIN=$HOSTNAME_FQDN (uno por servidor)."
    exit 0
fi

# El SPF del dominio raiz NO cubre a este servidor: los reenvios de alias salen
# con spf=fail AHORA MISMO.
echo ""
echo "  ⚠️  ATENCION: los reenvios de alias de este servidor pueden estar fallando."
echo ""
echo "     SRS_DOMAIN actual : $SRS_ACTUAL   (dominio raiz, compartido)"
echo "     SPF publicado     : ${SPF:-<NINGUNO>}"
echo "     IP de este servidor: ${IP4:-desconocida}   <-- NO esta autorizada"
echo ""
echo "     Los reenvios salen como <...@$SRS_ACTUAL> y Gmail/Outlook comprueban el"
echo "     SPF de ese dominio: como no incluye a este servidor, dan spf=fail."
echo ""
echo "     COMO ARREGLARLO (requiere publicar DNS en el proveedor del dominio):"
echo "       1) Publica en el DNS de $HOSTNAME_FQDN un TXT con el SPF de ESTE servidor."
echo "          El panel te da el valor exacto en: Correo -> Salud de correo del servidor."
echo "       2) Publica tambien el DKIM (mail._domainkey.$HOSTNAME_FQDN)."
echo "       3) Cuando esten publicados, cambia el SRS a este servidor:"
echo "            sed -i 's/^SRS_DOMAIN=.*/SRS_DOMAIN=$HOSTNAME_FQDN/' /etc/default/postsrsd"
echo "            systemctl restart postsrsd"
echo ""
echo "     (No lo cambiamos automaticamente: sin el SPF publicado en el subdominio,"
echo "      los reenvios saldrian con un dominio SIN SPF y estarian peor que ahora.)"
echo ""

echo "OK 0125: revisado (sin cambios automaticos)."
exit 0
