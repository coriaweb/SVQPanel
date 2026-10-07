#!/bin/bash
# 0163-logrotate-logs-dominios.sh
#
# 1. Instala la rotación de los logs web de cada dominio
#    (/home/*/web/*/logs/{nginx,apache}.{access,error}.log). Antes NO se rotaban
#    nunca: en producción sumaban 10 GB, con un dominio de 5,4 GB.
#    La config vive en config/logrotate/svqpanel-domains (misma fuente que
#    install.sh): semanal o al pasar de 500 MB, 10 rotaciones comprimidas,
#    copytruncate (nadie tiene que reabrir el fichero).
#    La primera rotación la hace el logrotate de esa noche, no este script.
#
# 2. Devuelve logs/ de cada dominio a usuario:www-data 750 (como la crea el
#    panel). El importador de Hestia la dejaba usuario:usuario y los workers de
#    nginx no podían reabrir los logs al rotar: ~620 "[emerg] Permission denied"
#    cada noche en /var/log/nginx/error.log.
#
# Idempotente y no interactivo.

set -euo pipefail

echo "→ 0163: rotación de logs de los dominios…"

SRC=/opt/svqpanel/config/logrotate/svqpanel-domains
DST=/etc/logrotate.d/svqpanel-domains

if [[ -f "$SRC" ]]; then
    if ! cmp -s "$SRC" "$DST" 2>/dev/null; then
        install -m 0644 "$SRC" "$DST"
        echo "  ✓ instalado $DST"
    else
        echo "  $DST ya al día"
    fi
    # Validar sin rotar nada (-d = depuración/ensayo)
    if ! logrotate -d "$DST" >/tmp/svq-0163-lr.log 2>&1; then
        echo "  ⚠ logrotate -d avisa; se retira la config para no romper la rotación nocturna:"
        tail -5 /tmp/svq-0163-lr.log | sed 's/^/      /'
        rm -f "$DST"
    fi
    rm -f /tmp/svq-0163-lr.log
else
    echo "  ⚠ falta $SRC (¿git pull incompleto?) — se omite la rotación."
fi

PYBIN=/opt/svqpanel/venv/bin/python
if [[ -x "$PYBIN" ]]; then
    cd /opt/svqpanel
    "$PYBIN" -m api.cli fix_domain_logs_perms || \
        echo "  ⚠ fix_domain_logs_perms con incidencias (no crítico)."
fi

echo "✓ 0163: hecho"
exit 0
