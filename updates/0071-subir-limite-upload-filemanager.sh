#!/bin/bash
# 0071-subir-limite-upload-filemanager.sh
#
# El límite de subida del gestor de archivos era 100 MB (y 500 MB para extraer),
# demasiado bajo para un WordPress (un .tar.gz/.zip del sitio suele pasar de
# 100 MB). Se suben los defaults a 2048 MB (subida) y 5120 MB (extracción).
# nginx del panel ya permite client_max_body_size 6g, así que no hay otro tope.
#
# Solo actualiza las filas que SIGUEN en el default viejo (100/500), para no
# pisar un valor que el admin haya personalizado a propósito. Idempotente.
#
# Usa el código del panel (SQLAlchemy) para conectar, igual que el resto de
# updates: no hardcodea credenciales de la BD.

set -u

echo "→ 0071: subir límite de subida del gestor de archivos (100→2048 MB)…"

cd /opt/svqpanel || { echo "✓ 0071: /opt/svqpanel no existe; nada que hacer"; exit 0; }
VENV_PY=/opt/svqpanel/venv/bin/python
[ -x "$VENV_PY" ] || VENV_PY=$(command -v python3)

"$VENV_PY" - <<'PY'
import sys
sys.path.insert(0, "/opt/svqpanel")
try:
    from api.models.database import SessionLocal
    from api.models.models_settings import Settings
except Exception as e:
    print(f"  · no se pudo importar el panel ({e}); lo aplicará el default al crear settings")
    sys.exit(0)

db = SessionLocal()
try:
    s = db.query(Settings).filter(Settings.id == 1).first()
    if not s:
        print("  · no hay fila Settings todavía; el default nuevo (2048/5120) ya aplica")
        sys.exit(0)
    changed = []
    if s.max_upload_mb == 100:
        s.max_upload_mb = 2048; changed.append("max_upload_mb 100→2048")
    if s.max_extract_mb == 500:
        s.max_extract_mb = 5120; changed.append("max_extract_mb 500→5120")
    if changed:
        db.commit()
        print("  ✓ " + "; ".join(changed))
    else:
        print(f"  · sin cambios (subida={s.max_upload_mb} MB, extracción={s.max_extract_mb} MB; personalizado o ya aplicado)")
finally:
    db.close()
PY

echo "✓ 0071: completado"
exit 0
