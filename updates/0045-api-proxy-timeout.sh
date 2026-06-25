#!/bin/bash
# 0045-api-proxy-timeout.sh
#
# El location /api/ del nginx del panel no tenía proxy_read_timeout, así que
# usaba el default de nginx (60s). Operaciones legítimamente largas (migración
# de backups de varios GB, emisión de SSL, restauraciones) daban un 504 al
# superar ese minuto. Subimos el timeout a 1800s (30 min). Idempotente.

set -euo pipefail

echo "→ 0045: subir proxy_read_timeout del location /api/ del panel…"

CONF=/etc/nginx/sites-available/svqpanel
[ -f "$CONF" ] || { echo "  No existe $CONF — nada que hacer."; exit 0; }

if grep -qE "proxy_read_timeout\s+1800s" "$CONF"; then
    echo "  Ya estaba aplicado, nada que hacer."
    exit 0
fi

# Insertar las directivas justo después de la línea 'location /api/ {'.
# Usamos awk para no depender de la posición exacta de otras líneas.
python3 - "$CONF" <<'PYEOF'
import re, sys
conf = sys.argv[1]
with open(conf) as f:
    text = f.read()

# Inyecta el timeout dentro del bloque 'location /api/ { ... }' si no lo tiene.
def add_timeout(m):
    block = m.group(0)
    if "proxy_read_timeout" in block:
        return block
    # Insertar antes del cierre del bloque (última '}').
    inject = ("        # migración/SSL/restauraciones pueden tardar > 60s\n"
              "        proxy_read_timeout 1800s;\n"
              "        proxy_send_timeout 1800s;\n")
    idx = block.rstrip().rfind("}")
    return block[:idx] + inject + block[idx:]

new = re.sub(r"location\s+/api/\s*\{.*?\n\s*\}",
             add_timeout, text, count=1, flags=re.DOTALL)

if new != text:
    with open(conf, "w") as f:
        f.write(new)
    print("  ✓ timeout inyectado en location /api/")
else:
    print("  No se pudo localizar el bloque location /api/ (¿config personalizada?)")
PYEOF

if nginx -t 2>/dev/null; then
    systemctl reload nginx
    echo "✓ 0045: nginx recargado con el nuevo timeout"
else
    echo "  ⚠ nginx -t falló tras el cambio; revisa $CONF. No se recargó."
    exit 1
fi

exit 0
