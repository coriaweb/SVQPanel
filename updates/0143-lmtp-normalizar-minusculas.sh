#!/bin/bash
# 0143-lmtp-normalizar-minusculas.sh
#
# Correo REAL de clientes rebotando con "550 User doesn't exist" aunque el buzón
# SÍ existe: pasaba cuando el remitente escribía la dirección en MAYÚSCULAS
# (GLOBATEL@GLOBATEL.ES, JOSE.GARCIA@INMOBILIARIACAMARON.COM…). Medido en el .71:
# 175 correos perdidos entre el 26-jul y el 26-ago (~5/día), de emisores reales
# (proveedores, Iberdrola, BBVA). El remitente recibía el "no existe", así que
# el cliente ni se enteraba de que le habían escrito.
#
# CAUSA: el drop-in 99-svqpanel-lmtp.conf (que puso el update 0062) forzaba
#
#     auth_username_format = %{user}
#
# para quitar el '| username' que trae el 20-lmtp.conf de Dovecot 2.4, porque
# 'username' RECORTA el @dominio y los buzones se indexan por email completo
# (passwd-file) → sin ese arreglo NO entraba nada de correo. Correcto… salvo que
# al escribir %{user} se perdió también el '| lower' del valor original
#
#     %{user | username | lower}
#
# que es el que normaliza a minúsculas. Y como nuestro drop-in es 99- (se lee el
# último), gana sobre el 20-lmtp.conf del paquete.
#
# FIX: %{user | lower} — mantiene el email completo (sin 'username') y recupera
# la normalización a minúsculas.
#
# Idempotente y no interactivo. Valida con `doveconf -n` ANTES de reiniciar y
# revierte si la config queda inválida (Dovecot roto = todo el correo caído).

set -u

echo "→ 0143: LMTP normaliza el destinatario a minúsculas…"

DROPIN=/etc/dovecot/conf.d/99-svqpanel-lmtp.conf

if ! command -v doveconf >/dev/null 2>&1; then
    echo "  · Dovecot no instalado; nada que hacer"
    exit 0
fi

# Valor efectivo de auth_username_format dentro de 'protocol lmtp'.
# OJO: quedarse SOLO con la parte de la derecha del '='. El nombre del ajuste ya
# contiene la palabra "username", así que buscarla en la línea entera da siempre
# positivo y la comprobación no valdría para nada.
_lmtp_fmt() {
    doveconf -n 2>/dev/null | grep -A2 'protocol lmtp' \
        | grep 'auth_username_format' | sed 's/.*=//'
}

# Ya aplicado (idempotencia): el VALOR lleva 'lower' y no 'username'.
efectivo="$(_lmtp_fmt)"
if echo "$efectivo" | grep -q 'lower' && ! echo "$efectivo" | grep -q 'username'; then
    echo "  · ya normaliza a minúsculas (auth_username_format =$efectivo)"
    exit 0
fi

BACKUP=""
if [ -f "$DROPIN" ]; then
    BACKUP="${DROPIN}.bak.$$"
    cp -a "$DROPIN" "$BACKUP"
fi

cat > "$DROPIN" <<'EOF'
# SVQPanel: LMTP busca el buzón por EMAIL COMPLETO (no recortar el dominio).
# NO editar a mano (lo gestionan install.sh y updates/0062 + 0143).
#
# | lower          → normaliza a minúsculas. SIN esto, un correo dirigido a
#                    "JOSE@DOMINIO.COM" rebota con "550 User doesn't exist"
#                    aunque el buzón exista como "jose@dominio.com".
# SIN | username   → 'username' RECORTA el @dominio, y los buzones se indexan
#                    por email completo (passwd-file) → con él no entra correo.
protocol lmtp {
  auth_username_format = %{user | lower}
}
EOF

if ! doveconf -n >/dev/null 2>&1; then
    echo "  ✗ la config de Dovecot queda INVÁLIDA; revirtiendo…"
    doveconf -n 2>&1 | tail -5
    if [ -n "$BACKUP" ]; then
        mv -f "$BACKUP" "$DROPIN"
    else
        rm -f "$DROPIN"
    fi
    echo "  ✓ revertido (Dovecot intacto)"
    exit 1
fi
echo "  ✓ config de Dovecot válida"
[ -n "$BACKUP" ] && rm -f "$BACKUP"

if ! systemctl restart dovecot; then
    echo "  ✗ fallo al reiniciar Dovecot; revisar 'journalctl -u dovecot'"
    exit 1
fi

# Comprobar el valor efectivo tras el reinicio: si otro drop-in lo volviera a
# pisar, el correo en mayúsculas seguiría rebotando y el update habría mentido.
final="$(_lmtp_fmt)"
if echo "$final" | grep -q 'lower' && ! echo "$final" | grep -q 'username'; then
    echo "  ✓ auth_username_format efectivo:$final"
else
    echo "  ✗ el valor efectivo NO es el esperado (¿otro drop-in lo pisa?):"
    echo "    auth_username_format =$final"
    exit 1
fi

echo "✓ 0143: el correo a direcciones en MAYÚSCULAS ya se entrega"
exit 0
