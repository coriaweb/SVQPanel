#!/bin/bash
# 0057-unificar-carpeta-spam-junk.sh
#
# Unifica la carpeta de spam en 'Junk' (la canónica del sistema):
#
#   - Dovecot define special_use \Junk y el APRENDIZAJE imapsieve de Rspamd está
#     enganchado a 'Junk'. Pero Roundcube tenía junk_mbox = 'Spam', creando una
#     carpeta 'Spam' paralela donde lo que el usuario marcaba NO se aprendía y
#     adonde el nuevo Sieve spam→Junk (update 0056) NO mueve. Resultado: spam
#     repartido en dos carpetas y aprendizaje roto.
#
# Acciones (idempotentes):
#   1) Roundcube: junk_mbox = 'Junk'.
#   2) Mover el contenido de 'Spam' a 'Junk' en todos los buzones (doveadm move,
#      respeta índices). Solo si 'Spam' tiene mensajes.
#   3) Reentrenar Bayes con el spam que quede en 'Junk' de cada buzón.
#
# No interactivo. Seguro de re-ejecutar (si 'Spam' ya está vacía, no hace nada).

set -u

echo "→ 0057: unificar carpeta de spam en 'Junk'…"

# Sin correo instalado, nada que hacer.
if ! command -v doveadm >/dev/null 2>&1; then
    echo "✓ 0057: doveadm no instalado (¿servidor sin correo?); nada que hacer"
    exit 0
fi

# 1) Roundcube → junk_mbox = 'Junk' (varias rutas posibles del config).
for RC in /var/www/roundcube/config/config.inc.php \
          /var/www/webmail/config/config.inc.php; do
    [ -f "$RC" ] || continue
    if grep -qE "junk_mbox'\]\s*=\s*'Spam'" "$RC"; then
        sed -i -E "s/(junk_mbox'\]\s*=\s*)'Spam'/\1'Junk'/" "$RC"
        echo "  ✓ Roundcube ($RC): junk_mbox → Junk"
    fi
done

# 2) Migrar Spam → Junk en cada buzón (doveadm sabe la lista de usuarios).
#    Se usa 'doveadm move ... ALL'; si Spam no existe o está vacía, no falla.
MOVED=0
while IFS= read -r U; do
    [ -z "$U" ] && continue
    # ¿Tiene mensajes en Spam?
    N=$(doveadm mailbox status -u "$U" messages Spam 2>/dev/null | grep -oE 'messages=[0-9]+' | cut -d= -f2)
    [ -z "$N" ] && continue
    if [ "$N" -gt 0 ] 2>/dev/null; then
        if doveadm move -u "$U" Junk mailbox Spam ALL 2>/dev/null; then
            echo "  ✓ $U: $N correos Spam → Junk"
            MOVED=$((MOVED + 1))
        else
            echo "  ⚠ $U: no se pudo mover Spam → Junk"
        fi
    fi
done < <(doveadm user '*' 2>/dev/null | cut -f1)

# 3) Reentrenar Bayes con el Junk de cada buzón (best-effort; no crítico).
if command -v rspamc >/dev/null 2>&1; then
    while IFS= read -r U; do
        [ -z "$U" ] && continue
        # Localizar el maildir de Junk del usuario.
        HOME_DIR=$(doveadm user -f home "$U" 2>/dev/null)
        [ -z "$HOME_DIR" ] && continue
        for DOM_DIR in "$HOME_DIR"/mail/*; do
            JUNK="$DOM_DIR/.Junk"
            [ -d "$JUNK" ] || continue
            rspamc learn_spam "$JUNK/cur/" "$JUNK/new/" >/dev/null 2>&1 || true
        done
    done < <(doveadm user '*' 2>/dev/null | cut -f1)
    echo "  ✓ Bayes reentrenado con el spam de las carpetas Junk"
fi

echo "✓ 0057: spam unificado en 'Junk' (movidos $MOVED buzones)"
exit 0
