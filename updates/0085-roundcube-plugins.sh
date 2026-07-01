#!/bin/bash
# 0085-roundcube-plugins.sh
#
# Activa plugins útiles del webmail (Roundcube) en servidores ya instalados:
#   - markasjunk: botón Spam/No-spam. NO usa driver de learning propio; solo MUEVE
#     el correo a Junk (y de Junk→Inbox para "no es spam"). El aprendizaje Bayes lo
#     dispara el imapsieve del sistema al entrar/salir de Junk (learn-spam/ham), así
#     no duplicamos lógica ni exponemos rspamc al webmail.
#   - zipdownload: descargar varios adjuntos en un ZIP.
#   - archive: botón Archivar (carpeta Archive).
#   - attachment_reminder: avisa si mencionas un adjunto y no lo pusiste.
#
# Todos vienen ya incluidos en el Roundcube que instalamos (no hay que descargar
# nada). Idempotente y no interactivo.

set -u

echo "→ 0085: activar plugins del webmail (markasjunk + zipdownload + archive + attachment_reminder)…"

RC=/var/www/roundcube
CONF="$RC/config/config.inc.php"

if [ ! -f "$CONF" ]; then
    echo "  · Roundcube no instalado; nada que hacer"
    exit 0
fi

# Comprobar que los plugins existen en la instalación (vienen con el .tar completo)
for p in markasjunk zipdownload archive attachment_reminder; do
    if [ ! -d "$RC/plugins/$p" ]; then
        echo "  ✗ falta el plugin $p en $RC/plugins (¿Roundcube incompleto?); abortando"
        exit 1
    fi
done

python3 - "$CONF" <<'PYEOF'
import re, sys
p = sys.argv[1]
s = open(p).read()
orig = s

WANT = ['svqpanel_autologin', 'markasjunk', 'zipdownload', 'archive', 'attachment_reminder']

# 1) Reescribir el array $config['plugins'] = [...] preservando svqpanel_autologin
m = re.search(r"\$config\['plugins'\]\s*=\s*\[(.*?)\]\s*;", s, flags=re.DOTALL)
if m:
    current = re.findall(r"'([^']+)'", m.group(1))
    # unir: mantener lo que hubiera + añadir lo que falte, sin duplicar
    merged = list(dict.fromkeys(current + WANT))
    newarr = "$config['plugins'] = [" + ", ".join(f"'{x}'" for x in merged) + "];"
    s = s[:m.start()] + newarr + s[m.end():]
else:
    # no había línea de plugins: añadirla
    s = s.rstrip() + "\n$config['plugins'] = [" + ", ".join(f"'{x}'" for x in WANT) + "];\n"

# 2) Añadir la config de markasjunk/archive si no está (idempotente)
if 'markasjunk_learning_driver' not in s:
    block = """
// ── markasjunk (botón Spam/No-spam): solo mueve a Junk; el aprendizaje Bayes
//    lo dispara el imapsieve del sistema al entrar/salir de Junk ──
$config['markasjunk_learning_driver'] = null;
$config['markasjunk_read_spam']       = true;
$config['markasjunk_unread_ham']      = false;
$config['markasjunk_spam_mbox']       = 'Junk';
$config['markasjunk_ham_mbox']        = 'INBOX';
$config['archive_mbox'] = 'Archive';
"""
    # insertar antes del cierre PHP (?>) si existe, o al final
    if '?>' in s:
        s = s.replace('?>', block + "\n?>", 1)
    else:
        s = s.rstrip() + "\n" + block

if s != orig:
    open(p, 'w').write(s)
    print("  ✓ config.inc.php actualizado (plugins + config markasjunk/archive)")
else:
    print("  · config.inc.php ya estaba al día")
PYEOF

# Validar sintaxis PHP del config antes de dar por bueno (si php-cli está)
if command -v php >/dev/null 2>&1; then
    if php -l "$CONF" >/dev/null 2>&1; then
        echo "  ✓ config.inc.php con sintaxis PHP válida"
    else
        echo "  ✗ config.inc.php con error de sintaxis PHP; revisar (no se revierte solo)"
        php -l "$CONF" 2>&1 | head -3
        exit 1
    fi
fi

echo "✓ 0085: plugins del webmail activados"
exit 0
