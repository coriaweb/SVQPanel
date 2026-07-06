#!/bin/bash
# 0111-mail-sin-doble-conteo-crowdsec.sh
#
# Debian escribe las líneas de postfix/dovecot en /var/log/mail.log Y TAMBIÉN
# en /var/log/syslog (catch-all). CrowdSec lee los dos ficheros (acquis
# setup.postfix/setup.dovecot → mail.log; setup.linux → syslog), así que cada
# fallo de autenticación de correo contaba DOBLE: el servidor baneaba con la
# MITAD de los fallos reales configurados (caso real: una oficina entera
# baneada con solo 2 intentos fallidos de un equipo con contraseña caducada).
#
# Fix: excluir la facility mail del catch-all de /var/log/syslog en rsyslog.
# Las líneas siguen íntegras en /var/log/mail.log, que es de donde leen
# fail2ban y los parsers de correo de CrowdSec. Mismo cambio que aplica
# install_mail.sh en instalaciones limpias.
#
# Respetuoso: si la línea de syslog ya excluye mail, o el rsyslog.conf es
# custom (no tiene la línea estándar de Debian), no se toca nada.
# Idempotente y no interactivo.

set -u

CONF=/etc/rsyslog.conf

echo "→ 0111: correo sin doble conteo en CrowdSec (mail fuera de syslog)…"

if [ ! -f "$CONF" ]; then
    echo "  · $CONF no existe (¿sin rsyslog?); se omite"
    echo "✓ 0111: sin cambios"
    exit 0
fi

if grep -qE '^\*\.\*;.*mail[.,].*none.*/var/log/syslog' "$CONF"; then
    echo "  · syslog ya excluye mail; se respeta"
    echo "✓ 0111: sin cambios"
    exit 0
fi

if ! grep -qE '^\*\.\*;auth,authpriv\.none.*/var/log/syslog' "$CONF"; then
    echo "  · rsyslog.conf no tiene la línea estándar de Debian (config custom); se omite"
    echo "✓ 0111: sin cambios"
    exit 0
fi

cp -a "$CONF" "${CONF}.bak-0111"
sed -i 's|^\*\.\*;auth,authpriv\.none|*.*;mail,auth,authpriv.none|' "$CONF"

# Validar la config antes de dejarla activa; si no compila, revertir.
if command -v rsyslogd >/dev/null 2>&1 && ! rsyslogd -N1 >/dev/null 2>&1; then
    echo "  ✗ rsyslogd -N1 rechaza el cambio; se revierte"
    mv "${CONF}.bak-0111" "$CONF"
    exit 1
fi
rm -f "${CONF}.bak-0111"

systemctl restart rsyslog 2>/dev/null \
    && echo "  ✓ rsyslog reiniciado (mail ya no se duplica en /var/log/syslog)" \
    || echo "  ⚠ no se pudo reiniciar rsyslog (revisar: journalctl -u rsyslog)"

echo "✓ 0111: los fallos de correo ya solo cuentan UNA vez en CrowdSec"
exit 0
