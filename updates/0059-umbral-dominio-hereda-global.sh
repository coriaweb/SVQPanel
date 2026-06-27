#!/bin/bash
# 0059-umbral-dominio-hereda-global.sh
#
# Arregla que el umbral antispam POR DOMINIO pisara al GLOBAL del admin aunque el
# cliente no lo hubiera personalizado (todos tenían el default 6/15 escrito con
# priority=5, que gana sobre actions.conf). Ahora: NULL = hereda el global; solo
# se escribe bloque por dominio si el cliente personaliza.
#
# La migración (poner a NULL los 6/15 por defecto) la hace api/main.py al arrancar.
# Aquí solo regeneramos settings.conf de Rspamd para que tome efecto ya.
#
# Idempotente y no interactivo.

set -u

echo "→ 0059: umbral por dominio hereda el global del admin…"

PYBIN=/opt/svqpanel/venv/bin/python
if [ ! -x "$PYBIN" ]; then
    echo "✓ 0059: sin venv del panel; nada que hacer"
    exit 0
fi
if ! command -v rspamadm >/dev/null 2>&1; then
    echo "✓ 0059: Rspamd no instalado; nada que hacer"
    exit 0
fi

cd /opt/svqpanel
"$PYBIN" - <<'PYEOF' || echo "  ⚠ no se pudo regenerar (no crítico)"
import sys
sys.path.insert(0, "/opt/svqpanel")
from api.models.database import SessionLocal, load_all_models
load_all_models()
from api.models.models_mail import MailDomain
from scripts.rspamd_manager import RspamdManager
db = SessionLocal()
RspamdManager().rebuild_from_db(db.query(MailDomain).all())
print("  ✓ settings.conf regenerado (dominios sin personalizar heredan el global)")
db.close()
PYEOF

echo "✓ 0059: hecho"
exit 0
