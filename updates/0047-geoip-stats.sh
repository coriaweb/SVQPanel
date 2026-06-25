#!/bin/bash
# 0047-geoip-stats.sh
#
# Activa la geolocalización por país en las estadísticas de dominio (GoAccess):
#   - descarga la base GeoIP gratuita de DB-IP (sin registro),
#   - instala un cron MENSUAL para mantenerla al día (DB-IP la renueva cada mes).
# Idempotente.

set -euo pipefail

echo "→ 0047: GeoIP (países) + informe en español en las estadísticas…"

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }

# Locale español para que los informes de GoAccess salgan traducidos.
if ! locale -a 2>/dev/null | grep -qiE "^es_ES\.(utf8|UTF-8)$"; then
    grep -q "^es_ES.UTF-8" /etc/locale.gen 2>/dev/null || echo "es_ES.UTF-8 UTF-8" >> /etc/locale.gen
    locale-gen es_ES.UTF-8 >/dev/null 2>&1 && echo "  ✓ locale es_ES.UTF-8 generado" \
        || echo "  ⚠ no se pudo generar el locale es_ES (informe quedará en inglés)."
else
    echo "  locale es_ES.UTF-8 ya disponible."
fi

mkdir -p /var/lib/svqpanel/geoip

cd /opt/svqpanel
"$PYBIN" -m api.cli update_geoip \
    && echo "  ✓ base GeoIP descargada/actualizada" \
    || echo "  ⚠ no se pudo descargar la base GeoIP (¿sin red?); se reintentará por cron."

# Cron mensual: día 5 a las 4:15 (DB-IP publica la nueva a principios de mes).
CRON=/etc/cron.d/svqpanel-geoip
if [ ! -f "$CRON" ]; then
    cat > "$CRON" <<'CRONEOF'
# SVQPanel — actualización mensual de la base GeoIP (países en estadísticas)
15 4 5 * * root cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli update_geoip >> /var/log/svqpanel-update.log 2>&1
CRONEOF
    chmod 644 "$CRON"
    echo "  ✓ cron mensual de GeoIP instalado"
else
    echo "  cron de GeoIP ya existía."
fi

echo "✓ 0047: GeoIP activada"
exit 0
