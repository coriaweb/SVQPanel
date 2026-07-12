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

# ── La clave DKIM debe llamarse como el dominio SRS ───────────────────────────
# Rspamd busca la clave en /etc/rspamd/dkim/$domain.$selector.key. Si el SRS pasa a
# usar el hostname, la clave del dominio raiz (svqhost.red.mail.key) deja de
# encontrarse y el panel dice "aun no hay clave DKIM generada" aunque SI la haya.
#
# REUTILIZAMOS la clave existente en vez de generar una nueva: si el admin ya
# publico el TXT con esa clave publica, generar otra lo invalidaria y tendria que
# volver a tocar el DNS externo. Copiarla mantiene el TXT publicado valido.
_fix_dkim_key() {
    local dom="$1"
    local D=/etc/rspamd/dkim
    [ -d "$D" ] || return 0
    [ -f "$D/$dom.mail.key" ] && return 0          # ya existe con el nombre bueno

    # ¿Hay una clave del dominio raiz que podamos reutilizar?
    local raiz="${dom#*.}"                          # svq1.svqhost.red -> svqhost.red
    if [ -n "$raiz" ] && [ "$raiz" != "$dom" ] && [ -f "$D/$raiz.mail.key" ]; then
        cp -a "$D/$raiz.mail.key" "$D/$dom.mail.key"
        chown _rspamd:_rspamd "$D/$dom.mail.key" 2>/dev/null || \
            chown rspamd:rspamd "$D/$dom.mail.key" 2>/dev/null || true
        chmod 600 "$D/$dom.mail.key"
        echo "  . clave DKIM reutilizada para $dom (el TXT ya publicado sigue valido)"
    elif [ -x /opt/svqpanel/venv/bin/python ]; then
        # No hay ninguna: generar una nueva (el admin tendra que publicar su TXT)
        cd /opt/svqpanel && /opt/svqpanel/venv/bin/python - "$dom" <<'PYEOF' 2>/dev/null || true
import sys
from scripts.dkim_manager import DkimManager
dk = DkimManager()
if dk.dkim_available() and not dk.key_exists(sys.argv[1], "mail"):
    dk.generate_key(sys.argv[1], "mail")
    print(f"  . clave DKIM NUEVA generada para {sys.argv[1]} (publica su TXT)")
PYEOF
    fi

    # Declararla en el selectors.map o rspamd no la usara.
    # -F (cadena literal): los puntos del dominio son comodines en una regex y
    # "svq1.svqhost.red" haria match con "svq1xsvqhost.red".
    if [ -f "$D/selectors.map" ] && ! grep -qF "$dom	" "$D/selectors.map"; then
        printf '%s\tmail\n' "$dom" >> "$D/selectors.map"
        echo "  . $dom añadido a selectors.map"
    fi
    systemctl reload rspamd >/dev/null 2>&1 || true
}

if [ "$SRS_ACTUAL" = "$HOSTNAME_FQDN" ]; then
    echo "  . SRS_DOMAIN ya es el hostname del servidor ($SRS_ACTUAL). Correcto."
    _fix_dkim_key "$SRS_ACTUAL"     # asegurar que la clave DKIM lleva ese nombre
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
