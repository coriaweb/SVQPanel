#!/bin/bash
# 0121-postfix-preferir-ipv4-salida.sh
#
# BUG: el correo SALIENTE se enviaba por IPv6 cuando el servidor tiene IPv6, porque
# Postfix venia con el default smtp_address_preference=any. Problema: la IPv6 del
# servidor casi nunca tiene PTR (rDNS) y el SPF del dominio no cubre la IPv6 concreta
# que el SO elige del /64 -> el correo daba SPF FAIL en Gmail (y arriesga rechazo
# 550 por PTR faltante). La IPv4 dedicada del servidor SI tiene PTR y esta en el SPF.
#
# Sintoma real: correo de un dominio recien creado/migrado que sale por IPv6
# (2001:...:xxxx) y Gmail marca "spf=fail ... does not designate <IPv6>".
#
# FIX: smtp_address_preference = ipv4. Asi el correo sale por IPv4 (con PTR+SPF) por
# defecto; un dominio que quiera IPv6 dedicada la activa desde el panel (el
# mail_manager pone el smtp_bind_address6 por dominio, opt-in con PTR propio).
#
# Solo si hay Postfix. Idempotente y no interactivo.

set -u

echo "-> 0121: Postfix preferir IPv4 en correo saliente..."

if ! command -v postconf >/dev/null 2>&1; then
    echo "  . Postfix no instalado; nada que hacer."
    exit 0
fi

CUR="$(postconf -h smtp_address_preference 2>/dev/null)"
if [ "$CUR" = "ipv4" ]; then
    echo "  . smtp_address_preference ya es ipv4; nada que hacer."
    exit 0
fi

postconf -e "smtp_address_preference = ipv4"
echo "  . smtp_address_preference: '$CUR' -> ipv4"

if postfix check 2>/dev/null; then
    systemctl reload postfix 2>/dev/null || systemctl restart postfix 2>/dev/null || true
    echo "  . Postfix recargado."
fi

echo "OK 0121: correo saliente prefiere IPv4 (PTR+SPF correctos)."
exit 0
