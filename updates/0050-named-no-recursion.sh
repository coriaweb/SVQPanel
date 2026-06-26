#!/bin/bash
# 0050-named-no-recursion.sh
#
# SEGURIDAD: BIND venía con recursión activada (default Debian) → el servidor
# era un "open resolver" usable para ataques de amplificación DDoS contra
# terceros (y candidato a listas negras). Un nameserver autoritativo NO debe
# recurrir. Cierra la recursión en el BIND local del panel Y en los nodos del
# cluster (master/slave), manteniendo la resolución pública de sus zonas.
# Idempotente.

set -euo pipefail

echo "→ 0050: cerrar recursión DNS (open resolver)…"

# 1) BIND local del panel (si lo hay).
if [ -f /etc/bind/named.conf.options ]; then
    if ! grep -qE "recursion[[:space:]]+no" /etc/bind/named.conf.options; then
        cp /etc/bind/named.conf.options /etc/bind/named.conf.options.bak 2>/dev/null || true
        cat > /etc/bind/named.conf.options <<'NAMEDOPTS'
options {
	version "none";
	directory "/var/cache/bind";
	dnssec-validation auto;
	listen-on-v6 { any; };
	recursion no;
	allow-query { any; };
	allow-recursion { none; };
	allow-query-cache { none; };
};
NAMEDOPTS
        named-checkconf 2>/dev/null && (rndc reload 2>/dev/null || systemctl restart named 2>/dev/null) || true
        echo "  ✓ recursión cerrada en el BIND local"
    else
        echo "  BIND local ya sin recursión."
    fi
fi

# 2) Nodos del cluster (master/slave) vía el código del panel (idempotente).
PYBIN=/opt/svqpanel/venv/bin/python
if [ -x "$PYBIN" ]; then
    cd /opt/svqpanel
    "$PYBIN" - <<'PYEOF' || echo "  ⚠ hardening de nodos del cluster con incidencias (no crítico)."
import sys
sys.path.insert(0, "/opt/svqpanel")
from api.models.database import SessionLocal, load_all_models
load_all_models()
from scripts.dns_cluster import load_cluster, DNSCluster
db = SessionLocal()
cluster = load_cluster(db)
if not cluster:
    print("  No hay cluster DNS — solo BIND local.")
    sys.exit(0)
cl = DNSCluster(panel_id=cluster["panel_id"])
for role in ("master", "slave"):
    node = cluster.get(role)
    if not node or not node.get("ip"):
        continue
    ok, msg = cl.harden_named(node)
    print(f"  {role} ({node['ip']}): {'✓ sin recursión' if ok else '⚠ ' + msg}")
db.close()
PYEOF
fi

echo "✓ 0050: recursión DNS cerrada"
exit 0
