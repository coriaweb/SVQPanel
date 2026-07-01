#!/bin/bash
# 0094-message-size-limit-25mb.sh
#
# Sube el tope de tamaño por mensaje de Postfix (message_size_limit) a 25 MB
# (26214400 bytes), como Gmail. Postfix trae 10 MB por defecto, que se queda
# corto para adjuntos: los correos entrantes/salientes que lo superan se
# rechazan con "552 5.3.4 Message size exceeds fixed limit".
#
# A partir de ahora es ajustable desde el panel (Configuración → Email →
# Tamaño máximo de mensaje); este update solo fija el nuevo valor por defecto
# en los servidores ya instalados.
#
# Respetuoso: si el admin YA subió el límite por encima de 25 MB a mano, NO se
# lo baja. Solo eleva cuando está por debajo (típicamente el default de 10 MB).
# Idempotente y no interactivo.

set -u

TARGET=26214400   # 25 MB

echo "→ 0094: tamaño máximo de mensaje (message_size_limit) → 25 MB…"

if ! command -v postconf >/dev/null 2>&1; then
    echo "  · postfix no instalado (postconf ausente); se omite"
    echo "✓ 0094: sin cambios"
    exit 0
fi

CURRENT="$(postconf -h message_size_limit 2>/dev/null | tr -dc '0-9')"
[ -z "$CURRENT" ] && CURRENT=0

# 0 en Postfix = sin límite: no lo tocamos (el admin lo quiso ilimitado).
if [ "$CURRENT" = "0" ]; then
    echo "  · message_size_limit = 0 (sin límite); se respeta, no se toca"
    echo "✓ 0094: sin cambios"
    exit 0
fi

if [ "$CURRENT" -ge "$TARGET" ]; then
    echo "  · message_size_limit ya es $CURRENT bytes (≥ 25 MB); se respeta"
    echo "✓ 0094: sin cambios"
    exit 0
fi

postconf -e "message_size_limit = ${TARGET}"
echo "  ✓ message_size_limit: ${CURRENT} → ${TARGET} bytes (25 MB)"

if command -v systemctl >/dev/null 2>&1; then
    systemctl reload-or-restart postfix >/dev/null 2>&1 \
        && echo "  ✓ postfix recargado" \
        || echo "  ⚠ no se pudo recargar postfix (revisar: journalctl -u postfix)"
fi

echo "✓ 0094: tamaño máximo de mensaje en 25 MB"
exit 0
