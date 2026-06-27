#!/bin/bash
# 0060-reglas-admin-en-multimap.sh
#
# Las reglas de contenido del admin (antispam) deben vivir DENTRO de
# multimap.conf: Rspamd solo lee reglas de multimap desde ahí, un .conf aparte se
# ignoraba (la regla no disparaba). Ahora rspamd_tuning genera los bloques y
# RspamdManager los inyecta en multimap.conf al regenerar.
#
# Este update: borra el fichero antiguo ignorado (si existe) y regenera la config
# de Rspamd para que las reglas guardadas (JSON + BD) pasen a multimap.conf.
#
# Idempotente y no interactivo.

set -u

echo "→ 0060: reglas antispam del admin a multimap.conf…"

PYBIN=/opt/svqpanel/venv/bin/python
if [ ! -x "$PYBIN" ]; then
    echo "✓ 0060: sin venv del panel; nada que hacer"
    exit 0
fi
if ! command -v rspamadm >/dev/null 2>&1; then
    echo "✓ 0060: Rspamd no instalado; nada que hacer"
    exit 0
fi

# Quitar el fichero antiguo que Rspamd ignoraba (de la primera versión).
find /etc/rspamd/local.d/svqpanel_admin_rules.conf -delete 2>/dev/null || true

cd /opt/svqpanel

# Si hay overrides guardados en BD, reaplicarlos (incluye reglas en JSON propio).
"$PYBIN" - <<'PYEOF' || echo "  ⚠ no se pudo regenerar (no crítico)"
import sys
sys.path.insert(0, "/opt/svqpanel")
from api.models.database import SessionLocal, load_all_models
load_all_models()
from api.models.models_mail import MailDomain
from api.models.models_settings import Settings
from scripts.rspamd_manager import RspamdManager
from scripts import rspamd_tuning

db = SessionLocal()
# Reaplicar pesos/umbrales desde BD (por si acaso).
s = db.query(Settings).filter(Settings.id == 1).first()
raw = getattr(s, "rspamd_overrides", None) if s else None
if raw:
    import json
    try:
        data = json.loads(raw)
        # Sembrar el JSON de reglas que lee build_admin_rules_blocks().
        if data.get("rules") is not None:
            rspamd_tuning._write_atomic(rspamd_tuning.RULES_JSON, json.dumps(data["rules"]))
    except Exception as e:
        print("  ⚠ overrides:", e)
# Regenerar multimap.conf (inyecta las reglas del admin) + settings.
RspamdManager().rebuild_from_db(db.query(MailDomain).all())
print("  ✓ multimap.conf regenerado con las reglas del admin")
db.close()
PYEOF

echo "✓ 0060: hecho"
exit 0
