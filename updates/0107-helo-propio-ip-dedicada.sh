#!/bin/bash
# 0107-helo-propio-ip-dedicada.sh
#
# Los transportes de salida por dominio (svqout_*) con IP DEDICADA saludaban
# con el hostname del servidor: el receptor veia SPF_HELO_SOFTFAIL y el par
# PTR<->HELO roto (el PTR de una IP dedicada apunta a mail.{dominio}). El
# codigo ya genera "-o smtp_helo_name=mail.{dominio}" cuando el bind difiere
# de la IP global del servidor; este update regenera la seccion
# SVQPANEL_SMTP_BIND de master.cf para que los dominios existentes lo ganen.
# Idempotente: si no hay dominios con IP propia, no toca nada.

set -u

echo "-> 0107: HELO propio en transportes con IP dedicada..."

if [ -x /opt/svqpanel/venv/bin/python ]; then
    cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -c "
from scripts.mail_manager import MailManager
mm = MailManager()
if mm.mail_available():
    mm._rebuild_master_cf_smtp_binds()
    mm._reload_postfix()
    print('  . seccion SVQPANEL_SMTP_BIND regenerada')
else:
    print('  . correo no instalado; nada que hacer')
" || echo "  . aviso: no se pudo regenerar (se omite)"
else
    echo "  . venv no encontrado; se omite"
fi

echo "OK 0107: transportes regenerados"
exit 0
