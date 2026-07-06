#!/bin/bash
# 0110-mail-max-userip-connections.sh
#
# Sube el límite de conexiones IMAP por usuario+IP de Dovecot de 10 (default)
# a 50. El cupo es por buzón+IP, y en oficinas tras NAT todos los equipos
# comparten la IP pública: con 3-4 PCs usando el mismo buzón (Thunderbird abre
# hasta 5 conexiones por cuenta) el default se agota y el resto de equipos ve
# "Maximum number of connections from user+IP exceeded".
#
# Mismo drop-in que escribe install_mail.sh en instalaciones limpias
# (/etc/dovecot/conf.d/99-svqpanel-limits.conf). Sintaxis válida en
# Dovecot 2.3 y 2.4.
#
# Respetuoso: si el admin ya subió el límite global a ≥ 50 a mano, no se toca.
# Idempotente y no interactivo.

set -u

DROPIN=/etc/dovecot/conf.d/99-svqpanel-limits.conf
TARGET=50

echo "→ 0110: mail_max_userip_connections → ${TARGET} (oficinas tras NAT)…"

if ! command -v doveconf >/dev/null 2>&1; then
    echo "  · dovecot no instalado (doveconf ausente); se omite"
    echo "✓ 0110: sin cambios"
    exit 0
fi

if [ -f "$DROPIN" ] && grep -q "mail_max_userip_connections" "$DROPIN"; then
    echo "  · $DROPIN ya existe; se respeta"
    echo "✓ 0110: sin cambios"
    exit 0
fi

CURRENT="$(doveconf -h mail_max_userip_connections 2>/dev/null | tr -dc '0-9')"
[ -z "$CURRENT" ] && CURRENT=0
if [ "$CURRENT" -ge "$TARGET" ]; then
    echo "  · mail_max_userip_connections ya es ${CURRENT} (≥ ${TARGET}); se respeta"
    echo "✓ 0110: sin cambios"
    exit 0
fi

cat > "$DROPIN" << 'DOVELIMEOF'
# SVQPanel: límites de conexión (oficinas con varios equipos tras la misma IP)
protocol imap {
  mail_max_userip_connections = 50
}
DOVELIMEOF

# Validar antes de recargar: si la config no compila, revertir y avisar.
if ! doveconf -n >/dev/null 2>&1; then
    echo "  ✗ doveconf rechaza el drop-in; se revierte"
    rm -f "$DROPIN"
    exit 1
fi

echo "  ✓ $DROPIN escrito (límite ${CURRENT:-10} → ${TARGET})"

if command -v systemctl >/dev/null 2>&1; then
    systemctl reload-or-restart dovecot >/dev/null 2>&1 \
        && echo "  ✓ dovecot recargado" \
        || echo "  ⚠ no se pudo recargar dovecot (revisar: journalctl -u dovecot)"
fi

echo "✓ 0110: límite de conexiones IMAP por usuario+IP en ${TARGET}"
exit 0
