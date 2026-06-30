#!/bin/bash
# 0077-cachear-peso-disco-dominios.sh
#
# La lista de dominios hacía `du` EN VIVO por cada dominio al cargar (3 du por
# dominio: public_html, total, logs). Con decenas de dominios → muy lento y
# disco machacado en cada visita.
#
# Ahora el peso se CACHEA en BD (columnas disk_*_bytes + disk_calculated_at, las
# crea main.py al arrancar) y se refresca en background 2 veces al día (hilo del
# metrics-scheduler) o bajo demanda con el botón "refrescar" de cada dominio.
#
# Este update hace el PRIMER cálculo para que la lista no salga vacía hasta el
# primer tick del cron. Idempotente (recalcula, sin efectos secundarios) y no
# interactivo. El du puede tardar con muchos sitios grandes: corre en segundo
# plano del propio update (no bloquea el resto de la cadena más de lo necesario).

set -u

echo "→ 0077: primer cálculo del peso en disco de los dominios (cachear)…"

cd /opt/svqpanel || { echo "✓ 0077: /opt/svqpanel no existe; nada que hacer"; exit 0; }
VENV_PY=/opt/svqpanel/venv/bin/python
[ -x "$VENV_PY" ] || VENV_PY=$(command -v python3)

"$VENV_PY" - <<'PY'
import sys
sys.path.insert(0, "/opt/svqpanel")
try:
    from api.models.database import SessionLocal, load_all_models
    load_all_models()
    from api.models.models_domain import Domain
    from api.routes.domains import compute_domain_disk
except Exception as e:
    print(f"  · no se pudo importar el panel ({e}); lo calculará el cron 2/día")
    sys.exit(0)

db = SessionLocal()
try:
    n = 0
    for d in db.query(Domain).all():
        if getattr(d, "mail_dns_only", False):
            continue
        try:
            compute_domain_disk(d, db)
            n += 1
        except Exception as e:
            print(f"  · {d.domain_name}: fallo al calcular ({e})")
    print(f"  ✓ peso calculado y cacheado para {n} dominio(s)")
finally:
    db.close()
PY

echo "✓ 0077: completado"
exit 0
