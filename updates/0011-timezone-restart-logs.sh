#!/bin/bash
# 0011-timezone-restart-logs.sh
#
# Al cambiar la zona horaria del panel, los servicios que ya estaban corriendo
# (rsyslog, nginx, postfix, dovecot) seguían escribiendo sus logs en la zona
# ANTERIOR (normalmente UTC) porque cachean la zona al arrancar. Resultado: los
# logs salían con el desfase horario aunque el sistema ya estuviera en la zona
# correcta.
#
# El fix (en api/routes/settings.py) reinicia esos servicios al cambiar la zona.
# Este update los reinicia una vez ahora para que adopten la zona actual del
# sistema. Idempotente.

set -euo pipefail

echo "→ 0011: Aplicar la zona horaria del sistema a los servicios de logs..."

for svc in rsyslog nginx postfix dovecot cron; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        systemctl try-restart "$svc" 2>/dev/null && echo "  ✓ $svc reiniciado" || true
    fi
done

echo "✓ 0011: Servicios de logs reiniciados (timestamps en hora local)"
exit 0
