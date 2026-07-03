#!/bin/bash
# 0105-cron-wrapper-silenciar-exito.sh
#
# El wrapper svq-cron-run reemitia SIEMPRE la salida del comando a stdout. El
# cron del sistema manda por email cualquier stdout/stderr al dueno del cron, asi
# que un job correcto que imprime algo (p.ej. wp-cli imprime "Success: Executed a
# total of N cron events." en CADA ejecucion) generaba un email por ejecucion:
# con la flota de wp-cron cada 5 min salian cientos de correos/hora del usuario a
# si mismo, frenados por el ratelimit svq_sysuser_send y apilados en la cola de
# Postfix (miles "En espera").
#
# Fix: el wrapper ya solo reemite salida cuando el comando FALLA (exit != 0). La
# salida completa (exito incluido) sigue quedando en el historial de crons del
# panel. Este update:
#   1) Reinstala el wrapper corregido (invoca el codigo del panel, no lo duplica).
#   2) Purga de la cola de Postfix los correos de cron auto-dirigidos atascados.
# Idempotente.

set -u

echo "-> 0105: silenciar salida de exito del wrapper de cron + limpiar cola..."

# 1) Reinstalar wrapper corregido (idempotente; escribe /usr/local/bin/svq-cron-run)
if [ -x /opt/svqpanel/venv/bin/python ]; then
    cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -c \
      "from scripts.cron_manager import install_cron_wrapper; install_cron_wrapper()" 2>/dev/null \
      && echo "  . wrapper svq-cron-run reinstalado" \
      || echo "  . aviso: no se pudo reinstalar el wrapper (se omite)"
else
    echo "  . venv no encontrado; no se reinstala el wrapper"
fi

# 2) Purgar de la cola los correos de cron (From: root Cron Daemon / Subject: Cron <...>).
#    Solo eliminamos los que son salida de cron auto-dirigida (Subject empieza por
#    "Cron <"), para no tocar correo legitimo de clientes que pudiera estar en cola.
if command -v postqueue >/dev/null 2>&1 && command -v postcat >/dev/null 2>&1; then
    purged=0
    for id in $(postqueue -p 2>/dev/null | grep -oE '^[0-9A-F]{9,}' ); do
        subj=$(postcat -hq "$id" 2>/dev/null | grep -m1 -i '^Subject:')
        case "$subj" in
            Subject:\ Cron\ \<*|Subject:Cron\ \<*)
                postsuper -d "$id" >/dev/null 2>&1 && purged=$((purged+1))
                ;;
        esac
    done
    echo "  . correos de cron purgados de la cola: $purged"
else
    echo "  . postqueue/postcat no disponibles; no se limpia la cola"
fi

echo "OK 0105: wrapper corregido y cola de cron limpia"
exit 0
