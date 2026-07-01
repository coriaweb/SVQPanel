#!/bin/bash
# 0082-wp-attack-cache.sh
#
# Cache del análisis de ataques WordPress en la BD, para que la vista admin de
# Seguridad (tab WordPress) lea de BD (instantáneo) en vez de escanear los
# access.log de 40+ dominios en vivo (lento). Un cron cada 3h lo refresca
# (ventana 24h), enganchado al hilo de métricas del panel.
#
# Este update:
#   1) Crea las columnas domains.wp_xmlrpc_hits / wp_wplogin_hits /
#      wp_attack_checked_at (el ALTER de main.py también las crea al arrancar,
#      pero este update corre antes del reinicio y hace el primer refresh).
#   2) Ejecuta el primer análisis para que la tabla tenga datos ya (sin esperar
#      a que el cron corra por primera vez).
#
# Idempotente y no interactivo.

set -u

echo "→ 0082: cache de ataques WordPress en BD…"

DBQ() { sudo -u postgres psql -X -q -v ON_ERROR_STOP=1 -d panel_db -c "$1"; }

DBQ "ALTER TABLE domains ADD COLUMN IF NOT EXISTS wp_xmlrpc_hits INTEGER NOT NULL DEFAULT 0;" \
    && echo "  ✓ columna wp_xmlrpc_hits" || { echo "  ✗ wp_xmlrpc_hits"; exit 1; }
DBQ "ALTER TABLE domains ADD COLUMN IF NOT EXISTS wp_wplogin_hits INTEGER NOT NULL DEFAULT 0;" \
    && echo "  ✓ columna wp_wplogin_hits" || { echo "  ✗ wp_wplogin_hits"; exit 1; }
DBQ "ALTER TABLE domains ADD COLUMN IF NOT EXISTS wp_attack_checked_at TIMESTAMP;" \
    && echo "  ✓ columna wp_attack_checked_at" || { echo "  ✗ wp_attack_checked_at"; exit 1; }

# Primer análisis para poblar la tabla (idempotente; puede tardar unos segundos
# si hay muchos dominios con logs grandes).
PANEL=/opt/svqpanel
if [ -x "$PANEL/venv/bin/python" ]; then
    echo "  → primer análisis de ataques (ventana 24h)…"
    "$PANEL/venv/bin/python" - <<'PYEOF' && echo "  ✓ análisis inicial completado" || echo "  · análisis inicial falló (lo hará el cron cada 3h)"
import sys
sys.path.insert(0, "/opt/svqpanel")
from scripts.wp_attack_detector import refresh_all_domains
n = refresh_all_domains()
print(f"    {n} dominio(s) analizados")
PYEOF
fi

echo "✓ 0082: cache de ataques WordPress listo"
exit 0
