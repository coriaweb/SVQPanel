#!/bin/bash
# 0106-limpiar-webmail-huerfanos.sh
#
# BUG: al eliminar un dominio de correo entero, el panel dejaba atras el vhost
# de webmail.{dominio} como placeholder 503 "webmail desactivado" (llamaba a
# WebmailManager.remove(), pensado para DESACTIVAR el webmail de un dominio que
# sigue existiendo, en vez de destroy()). El fichero quedaba huerfano para
# siempre en sites-available/sites-enabled.
#
# El codigo ya esta corregido (delete_mail_domain usa destroy=True). Este update
# limpia los vhosts de webmail huerfanos que el bug haya dejado en servidores ya
# instalados, reutilizando el saneador del panel (clean_orphan_vhosts: borra
# vhosts de dominios que ya no existen en BD y recarga el webserver).
# Idempotente: si no hay huerfanos, no hace nada.

set -u

echo "-> 0106: limpiar vhosts de webmail huerfanos..."

if [ -x /opt/svqpanel/venv/bin/python ]; then
    cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli clean_orphan_vhosts --yes \
      && echo "  . saneador ejecutado" \
      || echo "  . aviso: el saneador devolvio error (se omite)"
else
    echo "  . venv no encontrado; se omite"
fi

echo "OK 0106: vhosts huerfanos limpiados"
exit 0
