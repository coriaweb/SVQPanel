#!/bin/bash
# 0093-memory-limit-256-global-128-dominio.sh
#
# memory_limit: el php.ini GLOBAL sube a 256M (techo máximo que el panel permite
# via override por dominio). Cada pool dedicado nace con 128M explícito
# (DOMAIN_DEFAULT_OVERRIDES en el código): consumo contenido por defecto, y solo
# lo sube quien lo necesite (p.ej. WooCommerce, que agotaba los 128M → 500).
#
# Este update:
#  1) Sube memory_limit a 256M en el php.ini global de FPM de cada versión PHP.
#  2) Regenera todos los pools de dominio para que lleven el 128M explícito
#     (via regenerate_all_vhosts, que reescribe pools+vhosts desde la BD).
#
# Idempotente y no interactivo.

set -u

echo "→ 0093: memory_limit global 256M + pools por dominio 128M…"

# 1) Global 256M en cada php.ini de FPM instalado.
changed=0
for INI in /etc/php/*/fpm/php.ini; do
    [ -f "$INI" ] || continue
    if grep -q "^\s*memory_limit\s*=" "$INI"; then
        sed -i "s|^\s*memory_limit\s*=.*|memory_limit = 256M|" "$INI"
    else
        echo "memory_limit = 256M" >> "$INI"
    fi
    changed=1
    echo "  ✓ $INI → memory_limit = 256M"
done

# 2) Regenerar pools (nacen con el 128M por dominio) + recargar FPM.
cd /opt/svqpanel 2>/dev/null && {
    VENV_PY=/opt/svqpanel/venv/bin/python
    [ -x "$VENV_PY" ] || VENV_PY=$(command -v python3)
    echo "→ 0093: regenerando pools de dominio (128M explícito)…"
    "$VENV_PY" -m api.cli migrate_php_pools --force 2>&1 | tail -3 || \
        echo "  ⚠ migrate_php_pools devolvió error (revisa el log), continúo"
}

# 3) Recargar los FPM para que tomen el nuevo global.
for SVC in $(systemctl list-units --type=service --no-legend 'php*-fpm.service' 2>/dev/null | awk '{print $1}'); do
    systemctl reload "$SVC" 2>/dev/null && echo "  ✓ recargado $SVC" || \
        systemctl restart "$SVC" 2>/dev/null || true
done

echo "✓ 0093: completado"
exit 0
