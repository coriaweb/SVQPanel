#!/bin/bash
# 0090-crowdsec-coleccion-wordpress.sh
#
# Instala la colección crowdsecurity/wordpress en CrowdSec.
#
# Por qué: la fuerza bruta DISTRIBUIDA a /wp-login.php (decenas de IPs, pocos
# intentos cada una) NO la para el rate-limit por IP (cada IP va bajo el umbral)
# ni fail2ban. CrowdSec sí, pero solo tenía http-wordpress-scan (detecta ESCANEO
# de rutas WP), no el escenario de fuerza bruta de LOGIN. Esta colección añade:
#   - http-bf-wordpress_bf      (fuerza bruta de wp-login por acumulación)
#   - http-wordpress_user-enum  (enumeración de usuarios)
#   - http-wordpress_wpconfig   (sondeo de wp-config)
#
# Requiere que CrowdSec lea los logs de los dominios (update 0089). Idempotente:
# cscli no reinstala si ya está.

set -u

echo "→ 0090: colección crowdsecurity/wordpress en CrowdSec…"

if ! command -v cscli >/dev/null 2>&1; then
    echo "  · cscli no disponible (CrowdSec no instalado); se omite"
    echo "✓ 0090: sin cambios"
    exit 0
fi

if cscli collections list 2>/dev/null | grep -q 'crowdsecurity/wordpress'; then
    echo "  · colección wordpress ya instalada"
else
    cscli collections install crowdsecurity/wordpress >/dev/null 2>&1 \
        && echo "  ✓ colección wordpress instalada" \
        || echo "  ⚠ no se pudo instalar (¿sin red / hub?); se reintenta en próximos updates"
fi

# Recargar para activar los escenarios nuevos (restart: reload no siempre carga
# escenarios recién habilitados de forma fiable).
systemctl restart crowdsec >/dev/null 2>&1 \
    && echo "  ✓ crowdsec reiniciado" \
    || echo "  ⚠ no se pudo reiniciar crowdsec (revisar: journalctl -u crowdsec)"

echo "✓ 0090: escenarios de fuerza bruta WordPress activos en CrowdSec"
exit 0
