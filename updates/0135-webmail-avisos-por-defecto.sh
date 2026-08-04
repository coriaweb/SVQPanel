#!/bin/bash
# 0135-webmail-avisos-por-defecto.sh
#
# Remata el 0134: attachment_reminder y newmail_notifier son preferencias POR
# USUARIO que de fábrica vienen a false — los plugins estaban activos pero no
# hacían NADA hasta que cada usuario los activara a mano en sus preferencias
# (descubierto en la primera prueba real: "adjunto un archivo" sin adjuntar y
# ningún aviso al enviar). Se activan por defecto a nivel global; el usuario
# que no los quiera puede apagarlos en Configuración → Preferencias.
#
# Idempotente y no interactivo.

set -u

echo "→ 0135: activar por defecto el aviso de adjunto olvidado y el de correo nuevo…"

RC=/var/www/roundcube
CONF="$RC/config/config.inc.php"

if [ ! -f "$CONF" ]; then
    echo "  · Roundcube no instalado; nada que hacer"
    exit 0
fi

python3 - "$CONF" <<'PYEOF'
import sys
p = sys.argv[1]
s = open(p).read()
orig = s

block = """
// attachment_reminder y newmail_notifier ACTIVOS por defecto: son preferencias
// por usuario que de fábrica vienen a false (sin esto los plugins no hacen nada).
// El usuario puede apagarlos en Configuración → Preferencias.
$config['attachment_reminder'] = true;
$config['newmail_notifier_basic'] = true;
"""

if "$config['attachment_reminder']" not in s:
    if '?>' in s:
        s = s.replace('?>', block + "\n?>", 1)
    else:
        s = s.rstrip() + "\n" + block

if s != orig:
    open(p, 'w').write(s)
    print("  ✓ config.inc.php: avisos activados por defecto")
else:
    print("  · config.inc.php ya estaba al día")
PYEOF

if command -v php >/dev/null 2>&1; then
    if php -l "$CONF" >/dev/null 2>&1; then
        echo "  ✓ config.inc.php con sintaxis PHP válida"
    else
        echo "  ✗ config.inc.php con error de sintaxis PHP; revisar"
        php -l "$CONF" 2>&1 | head -3
        exit 1
    fi
fi

echo "✓ 0135: avisos del webmail activos por defecto"
exit 0
