#!/bin/bash
# 0160-nginx-server-name-sin-ipv6.sh
#
# Quita la IPv6 literal del server_name de los vhosts nginx de dominios.
#
# Se añadía para servir la web en http://[ipv6]/, pero nunca coincidía: el
# navegador manda "Host: [ipv6]" (con corchetes) y nginx lo mandaba igualmente
# al vhost por defecto. Solo producía "conflicting server name ... ignored" en
# nginx -t cuando dos dominios compartían IPv6. Probado en socios.zococoria.es
# (oct 2026): respuestas idénticas antes/después por nombre (v4/v6) y por IP.
# El generador ya no la escribe; esto limpia los vhosts existentes.
#
# Cambio quirúrgico (solo esas líneas, no regenera los vhosts). Copia previa y
# si nginx -t falla, se restaura todo. Idempotente. Solo código del panel → no
# requiere cambio en install.sh (un servidor nuevo nace sin la IPv6).

set -u

echo "-> 0160: IPv6 literal fuera del server_name de los vhosts nginx..."

DIR=/etc/nginx/sites-available
if [ ! -d "$DIR" ] || ! command -v nginx >/dev/null 2>&1; then
    echo "  . sin nginx; se omite"
    echo "OK 0160: sin cambios"
    exit 0
fi

# Token IPv6 (lleva ':', un nombre de dominio nunca) dentro de líneas server_name.
RE='/^[[:space:]]*server_name[[:space:]]/ s/ [0-9a-fA-F]*:[0-9a-fA-F:]*([ ;])/\1/g'

BK=/var/backups/svqpanel-0160-$(date +%Y%m%d%H%M%S)
changed=()
for f in "$DIR"/*; do
    [ -f "$f" ] || continue
    if grep -Eq '^[[:space:]]*server_name[[:space:]].* [0-9a-fA-F]*:[0-9a-fA-F:]*[ ;]' "$f"; then
        mkdir -p "$BK"
        cp -a "$f" "$BK/"
        # Dos pasadas: dos IPv6 seguidas comparten el espacio separador.
        sed -E -i "$RE; $RE" "$f"
        changed+=("$f")
    fi
done

if [ ${#changed[@]} -eq 0 ]; then
    echo "OK 0160: ningún vhost con IPv6 en server_name"
    exit 0
fi

if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx
    echo "  OK ${#changed[@]} vhost(s) limpiados (copia en $BK)"
else
    echo "  !! nginx -t falla tras el cambio: restaurando los ${#changed[@]} vhost(s)"
    cp -a "$BK"/* "$DIR/"
    nginx -t >/dev/null 2>&1 && systemctl reload nginx
    echo "OK 0160: revertido (revisar a mano; copia en $BK)"
    exit 0
fi

echo "OK 0160: server_name sin IPv6"
exit 0
