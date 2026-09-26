#!/bin/bash
# 0154-ssl-renewal-hook.sh
#
# Instala el deploy-hook de certbot que faltaba y deja el correo sirviendo el
# certificado que hay en disco.
#
# ── EL FALLO ──────────────────────────────────────────────────────────────────
# El mapa SNI de Postfix (/etc/postfix/svqpanel_sni) se compila con
# `postmap -F`, que COPIA el contenido de key+cert dentro del .db. Certbot
# renueva por --webroot (no recarga nada) y en /etc/letsencrypt/renewal-hooks/
# no había ningún hook. Resultado: certbot renovaba bien, pero Postfix seguía
# presentando el cert viejo en 465/587 hasta que CADUCABA.
#
# Visto en sep 2026 (ticket "no podemos enviar, el certificado no es de
# confianza"): 7 dominios con el cert de SMTP ya caducado y 24 más a días, todos
# con el cert renovado en disco desde hacía un mes. El ssl-check del panel no lo
# vio porque solo miraba el disco (ahora compara también lo que se sirve).
#
# ── QUÉ HACE ──────────────────────────────────────────────────────────────────
# 1. Instala el hook vía el código del panel (install_ssl_renewal_hook).
# 2. Lo ejecuta una vez: regenera el mapa SNI y recarga Postfix/Dovecot/nginx.
# 3. Sube el TimeoutStartSec del ssl-check (ahora hace conexiones TLS locales).
#
# Idempotente y no interactivo.
set -e

echo "→ 0154: hook de renovación SSL (SNI de correo + recargas)…"

cd /opt/svqpanel
/opt/svqpanel/venv/bin/python -m api.cli install_ssl_renewal_hook

HOOK=/etc/letsencrypt/renewal-hooks/deploy/svqpanel-reload.sh
if [ -x "$HOOK" ]; then
    bash "$HOOK" || true
    echo "  · mapa SNI regenerado y servicios recargados"
fi

UNIT=/etc/systemd/system/svqpanel-ssl-check.service
if [ -f "$UNIT" ] && grep -q '^TimeoutStartSec=120$' "$UNIT"; then
    sed -i 's/^TimeoutStartSec=120$/TimeoutStartSec=600/' "$UNIT"
    systemctl daemon-reload
    echo "  · ssl-check: TimeoutStartSec 120 → 600"
fi

echo "✓ 0154: las renovaciones ya llegan a Postfix/Dovecot"
exit 0
