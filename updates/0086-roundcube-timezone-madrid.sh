#!/bin/bash
# 0086-roundcube-timezone-madrid.sh
#
# Fija la zona horaria por defecto del webmail (Roundcube) a Europe/Madrid en
# servidores ya instalados. Sin esto, Roundcube usa 'auto' → suele quedar en UTC
# y las fechas de los correos salen 1-2h atrasadas, obligando a cada usuario a
# corregirlo a mano en sus Ajustes.
#
# Es solo el DEFAULT global: cada usuario puede seguir cambiándola en
# Ajustes → Preferencias → Fecha y hora (su preferencia manda sobre este valor).
#
# Idempotente y no interactivo.

set -u

echo "→ 0086: zona horaria por defecto del webmail = Europe/Madrid…"

RC=/var/www/roundcube
CONF="$RC/config/config.inc.php"

if [ ! -f "$CONF" ]; then
    echo "  · Roundcube no instalado; nada que hacer"
    exit 0
fi

python3 - "$CONF" <<'PYEOF'
import re, sys
p = sys.argv[1]
s = open(p).read()
orig = s

LINE = "$config['timezone'] = 'Europe/Madrid';"

m = re.search(r"\$config\['timezone'\]\s*=\s*[^;]+;", s)
if m:
    # ya existe: normalizar a Europe/Madrid solo si es distinto
    if m.group(0) != LINE:
        s = s[:m.start()] + LINE + s[m.end():]
else:
    # no existe: insertar antes del cierre PHP (?>) si lo hay, o al final
    block = ("\n// Zona horaria por defecto para todas las cuentas (España peninsular).\n"
             "// El usuario puede sobreescribirla en Ajustes → Fecha y hora.\n"
             + LINE + "\n")
    if '?>' in s:
        s = s.replace('?>', block + "?>", 1)
    else:
        s = s.rstrip() + "\n" + block

if s != orig:
    open(p, 'w').write(s)
    print("  ✓ config.inc.php: timezone = Europe/Madrid")
else:
    print("  · config.inc.php ya tenía Europe/Madrid")
PYEOF

# Validar sintaxis PHP del config antes de darlo por bueno (si php-cli está)
if command -v php >/dev/null 2>&1; then
    if php -l "$CONF" >/dev/null 2>&1; then
        echo "  ✓ config.inc.php con sintaxis PHP válida"
    else
        echo "  ✗ config.inc.php con error de sintaxis PHP; revisar"
        php -l "$CONF" 2>&1 | head -3
        exit 1
    fi
fi

echo "✓ 0086: zona horaria del webmail fijada a Europe/Madrid"
exit 0
