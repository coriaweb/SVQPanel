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

# 5) IP de salida fija para el correo DEL SERVIDOR (reenvíos SRS / sistema).
#    Sin esto, el correo del servidor puede salir por una IPv6 SLAAC/de dominio
#    aleatoria sin PTR/SPF → rechazo de Gmail. El envío por dominio NO se afecta
#    (cada uno usa su transporte svqout_* con su propio bind). Detectamos la IP
#    principal de la máquina del enrutado por defecto.
OUT_V4="$(ip -4 route get 1.1.1.1 2>/dev/null | grep -oE 'src [0-9.]+' | awk '{print $2}')"
OUT_V6="$(ip -6 route get 2001:4860:4860::8888 2>/dev/null | grep -oE 'src [0-9a-f:]+' | awk '{print $2}')"
[ -n "$OUT_V4" ] && postconf -e "smtp_bind_address = $OUT_V4"
[ -n "$OUT_V6" ] && postconf -e "smtp_bind_address6 = $OUT_V6"

systemctl reload postfix 2>/dev/null || systemctl restart postfix 2>/dev/null || true

# 6) DKIM del dominio del servidor (para autenticar los reenvíos). Idempotente:
#    solo genera si no existe. El TXT a publicar lo muestra la vista del panel.
if [ -x /opt/svqpanel/venv/bin/python ]; then
    cd /opt/svqpanel 2>/dev/null && /opt/svqpanel/venv/bin/python - "$SRS_DOM" <<'PYEOF' 2>/dev/null || true
import sys
from scripts.dkim_manager import DkimManager
dk = DkimManager()
if dk.dkim_available():
    dom = sys.argv[1]
    if not dk.key_exists(dom, "mail"):
        dk.generate_key(dom, "mail")
        print(f"  DKIM del servidor generado para {dom}")
PYEOF
fi

echo "✓ 0063: SRS + salida fija (v4:${OUT_V4:-none} v6:${OUT_V6:-none}) + DKIM del servidor (@${SRS_DOM})"
echo "  ⚠ Publica en el DNS de ${SRS_DOM}: SPF (a/mx/ip4/ip6), DKIM (mail._domainkey) y PTR de la IP. Vista 'Salud de correo del servidor'."
exit 0
