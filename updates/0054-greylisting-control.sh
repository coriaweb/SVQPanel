#!/bin/bash
# 0054-greylisting-control.sh
#
# Control del greylisting (global + por dominio). El módulo de Rspamd se llama
# 'greylist' → el fichero debe ser greylist.conf (greylisting.conf NO lo lee).
# Crea greylist.conf con el estado guardado en el panel y regenera settings.conf
# (por si algún dominio tiene greylist desactivado). Idempotente.

set -u

echo "→ 0054: control de greylisting (global + por dominio)…"

# Quitar el nombre antiguo erróneo (no hacía nada).
rm -f /etc/rspamd/local.d/greylisting.conf 2>/dev/null || true

PYBIN=/opt/svqpanel/venv/bin/python
if [ ! -x "$PYBIN" ]; then
    # Sin panel: dejar greylist.conf activo por defecto.
    [ -f /etc/rspamd/local.d/greylist.conf ] || \
        printf 'enabled = true;\n' > /etc/rspamd/local.d/greylist.conf
    systemctl reload rspamd 2>/dev/null || true
    echo "✓ 0054: greylist.conf por defecto"
    exit 0
fi

cd /opt/svqpanel
"$PYBIN" - <<'PYEOF' || echo "  ⚠ con incidencias (no crítico)."
import sys
sys.path.insert(0, "/opt/svqpanel")
from api.models.database import SessionLocal, load_all_models
load_all_models()
from api.models.models_settings import Settings
from api.models.models_mail import MailDomain
from scripts.rspamd_manager import RspamdManager
db = SessionLocal()
s = db.query(Settings).filter(Settings.id == 1).first()
enabled = bool(getattr(s, "greylisting_enabled", True)) if s else True
mgr = RspamdManager()
mgr.set_global_greylisting(enabled)        # crea greylist.conf correcto
mgr.rebuild_from_db(db.query(MailDomain).all())  # aplica greylist por dominio
print(f"  ✓ greylisting global = {enabled}; settings por dominio regenerados")
db.close()
PYEOF

echo "✓ 0054: greylisting configurado"
exit 0
