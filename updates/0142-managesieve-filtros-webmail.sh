#!/bin/bash
# 0142-managesieve-filtros-webmail.sh
#
# Activa los FILTROS de correo del usuario (Sieve) en el webmail: el botón
# "Filtros" de Roundcube (Configuración → Filtros), que permite crear reglas del
# tipo "si viene de X, muévelo a la carpeta Y". Hasta ahora no existía: sólo
# teníamos dovecot-sieve (para el aprendizaje Bayes), no el servicio ManageSieve
# que permite EDITAR filtros desde el webmail.
#
# Qué hace:
#   1. Instala dovecot-managesieved (servicio ManageSieve, puerto 4190).
#   2. Drop-in 92-svqpanel-managesieve.conf:
#      - añade `sieve = yes` a `protocols` (en Dovecot 2.4 el servicio NO arranca
#        sin esto, aunque el paquete esté instalado),
#      - declara el listener SOLO en 127.0.0.1:4190 (lo consume Roundcube, que
#        corre en la misma máquina). NO se expone a Internet: menos superficie de
#        ataque y no hace falta abrir firewall ni jail de fail2ban,
#      - declara el sieve_script PERSONAL (type = personal). Sin él, ManageSieve
#        guardaría los filtros del usuario en un script que NUNCA se ejecuta en la
#        entrega: el cliente crearía reglas, las vería guardadas, y no harían nada.
#   3. Activa el plugin `managesieve` en Roundcube (ya viene en la instalación).
#
# ⚠️ Los scripts globales existentes son `type = before` (spam-to-junk, learn-*),
# y los `before` se ejecutan ANTES que el personal → el spam→Junk y el
# aprendizaje Bayes siguen mandando. Los filtros del usuario no los pisan.
#
# Idempotente y no interactivo. Valida con `doveconf -n` ANTES de reiniciar y
# revierte el drop-in si la config queda inválida (Dovecot roto = TODO el correo
# caído).

set -u

echo "→ 0142: activar filtros de correo (ManageSieve) en el webmail…"

DROPIN=/etc/dovecot/conf.d/92-svqpanel-managesieve.conf
RC=/var/www/roundcube
CONF="$RC/config/config.inc.php"

# ── 0. ¿Hay Dovecot? Si no hay correo en este servidor, no hay nada que hacer ──
if ! command -v doveconf >/dev/null 2>&1; then
    echo "  · Dovecot no instalado; nada que hacer"
    exit 0
fi

# ── 1. Paquete dovecot-managesieved ───────────────────────────────────────────
if dpkg -l 2>/dev/null | grep -q '^ii  dovecot-managesieved'; then
    echo "  · dovecot-managesieved ya instalado"
else
    echo "  → instalando dovecot-managesieved…"
    export DEBIAN_FRONTEND=noninteractive
    if ! apt-get install -y -qq dovecot-managesieved; then
        echo "  ✗ no se pudo instalar dovecot-managesieved; abortando"
        exit 1
    fi
    echo "  ✓ dovecot-managesieved instalado"
fi

# ── 2. Drop-in de Dovecot ─────────────────────────────────────────────────────
# Guardar copia del anterior (si existía) para poder revertir.
BACKUP=""
if [ -f "$DROPIN" ]; then
    BACKUP="${DROPIN}.bak.$$"
    cp -a "$DROPIN" "$BACKUP"
fi

cat > "$DROPIN" <<'EOF'
# SVQPanel — ManageSieve: filtros de correo del usuario desde el webmail.
# NO editar a mano (lo gestiona updates/0142 e install.sh).

# En Dovecot 2.4 el servicio managesieve NO arranca si 'sieve' no está en
# protocols, aunque el paquete dovecot-managesieved esté instalado.
protocols {
  sieve = yes
}

# Listener SOLO en localhost: lo consume Roundcube, que corre en esta máquina.
# No se expone a Internet (sin firewall que abrir ni jail de fail2ban que añadir).
# ⚠️ Dovecot 2.4: la restricción de IP va en `listen` a nivel de SERVICE. La
# directiva `address` dentro de inet_listener (sintaxis 2.3) ya NO existe y hace
# que Dovecot aborte con "Unknown setting: address".
# ⚠️ El paquete instala su propio 20-managesieve.conf que abre 4190 y ADEMÁS 2000
# (sieve_deprecated) en todas las interfaces. Este drop-in (92-, se lee después)
# los sobreescribe: fija listen a localhost y apaga el 2000 con port = 0.
service managesieve-login {
  listen = 127.0.0.1
  inet_listener sieve {
    port = 4190
  }
  inet_listener sieve_deprecated {
    port = 0
  }
}

