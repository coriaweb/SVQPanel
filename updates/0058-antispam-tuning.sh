#!/bin/bash
# 0058-antispam-tuning.sh
#
# Ajuste fino del antispam (Rspamd) por el admin + Bayes que se autoequilibra:
#
#   1) Reconfigura el autolearn del Bayes (setup_spam_learning): el umbral de ham
#      pasa de -2 a 0.5 para que el filtro aprenda ham solo conforme entra correo
#      legítimo (antes quedaba ciego: mucho spam, ~0 ham). min_learns 30→20.
#   2) Regenera los drop-ins de pesos/umbrales/reglas desde Settings.rspamd_overrides
#      (si el admin ya guardó ajustes en el panel). Idempotente.
#
# No interactivo. Seguro de re-ejecutar.

set -u

echo "→ 0058: ajuste del antispam (Bayes autoequilibrado + overrides admin)…"

PYBIN=/opt/svqpanel/venv/bin/python
if [ ! -x "$PYBIN" ]; then
    echo "✓ 0058: sin venv del panel; nada que hacer"
    exit 0
fi

if ! command -v rspamadm >/dev/null 2>&1; then
    echo "✓ 0058: Rspamd no instalado (¿servidor sin correo?); nada que hacer"
    exit 0
fi

cd /opt/svqpanel

# 1) Reconfigurar Bayes (nuevo autolearn/min_learns).
"$PYBIN" -m api.cli setup_spam_learning || echo "  ⚠ setup_spam_learning con incidencias"

# 2) Aplicar overrides del admin guardados en BD (si los hay).
"$PYBIN" - <<'PYEOF' || echo "  ⚠ no se pudieron aplicar overrides (no crítico)"
import sys
sys.path.insert(0, "/opt/svqpanel")
from api.models.database import SessionLocal, load_all_models
load_all_models()
from api.models.models_settings import Settings
from scripts import rspamd_tuning
db = SessionLocal()
s = db.query(Settings).filter(Settings.id == 1).first()
raw = getattr(s, "rspamd_overrides", None) if s else None
res = rspamd_tuning.apply_from_db_json(raw)
print(f"  ✓ overrides antispam aplicados: {res.get('success', res)}")
db.close()
PYEOF

echo "✓ 0058: antispam ajustado"
exit 0
