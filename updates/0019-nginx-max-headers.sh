#!/bin/bash
# 0019-nginx-max-headers.sh
#
# Defensa contra el "HTTP/2 Bomb" (amplificación HPACK + flow-control window
# stall): nginx 1.29.8+ trae la directiva `max_headers` que limita el nº de
# cabeceras por petición. El panel instala nginx del repo oficial (ya >= 1.29.8,
# no vulnerable), pero añadimos max_headers como capa explícita de defensa.
#
# Idempotente. Solo añade la directiva si la versión de nginx la soporta
# (>= 1.29.8); en versiones viejas la directiva no existe y rompería nginx -t.

set -euo pipefail

echo "→ 0019: nginx max_headers (mitigación HTTP/2 Bomb)..."

HARD=/etc/nginx/conf.d/svqpanel-hardening.conf
[ -f "$HARD" ] || { echo "  Sin $HARD (¿sin nginx?) — nada que hacer."; exit 0; }

if grep -q 'max_headers' "$HARD"; then
    echo "  max_headers ya presente — nada que hacer."
    exit 0
fi

# ¿nginx >= 1.29.8?
V=$(nginx -v 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo "0.0.0")
if printf '1.29.8\n%s\n' "$V" | sort -V -C; then
    echo "max_headers 100;" >> "$HARD"
    if nginx -t >/dev/null 2>&1; then
        systemctl reload nginx
        echo "  ✓ max_headers 100 añadido (nginx $V) y recargado"
    else
        # Revertir si por lo que sea no valida
        sed -i '/max_headers 100;/d' "$HARD"
        echo "  ✗ nginx -t falló; revertido. Revisa: nginx -t"
        exit 1
    fi
else
    echo "  nginx $V < 1.29.8 no soporta max_headers; omito (actualiza nginx para mitigar)."
fi

echo "✓ 0019: nginx max_headers aplicado"
exit 0
