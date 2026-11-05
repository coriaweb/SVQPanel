#!/bin/bash
# 0175-cloudflare-rangos-diario.sh
#
# Nueva opción por dominio «Solo tráfico desde Cloudflare» (Protección → Acceso
# por país e IP): 403 a quien conecte directo a la IP del servidor saltándose el
# WAF/anti-DDoS de Cloudflare. Necesita el geo global $svq_from_cf
# (/etc/nginx/conf.d/svqpanel-cloudflare-geo.conf), que escribe
# refresh_cloudflare_ips junto al real_ip.
#
# El cron pasa de mensual a DIARIO: con la opción activa, un rango nuevo de
# Cloudflare sin añadir dejaría esas webs sin responder desde él. Si la descarga
# falla o viene corta se mantienen los rangos que ya había. Reflejado en
# install.sh. Idempotente.

set -u

CRON=/etc/cron.d/svqpanel-cloudflare
cat > "$CRON" <<'CRONEOF'
# SVQPanel — actualización diaria de los rangos de Cloudflare (real_ip + $svq_from_cf)
20 4 * * * root cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli refresh_cloudflare_ips >> /var/log/svqpanel-update.log 2>&1
CRONEOF
chmod 644 "$CRON"

if [ -x /opt/svqpanel/venv/bin/python ] && command -v nginx >/dev/null 2>&1; then
    (cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli refresh_cloudflare_ips) \
      && echo "✓ 0175: rangos de Cloudflare diarios y \$svq_from_cf listo" \
      || echo "⚠ 0175: no se pudieron refrescar los rangos (lo reintentará el cron)"
fi
exit 0
