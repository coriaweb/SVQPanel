#!/bin/bash
# 0092-crowdsec-error-logs-dominios.sh
#
# Amplía la acquisition de CrowdSec para los dominios: además de los access.log
# (update 0089), ahora lee también los ERROR.log de nginx y apache.
#
# Por qué: los 429 del rate-limit (p.ej. la protección de fuerza bruta de
# wp-login) quedan registrados en el nginx.error.log ("limiting requests by
# zone …"), NO en el access.log. El escenario crowdsecurity/nginx-req-limit-exceeded
# está activo pero se quedaba CIEGO: sin el error.log no ve esos 429, así que
# CrowdSec no baneaba al que dispara el rate-limit una y otra vez (visto: >1000
# hits de una misma IP a wp-login, frenados por el 429 pero sin ban). Con el
# error.log, el limit_req frena y CrowdSec banea al insistente.
#
# CrowdSec corre como root → puede leer los error.log aunque sean 0640 www-data.
# Idempotente y no interactivo.

set -u

echo "→ 0092: CrowdSec lee los error.log de los dominios…"

if [ ! -d /etc/crowdsec ]; then
    echo "  · /etc/crowdsec no existe (CrowdSec no instalado); se omite"
    echo "✓ 0092: sin cambios"
    exit 0
fi

ACQ=/etc/crowdsec/acquis.d/svqpanel-domains.yaml
mkdir -p /etc/crowdsec/acquis.d
cat > "$ACQ" <<'CSDOMEOF'
# SVQPanel — logs de acceso Y error de los dominios de clientes.
# access.log → escenarios http-* (fuerza bruta wp-login, scans, probing…).
# error.log  → nginx-req-limit-exceeded: los 429 del rate-limit (p.ej. wp-login)
#              quedan en el error.log, NO en el access → sin él CrowdSec no banea
#              al que dispara el límite repetidamente.
filenames:
  - /home/*/web/*/logs/nginx.access.log
labels:
  type: nginx
---
filenames:
  - /home/*/web/*/logs/nginx.error.log
labels:
  type: nginx
---
filenames:
  - /home/*/web/*/logs/apache.access.log
labels:
  type: apache2
---
filenames:
  - /home/*/web/*/logs/apache.error.log
labels:
  type: apache2
CSDOMEOF
echo "  ✓ acquisition actualizada (access + error, nginx + apache)"

if command -v systemctl >/dev/null 2>&1; then
    systemctl restart crowdsec >/dev/null 2>&1 \
        && echo "  ✓ crowdsec reiniciado (ahora ve los error.log)" \
        || echo "  ⚠ no se pudo reiniciar crowdsec (revisar: journalctl -u crowdsec)"
fi

echo "✓ 0092: error.log de dominios cubierto (rate-limit → ban)"
exit 0
