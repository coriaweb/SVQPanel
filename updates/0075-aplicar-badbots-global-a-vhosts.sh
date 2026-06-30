#!/bin/bash
# 0075-aplicar-badbots-global-a-vhosts.sh
#
# El catálogo global "Bloqueo de bots" (Seguridad) escribe un map $bad_bot en
# /etc/nginx/conf.d/bad-bots.conf, pero NINGÚN vhost nginx lo consultaba: el map
# definía una variable que nadie leía, así que activar bots ahí no bloqueaba
# nada (en nginx puro). Solo Apache lo aplicaba.
#
# El código ya añade `if ($bad_bot) { return 444; }` a cada server block. Este
# update:
#   1) Garantiza que bad-bots.conf exista (si no, los vhosts con $bad_bot no
#      validarían → nginx no arrancaría).
#   2) Regenera TODOS los vhosts desde la BD para que incluyan el chequeo global.
#   3) Valida y recarga nginx.
#
# Idempotente y no interactivo.

set -u

echo "→ 0075: aplicar el bloqueo global de bots a todos los vhosts nginx…"

cd /opt/svqpanel || { echo "✓ 0075: /opt/svqpanel no existe; nada que hacer"; exit 0; }
VENV_PY=/opt/svqpanel/venv/bin/python
[ -x "$VENV_PY" ] || VENV_PY=$(command -v python3)

# 1) Asegurar el map base (no rompe lo que ya hubiera). Imprescindible ANTES de
#    regenerar vhosts que referencian $bad_bot.
"$VENV_PY" - <<'PY'
import sys
sys.path.insert(0, "/opt/svqpanel")
try:
    from scripts.bad_bots_manager import ensure_nginx_conf_exists
    created = ensure_nginx_conf_exists()
    print("  · bad-bots.conf creado (map base)" if created else "  · bad-bots.conf ya existía")
except Exception as e:
    print(f"  ⚠ no se pudo asegurar bad-bots.conf ({e}); continúo")
PY

# 2) Regenerar todos los vhosts desde la BD con el código actual.
"$VENV_PY" -m api.cli regenerate_all_vhosts 2>&1 | tail -5 || \
    echo "  ⚠ regenerate_all_vhosts devolvió error (revisa el log), continúo"

# 3) Validar y recargar nginx.
if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx
    echo "  ✓ nginx -t OK; recargado"
else
    echo "  ✗ nginx -t SIGUE fallando tras regenerar. Revisa: nginx -t"
    nginx -t 2>&1 | tail -3
fi

echo "✓ 0075: completado"
exit 0
