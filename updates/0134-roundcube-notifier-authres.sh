#!/bin/bash
# 0134-roundcube-notifier-authres.sh
#
# Activa dos plugins más del webmail (Roundcube) en servidores ya instalados:
#   - newmail_notifier: notificación de escritorio/sonido al llegar correo
#     nuevo. Viene incluido con Roundcube; solo hay que activarlo.
#   - authres_status: icono con el resultado SPF/DKIM/DMARC de cada correo
#     recibido (el cliente ve de un vistazo si un correo viene autenticado o
#     es sospechoso de spoofing). Es de TERCEROS (pimlie/authres_status):
#     se descarga FIJADO a la versión 0.7.1 — misma versión que instala
#     install.sh; subirla es un cambio de código consciente, no un "latest".
#
# roundcube_updater preserva plugins/ al actualizar Roundcube, así que el
# plugin de terceros sobrevive a las actualizaciones del webmail.
# Idempotente y no interactivo.

set -u

echo "→ 0134: plugins webmail newmail_notifier + authres_status…"

RC=/var/www/roundcube
CONF="$RC/config/config.inc.php"
AUTHRES_VER="0.7.1"

if [ ! -f "$CONF" ]; then
    echo "  · Roundcube no instalado; nada que hacer"
    exit 0
fi

# newmail_notifier viene con Roundcube; si no está, la instalación es incompleta.
if [ ! -d "$RC/plugins/newmail_notifier" ]; then
    echo "  ✗ falta newmail_notifier en $RC/plugins (¿Roundcube incompleto?); abortando"
    exit 1
fi

# authres_status: descargar (fijado a versión) solo si no existe ya.
if [ ! -d "$RC/plugins/authres_status" ]; then
    if curl -fsSL "https://github.com/pimlie/authres_status/archive/refs/tags/${AUTHRES_VER}.tar.gz" \
            -o /tmp/authres_status.tar.gz \
        && tar -xzf /tmp/authres_status.tar.gz -C /tmp/ \
        && mv "/tmp/authres_status-${AUTHRES_VER}" "$RC/plugins/authres_status"; then
        rm -f /tmp/authres_status.tar.gz
        echo "  ✓ authres_status ${AUTHRES_VER} descargado"
    else
        rm -f /tmp/authres_status.tar.gz
        echo "  ✗ no se pudo descargar authres_status; abortando sin tocar config"
        exit 1
    fi
else
    echo "  · authres_status ya presente"
fi

python3 - "$CONF" <<'PYEOF'
import re, sys
p = sys.argv[1]
s = open(p).read()
orig = s

WANT = ['newmail_notifier', 'authres_status']

m = re.search(r"\$config\['plugins'\]\s*=\s*\[(.*?)\]\s*;", s, flags=re.DOTALL)
if m:
    current = re.findall(r"'([^']+)'", m.group(1))
    merged = list(dict.fromkeys(current + WANT))
    newarr = "$config['plugins'] = [" + ", ".join(f"'{x}'" for x in merged) + "];"
    s = s[:m.start()] + newarr + s[m.end():]
else:
    s = s.rstrip() + "\n$config['plugins'] = [" + ", ".join(f"'{x}'" for x in WANT) + "];\n"

if s != orig:
    open(p, 'w').write(s)
    print("  ✓ config.inc.php actualizado (plugins añadidos)")
else:
    print("  · config.inc.php ya estaba al día")
PYEOF

# Validar sintaxis PHP del config antes de dar por bueno
if command -v php >/dev/null 2>&1; then
    if php -l "$CONF" >/dev/null 2>&1; then
        echo "  ✓ config.inc.php con sintaxis PHP válida"
    else
        echo "  ✗ config.inc.php con error de sintaxis PHP; revisar"
        php -l "$CONF" 2>&1 | head -3
        exit 1
    fi
fi

echo "✓ 0134: newmail_notifier + authres_status activados"
exit 0
