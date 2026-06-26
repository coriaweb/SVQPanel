#!/bin/bash
# 0049-cluster-slave-resync.sh
#
# Fix de cluster DNS: push_zone solo declaraba las zonas NUEVAS en el MASTER, no
# en el SLAVE. Resultado: todo dominio creado/migrado tras montar el cluster
# llegaba al master pero el slave nunca lo replicaba (el slave no conocía la
# zona). El código ya está corregido; este update RE-SINCRONIZA todas las zonas
# para que el slave adopte las que le faltaban. Idempotente y no interactivo.

set -euo pipefail

echo "→ 0049: re-sincronizar zonas del cluster DNS al slave…"

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }

cd /opt/svqpanel
"$PYBIN" - <<'PYEOF' || echo "  ⚠ resync con incidencias (no crítico; el health periódico reintentará)."
import sys
sys.path.insert(0, "/opt/svqpanel")
from api.models.database import SessionLocal, load_all_models
load_all_models()
from scripts.dns_cluster import load_cluster, resync_zone
from api.models.models_dns import DnsZone

db = SessionLocal()
if not load_cluster(db):
    print("  No hay cluster DNS configurado — nada que re-sincronizar.")
    sys.exit(0)

zones = [z.domain_name for z in db.query(DnsZone).filter(DnsZone.is_active == True).all()]
ok = 0
for d in zones:
    try:
        if resync_zone(db, d):
            ok += 1
    except Exception as e:
        print(f"    {d}: error {str(e)[:80]}")
print(f"  ✓ {ok}/{len(zones)} zonas re-empujadas (master + slave)")
db.close()
PYEOF

echo "✓ 0049: cluster re-sincronizado"
exit 0
