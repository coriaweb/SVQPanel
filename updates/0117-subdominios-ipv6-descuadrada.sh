#!/bin/bash
# 0117-subdominios-ipv6-descuadrada.sh
#
# BUG: los subdominios importados desde HestiaCP quedaban con el campo
# Domain.ipv6 vacio (NULL) aunque el importador SI publicaba un registro AAAA
# para ellos en la zona del dominio padre.
#
# Causa: scripts/hestia_import.py llamaba a apply_subdomain_dns(..., ipv6=server_ipv6),
# que escribe el AAAA en la zona padre, pero acto seguido solo guardaba
# is_subdomain y parent_domain en el Domain, nunca la IPv6. El alta manual de un
# subdominio desde el panel (api/routes/domains.py) no tiene el problema: pasa la
# IPv6 del propio dominio (NULL -> no crea AAAA).
#
# Sintoma: el panel muestra el subdominio "sin IPv6" pero el dominio SI responde
# por IPv6 (el AAAA esta publicado y la IP existe en el servidor). El descuadre
# no rompe nada hoy, pero si la IPv6 del padre cambia o se retira, el panel no
# actualizara ese AAAA -- creera que el subdominio no tiene IPv6 -- y el registro
# quedara apuntando a una direccion inexistente.
#
# FIX (dos partes):
#   1. Codigo (ya en el git pull): hestia_import.py guarda d.ipv6 al publicar el AAAA.
#   2. Este update: sincroniza los subdominios YA importados, copiando a Domain.ipv6
#      el valor del AAAA que ya tienen publicado en la zona padre.
#
# Solo toca filas donde el AAAA ya existe y Domain.ipv6 es NULL: no inventa
# registros DNS, no toca BIND ni nginx, no cambia lo que ya se sirve.
#
# Idempotente y no interactivo.

set -u

echo "-> 0117: sincronizar Domain.ipv6 de subdominios importados de Hestia..."

PANEL_DIR="/opt/svqpanel"
PY="${PANEL_DIR}/venv/bin/python"

if [ ! -x "$PY" ]; then
    echo "  ! No existe $PY -- panel no instalado aqui, nada que hacer."
    exit 0
fi

cd "$PANEL_DIR" || { echo "  ! No puedo entrar en $PANEL_DIR"; exit 1; }

"$PY" - <<'PYEOF'
import sys

try:
    from api.models.database import SessionLocal, load_all_models
    load_all_models()  # fuente unica de imports (evita InvalidRequestError por relationships)
    from api.models.models_domain import Domain
    from api.models.models_dns import DnsZone, DnsRecord
except Exception as e:
    print(f"  ! No se pudieron cargar los modelos: {e}")
    sys.exit(0)  # no romper la cadena de updates

db = SessionLocal()
fixed = 0
skipped = 0
try:
    subs = db.query(Domain).filter(
        Domain.is_subdomain.is_(True),
        Domain.ipv6.is_(None),
        Domain.parent_domain.isnot(None),
    ).all()

    for d in subs:
        zone = db.query(DnsZone).filter(
            DnsZone.domain_name == d.parent_domain).first()
        if not zone:
            continue

        # etiqueta del subdominio dentro de la zona padre: "zonaprivada" en
        # zonaprivada.corosantamaria.org
        suffix = "." + d.parent_domain
        if not d.domain_name.endswith(suffix):
            continue
        label = d.domain_name[: -len(suffix)]

        rec = db.query(DnsRecord).filter(
            DnsRecord.zone_id == zone.id,
            DnsRecord.record_type == "AAAA",
            DnsRecord.name == label,
        ).first()

        if not rec or not rec.content:
            skipped += 1
            continue

        d.ipv6 = rec.content
        fixed += 1
        print(f"  . {d.domain_name} -> ipv6={rec.content}")

    if fixed:
        db.commit()
    print(f"  = subdominios sincronizados: {fixed} (sin AAAA publicado: {skipped})")
except Exception as e:
    db.rollback()
    print(f"  ! Error sincronizando: {e}")
finally:
    db.close()
PYEOF

echo "-> 0117: OK"
exit 0
