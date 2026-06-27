#!/bin/bash
# 0063-srs-postsrsd.sh
#
# SRS (Sender Rewriting Scheme) para reenvíos de correo seguros.
#
# Problema: cuando un alias/reenvío manda correo a Gmail/Outlook/etc., Postfix
# reenviaba con el envelope-from ORIGINAL (de otro dominio). El destino comprueba
# SPF de ese dominio contra NUESTRA IP → SPF fail → reenviamos la mala reputación
# ajena (mucho spam que entra y se reenvía) y nuestra IP acaba en listas negras
# (Spamhaus, Gmail, etc.) sin haber enviado nada propio.
#
# Solución: postsrsd reescribe el envelope-from al reenviar a "...@<mydomain>"
# (cuyo SPF SÍ incluye nuestra IP) y descodifica los rebotes de vuelta al
# remitente original. Estándar de la industria (cPanel/Plesk/Hestia igual).
#
# Idempotente y no interactivo. Solo actúa si Postfix está instalado.

set -u

echo "→ 0063: SRS (postsrsd) para reenvíos seguros…"

if ! command -v postconf >/dev/null 2>&1; then
    echo "✓ 0063: Postfix no instalado (¿servidor sin correo?); nada que hacer"
    exit 0
fi

# 1) Instalar postsrsd (idempotente).
if ! dpkg -l postsrsd 2>/dev/null | grep -q '^ii'; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postsrsd 2>/dev/null || {
        echo "  ⚠ no se pudo instalar postsrsd; reenvíos siguen sin SRS"; exit 0; }
fi

# 2) Dominio de reescritura = mydomain (su SPF incluye la IP del servidor).
SRS_DOM="$(postconf -h mydomain 2>/dev/null)"
[ -n "$SRS_DOM" ] || SRS_DOM="$(hostname -d 2>/dev/null)"
if [ -z "$SRS_DOM" ]; then
    echo "  ⚠ no se pudo determinar el dominio para SRS; abortando"
    exit 0
fi
# postsrsd 1.x (Debian 12/13) configura por /etc/default/postsrsd (formato shell).
if [ -f /etc/default/postsrsd ]; then
    if grep -q '^#*SRS_DOMAIN=' /etc/default/postsrsd; then
        sed -i "s/^#*SRS_DOMAIN=.*/SRS_DOMAIN=${SRS_DOM}/" /etc/default/postsrsd
    else
        echo "SRS_DOMAIN=${SRS_DOM}" >> /etc/default/postsrsd
    fi
fi

systemctl enable postsrsd 2>/dev/null || true
systemctl restart postsrsd 2>/dev/null || true
sleep 1

# 3) Verificar que postsrsd reescribe ANTES de enchufarlo a Postfix (seguridad:
#    si no responde, NO tocar Postfix para no romper el envío de correo).
TEST_OUT="$(postmap -q 'probe@dominio-externo-test.com' tcp:127.0.0.1:10001 2>/dev/null)"
case "$TEST_OUT" in
    SRS0=*@${SRS_DOM})
        : ;;  # OK, reescribe a nuestro dominio
    *)
        echo "  ⚠ postsrsd no reescribe correctamente (out='${TEST_OUT}'); NO toco Postfix"
        exit 0 ;;
esac

# 4) Enchufar a Postfix (forward=10001, reverse=10002; solo loopback).
postconf -e "sender_canonical_maps = tcp:127.0.0.1:10001"
postconf -e "sender_canonical_classes = envelope_sender"
postconf -e "recipient_canonical_maps = tcp:127.0.0.1:10002"
postconf -e "recipient_canonical_classes = envelope_recipient,header_recipient"
systemctl reload postfix 2>/dev/null || systemctl restart postfix 2>/dev/null || true

echo "✓ 0063: SRS activo — reenvíos reescritos a @${SRS_DOM} (fin de blacklist por reenvío)"
exit 0
