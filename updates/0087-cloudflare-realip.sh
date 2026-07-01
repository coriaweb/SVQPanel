#!/bin/bash
# 0087-cloudflare-realip.sh
#
# Configura real_ip de Cloudflare en nginx e instala el cron mensual que mantiene
# los rangos al día.
#
# Problema que arregla: cuando un dominio está tras Cloudflare, nginx ve la IP de
# Cloudflare (172.x, 104.2x…) en vez de la del visitante real. Eso deja ciegos:
#   - los rate-limit por IP (p.ej. la protección de fuerza bruta de wp-login):
#     limitan "por IP de Cloudflare", que multiplexa miles de clientes → el
#     atacante los esquiva y encima castiga a usuarios legítimos que comparten
#     IP de CF con el bot (falsos positivos 429).
#   - fail2ban / CrowdSec: banearían a Cloudflare (inútil o contraproducente).
#   - los logs: registran la IP de CF, no la real.
#
# Solución: declarar los rangos de Cloudflare como proxies de confianza
# (set_real_ip_from) y tomar la IP real de CF-Connecting-IP. A partir de ahí
# $remote_addr/$binary_remote_addr son la IP real del visitante.
#
# Delega en el código del panel (refresh_cloudflare_ips), que descarga los rangos
# oficiales, escribe /etc/nginx/conf.d/svqpanel-cloudflare-realip.conf y recarga
# nginx. Idempotente y no interactivo.

set -u

echo "→ 0087: real_ip de Cloudflare para nginx…"

# 1) Escribir el conf.d de real_ip (delega en el código del panel; idempotente,
#    valida y recarga nginx solo si el test pasa).
if [ -x /opt/svqpanel/venv/bin/python ]; then
    (cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli refresh_cloudflare_ips) \
        && echo "  ✓ conf.d de Cloudflare escrito y nginx recargado" \
        || echo "  ⚠ no se pudo escribir el conf.d (se reintentará por cron)"
else
    echo "  · venv no encontrado; se omite (el cron lo hará cuando esté)"
fi

# 2) Cron mensual para mantener los rangos de Cloudflare al día.
CRON=/etc/cron.d/svqpanel-cloudflare
if [ ! -f "$CRON" ]; then
    cat > "$CRON" <<'CRONEOF'
# SVQPanel — actualización mensual de los rangos de Cloudflare (real_ip nginx)
20 4 5 * * root cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli refresh_cloudflare_ips >> /var/log/svqpanel-update.log 2>&1
CRONEOF
    chmod 644 "$CRON"
    echo "  ✓ cron mensual instalado ($CRON)"
else
    echo "  · cron ya existente ($CRON)"
fi

echo "✓ 0087: real_ip de Cloudflare configurado"
exit 0
