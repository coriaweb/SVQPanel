#!/bin/bash
# 0070-nginx-quic-sin-reuseport.sh
#
# BUG: los vhosts con HTTP/3 (QUIC) generaban `listen 443 quic reuseport;`. El
# `reuseport` solo puede aparecer UNA vez por puerto en TODA la config de nginx;
# al haber DOS o más dominios con HTTP/3, el segundo reventaba nginx con
#   nginx: [emerg] duplicate listen options for 0.0.0.0:443
# y eso bloqueaba CUALQUIER reload → fallaban migraciones y cambios de vhost.
#
# El código ya genera `listen 443 quic;` sin reuseport (no es necesario: solo
# balancea conexiones UDP entre workers). Este update REGENERA todos los vhosts
# existentes desde la BD para quitar el reuseport de los que ya lo tenían.
#
# Idempotente y no interactivo.

set -u

echo "→ 0070: regenerar vhosts nginx (quitar reuseport de HTTP/3)…"

cd /opt/svqpanel || { echo "✓ 0070: /opt/svqpanel no existe; nada que hacer"; exit 0; }

VENV_PY=/opt/svqpanel/venv/bin/python
[ -x "$VENV_PY" ] || VENV_PY=$(command -v python3)

# Regenera el vhost de todos los dominios desde la BD con el código actual.
"$VENV_PY" -m api.cli regenerate_all_vhosts 2>&1 | tail -5 || \
    echo "  ⚠ regenerate_all_vhosts devolvió error (revisa el log), continúo"

# Validar y recargar nginx. Si tras regenerar aún falla, avisar (pero el código
# de salida 0 no debe romper la cadena: el resto del sistema sigue bien).
if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx
    echo "  ✓ nginx -t OK; recargado"
else
    echo "  ✗ nginx -t SIGUE fallando tras regenerar. Revisa manualmente: nginx -t"
    nginx -t 2>&1 | tail -3
fi

echo "✓ 0070: completado"
exit 0