# ⚠️ Los Sieve NO pueden vivir en ~/: el home del buzón y el maildir son el MISMO
# directorio (mail_path = ~/) y en Maildir++ toda entrada que empieza por '.' es
# una CARPETA DE CORREO. Con path = ~/sieve, el '~/.dovecot.sieve' de ManageSieve
# le sale al cliente como carpeta fantasma "dovecot.sieve" y, peor, 'fileinto'
# intenta escribir en '.dovecot.sieve/tmp' → la entrega falla con
# "451 4.2.0 Internal error" y el correo SE QUEDA EN COLA. Por eso van fuera.
#
# Script PERSONAL del usuario: aquí es donde ManageSieve guarda los filtros que
# el cliente crea en el webmail. Sin esta declaración los filtros se guardarían
# pero NO se ejecutarían en la entrega.
sieve_script personal {
  type = personal
  path = /var/lib/dovecot/sieve-users/%{user}/scripts
  active_path = /var/lib/dovecot/sieve-users/%{user}/active.sieve
}

# Script de AUTO-RESPUESTA, que escribe el PANEL. Va aparte (type = before) para
# que auto-respuesta y filtros CONVIVAN: antes ambos peleaban por
# '~/.dovecot.sieve' y el que escribía último borraba al otro (abrir la pestaña
# Filtros en el webmail desactivaba la auto-respuesta, y activar una
# auto-respuesta desde el panel borraba los filtros del cliente).
# Orden de ejecución: globales 'before' (spam→Junk, learn-*) → autoreply →
# personal. El antispam y el Bayes siguen mandando sobre todo lo demás.
sieve_script autoreply {
  type = before
  path = /var/lib/dovecot/sieve-users/%{user}/autoreply.sieve
}
EOF

echo "  ✓ $DROPIN escrito"

# ── 3. Validar la config ANTES de reiniciar (Dovecot roto = correo caído) ─────
if ! doveconf -n >/dev/null 2>&1; then
    echo "  ✗ la config de Dovecot queda INVÁLIDA con el drop-in; revirtiendo…"
    doveconf -n 2>&1 | tail -5
    if [ -n "$BACKUP" ]; then
        mv -f "$BACKUP" "$DROPIN"
    else
        rm -f "$DROPIN"
    fi
    echo "  ✓ revertido (Dovecot intacto)"
    exit 1
fi
echo "  ✓ config de Dovecot válida"

# Backup ya no hace falta
[ -n "$BACKUP" ] && rm -f "$BACKUP"

# ── 4. Reiniciar Dovecot y comprobar que el 4190 escucha ──────────────────────
systemctl restart dovecot || {
    echo "  ✗ fallo al reiniciar Dovecot; revisar 'journalctl -u dovecot'"
    exit 1
}

# Dar un margen a que el listener levante
for _ in 1 2 3 4 5; do
    if ss -lnt 2>/dev/null | grep -q '127.0.0.1:4190'; then
        break
    fi
    sleep 1
done

if ss -lnt 2>/dev/null | grep -q '127.0.0.1:4190'; then
    echo "  ✓ ManageSieve escuchando en 127.0.0.1:4190"
else
    echo "  ✗ el puerto 4190 NO escucha tras reiniciar; revisar 'journalctl -u dovecot'"
    exit 1
fi

# Comprobar que NO quedó expuesto a Internet (el paquete abre 4190 y 2000 en
# todas las interfaces; nuestro drop-in debe haberlos restringido/apagado).
if ss -lnt 2>/dev/null | grep -E ':(4190|2000)\b' | grep -qv '127.0.0.1'; then
    echo "  ✗ ManageSieve expuesto fuera de localhost; revisar el drop-in:"
    ss -lnt 2>/dev/null | grep -E ':(4190|2000)\b'
    exit 1
fi
echo "  ✓ no expuesto fuera de localhost (2000 'deprecated' cerrado)"

# ── 4b. Migrar las auto-respuestas que aún viven dentro del maildir ───────────
# Hasta ahora el panel escribía la auto-respuesta en '~/.dovecot.sieve', dentro
# del maildir. Se mueven a /var/lib/dovecot/sieve-users/<email>/autoreply.sieve,
# que es donde las busca el sieve_script 'autoreply' declarado arriba. Sin este
# paso, los buzones con auto-respuesta activa la perderían al aplicar el update.
SIEVE_USERS=/var/lib/dovecot/sieve-users
mkdir -p "$SIEVE_USERS"
chown vmail:vmail "$SIEVE_USERS"
chmod 700 "$SIEVE_USERS"

