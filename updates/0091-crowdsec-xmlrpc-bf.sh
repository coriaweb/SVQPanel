#!/bin/bash
# 0091-crowdsec-xmlrpc-bf.sh
#
# Instala el escenario crowdsecurity/http-bf-wordpress_bf_xmlrpc en CrowdSec.
#
# Por qué: la colección crowdsecurity/wordpress (update 0090) trae la fuerza bruta
# de wp-login pero NO la de XML-RPC (es un escenario aparte, no incluido). El
# xmlrpc es un vector clásico de fuerza bruta de WordPress. Complementa el bloqueo
# de /xmlrpc.php en nginx (defensa en profundidad: nginx corta el endpoint, y si
# alguien lo reactiva o hay una ruta no cubierta, CrowdSec banea al que insiste).
#
# Nota Laravel / PHP a medida: no hay colección específica (login sin ruta fija);
# ya lo cubren los escenarios genéricos (http-generic-bf, sqli, xss, probing,
# path-traversal, backdoors, cve-probing) que trae base-http-scenarios + http-cve.
#
# Idempotente.

set -u

echo "→ 0091: escenario xmlrpc BF en CrowdSec…"

if ! command -v cscli >/dev/null 2>&1; then
    echo "  · cscli no disponible (CrowdSec no instalado); se omite"
    echo "✓ 0091: sin cambios"
    exit 0
fi

if cscli scenarios list 2>/dev/null | grep -q 'http-bf-wordpress_bf_xmlrpc'; then
    echo "  · escenario xmlrpc BF ya instalado"
else
    cscli scenarios install crowdsecurity/http-bf-wordpress_bf_xmlrpc >/dev/null 2>&1 \
        && echo "  ✓ escenario xmlrpc BF instalado" \
        || echo "  ⚠ no se pudo instalar (¿sin red / hub?); se reintenta en próximos updates"
fi

systemctl restart crowdsec >/dev/null 2>&1 \
    && echo "  ✓ crowdsec reiniciado" \
    || echo "  ⚠ no se pudo reiniciar crowdsec (revisar: journalctl -u crowdsec)"

echo "✓ 0091: fuerza bruta xmlrpc cubierta en CrowdSec"
exit 0
