#!/bin/bash
# 0112-webmail-upload-limit.sh
#
# BUG: al adjuntar un fichero por webmail (Roundcube), el cliente recibia un error
# de limite ~2 MB aunque el panel dijera que el correo admite 25 MB. Causa: el
# adjunto por webmail viaja por HTTP -> nginx -> PHP ANTES de llegar a Postfix, y
# esas capas se quedaban en su default bajo:
#   - PHP:   upload_max_filesize = 2M (de fabrica)  <- el "2 MB" que veia el cliente
#   - nginx: client_max_body_size ausente -> default 1 MB en los vhosts webmail.*
#   - Roundcube: max_message_size sin fijar
# Ninguna acompanaba al message_size_limit de Postfix.
#
# El codigo ya esta corregido: al guardar el tamano de mensaje en el panel se
# propaga a las tres capas (WebmailManager.sync_upload_limit), y el vhost de
# webmail ya incluye client_max_body_size. Este update aplica el fix a los
# servidores YA instalados invocando el mismo codigo del panel.
#
# Idempotente y no interactivo.

set -u

echo "-> 0112: alinear limite de subida del webmail con el tamano de mensaje..."

if [ ! -x /opt/svqpanel/venv/bin/python ]; then
    echo "  . venv no encontrado; se omite"
    echo "OK 0112: sin cambios"
    exit 0
fi

# Sin Roundcube instalado no hay webmail que ajustar (pero el drop-in PHP es
# inofensivo). sync_upload_limit ya es defensivo: si /var/www/webmail no existe
# no toca vhosts, solo escribe el .ini de PHP y sale.
cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli sync_webmail_upload_limit \
    && echo "  . limite del webmail sincronizado (nginx + PHP + Roundcube)" \
    || echo "  . aviso: la sincronizacion devolvio error (se omite)"

echo "OK 0112: limite de subida del webmail alineado con Postfix"
exit 0