migrados=0
# Los maildir viven en /home/<panel_user>/mail/<dominio>/<buzon>/
for sieve in /home/*/mail/*/*/.dovecot.sieve; do
    [ -e "$sieve" ] || continue
    # Un symlink aquí es de ManageSieve (no del panel): no es una auto-respuesta.
    [ -L "$sieve" ] && continue

    box=$(dirname "$sieve")
    mailbox=$(basename "$box")
    domain=$(basename "$(dirname "$box")")
    email="${mailbox}@${domain}"

    dest="$SIEVE_USERS/$email"
    mkdir -p "$dest/scripts"

    # No pisar una auto-respuesta ya migrada (idempotencia).
    if [ ! -f "$dest/autoreply.sieve" ]; then
        cp -a "$sieve" "$dest/autoreply.sieve"
        migrados=$((migrados + 1))
    fi

    # Quitar del maildir el script y sus binarios: si se quedan, Dovecot los
    # sigue mostrando como carpeta fantasma y 'fileinto' vuelve a romper.
    rm -f "$sieve" "${sieve}c" "$box/.dovecot.svbin" "$box/.dovecot.sieve.log"

    chown -R vmail:vmail "$dest"
    chmod -R u+rwX,go-rwx "$dest"
done

if [ "$migrados" -gt 0 ]; then
    # Compilar como vmail: si compila root, el .svbin queda ilegible para Dovecot
    # (euid vmail) y la entrega falla con 451 dejando el correo en cola.
    for s in "$SIEVE_USERS"/*/autoreply.sieve; do
        [ -e "$s" ] || continue
        su -s /bin/sh vmail -c "sievec $(printf '%q' "$s")" 2>/dev/null || \
            echo "  · aviso: no compiló $s (se revisará al reactivar la auto-respuesta)"
    done
    echo "  ✓ $migrados auto-respuesta(s) migradas fuera del maildir"
else
    echo "  · no había auto-respuestas que migrar"
fi

# ── 5. Activar el plugin managesieve en Roundcube ─────────────────────────────
if [ ! -f "$CONF" ]; then
    echo "  · Roundcube no instalado; Dovecot listo, sin webmail que configurar"
    exit 0
fi

if [ ! -d "$RC/plugins/managesieve" ]; then
    echo "  ✗ falta el plugin managesieve en $RC/plugins (¿Roundcube incompleto?)"
    exit 1
fi

cp -a "$CONF" "${CONF}.bak.0142"

python3 - "$CONF" <<'PYEOF'
import re, sys
p = sys.argv[1]
s = open(p).read()
orig = s

# 1) Añadir 'managesieve' al array de plugins (sin duplicar, preservando el resto)
m = re.search(r"\$config\['plugins'\]\s*=\s*\[(.*?)\]\s*;", s, flags=re.DOTALL)
if m:
    current = re.findall(r"'([^']+)'", m.group(1))
    if 'managesieve' not in current:
        merged = current + ['managesieve']
        newarr = "$config['plugins'] = [" + ", ".join(f"'{x}'" for x in merged) + "];"
        s = s[:m.start()] + newarr + s[m.end():]
else:
    s = s.rstrip() + "\n$config['plugins'] = ['managesieve'];\n"

# 2) Config del plugin (idempotente)
if 'managesieve_host' not in s:
    block = """
// ── managesieve: filtros de correo del usuario (Configuración → Filtros) ──
// Habla con el ManageSieve de Dovecot en localhost:4190 (no expuesto a Internet).
// managesieve_kolab_master=false y sin TLS: la conexión no sale de la máquina.
$config['managesieve_host'] = 'localhost:4190';
$config['managesieve_usetls'] = false;
// Sin managesieve_default: no tenemos plantilla de filtros por defecto y apuntar
// a un fichero inexistente hace que el plugin avise por cada usuario.
$config['managesieve_script_name'] = 'managesieve';
// Mostrar sólo el editor de filtros por formulario (no el código Sieve en crudo),
// que es lo que espera un usuario final.
$config['managesieve_raw_editor'] = false;
"""
    if '?>' in s:
        s = s.replace('?>', block + "\n?>", 1)
    else:
        s = s.rstrip() + "\n" + block

if s != orig:
    open(p, 'w').write(s)
    print("  ✓ config.inc.php actualizado (plugin managesieve + config)")
else:
    print("  · config.inc.php ya estaba al día")
PYEOF

# Validar sintaxis PHP; si está rota, revertir (webmail caído = clientes sin correo)
if command -v php >/dev/null 2>&1; then
    if php -l "$CONF" >/dev/null 2>&1; then
        echo "  ✓ config.inc.php con sintaxis PHP válida"
        rm -f "${CONF}.bak.0142"
    else
        echo "  ✗ config.inc.php con error de sintaxis PHP; revirtiendo…"
        php -l "$CONF" 2>&1 | head -3
        mv -f "${CONF}.bak.0142" "$CONF"
        echo "  ✓ config.inc.php revertido"
        exit 1
    fi
else
    rm -f "${CONF}.bak.0142"
fi

echo "✓ 0142: filtros de correo activados (Roundcube → Configuración → Filtros)"
exit 0
