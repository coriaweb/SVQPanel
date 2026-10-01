#!/bin/bash
# 0156-fail2ban-jail-local-reparar.sh
#
# Repara el /etc/fail2ban/jail.local de las instalaciones que nacieron con
# fail2ban CAÍDO.
#
# Causa (vista en el install limpio de oct 2026, svq-beyuri1): el jail.local del
# install llevaba en la sección [sshd] un comentario "...los hereda del [DEFAULT]."
# y el update 0079 delimitaba la sección con [^\[]*, que se cortaba en ese
# corchete del comentario. Al no ver maxretry en el trozo, insertaba
# maxretry/findtime/bantime EN MITAD DEL COMENTARIO, dejando "[DEFAULT]." sola en
# una línea: fail2ban la lee como cabecera DEFAULT, encuentra maxretry duplicado
# ("option 'maxretry' in section 'DEFAULT' already exists") y no arranca.
#
# El fix de raíz va en install.sh (comentario sin corchetes) y en 0079 (sección
# delimitada por cabeceras al inicio de línea + validar antes de escribir). Este
# update arregla los servidores ya instalados:
#   1) quita la cabecera mal formada "[DEFAULT]." y sus maxretry/findtime/bantime
#      duplicados (los buenos ya quedaron dentro de [sshd]);
#   2) recompone el comentario partido;
#   3) valida con fail2ban-client -t; si no valida, restaura el original;
#   4) si valida, (re)arranca fail2ban.
# Idempotente: en un jail.local sano no cambia nada.

set -u

echo "-> 0156: reparar jail.local de fail2ban (cabecera [DEFAULT]. duplicada)..."

JAIL=/etc/fail2ban/jail.local
if [ ! -f "$JAIL" ] || ! command -v fail2ban-client >/dev/null 2>&1; then
    echo "  . fail2ban/jail.local no presente; se omite"
    echo "OK 0156: sin cambios"
    exit 0
fi

cp -p "$JAIL" "$JAIL.svq-0156.bak"

python3 - "$JAIL" <<'PYEOF'
import re, sys
p = sys.argv[1]
s = open(p).read()
orig = s

# 1) Cabecera mal formada "[DEFAULT]." (u otra basura tras el corchete) + las
#    opciones que la siguen: duplican maxretry/findtime/bantime en el DEFAULT real.
s = re.sub(r"(?m)^\[DEFAULT\][^\n\s]+[^\n]*\n(?:[ \t]*(?:maxretry|findtime|bantime)[ \t]*=.*\n)*",
           "", s)

# 2) Comentario partido: "...los hereda del\n" → frase completa sin corchetes.
s = re.sub(r"(?m)^(# para cualquier IP que reincida\. El factor/maxtime los hereda)[ \t]+del[ \t]*$",
           r"\1 de la sección DEFAULT.", s)

if s != orig:
    open(p, "w").write(s)
    print("  OK jail.local corregido")
else:
    print("  . jail.local ya estaba sano")
PYEOF

if fail2ban-client -t >/dev/null 2>&1; then
    rm -f "$JAIL.svq-0156.bak"
    systemctl enable fail2ban >/dev/null 2>&1 || true
    systemctl reset-failed fail2ban >/dev/null 2>&1 || true
    systemctl restart fail2ban >/dev/null 2>&1 || true
    sleep 2
    echo "  OK fail2ban: $(systemctl is-active fail2ban 2>&1)"
else
    mv -f "$JAIL.svq-0156.bak" "$JAIL"
    echo "  WARN la config de fail2ban no valida; jail.local restaurado sin cambios:"
    fail2ban-client -t 2>&1 | grep -i error | tail -3
fi

echo "OK 0156: jail.local de fail2ban revisado"
exit 0
