#!/bin/bash
# 0072-geo-bloqueo-ipv6.sh
#
# El geo-bloqueo por país solo descargaba la zona IPv4 de ipdeny.com (la ruta
# 'aggregated' es v4-only). Resultado: bloquear "China" filtraba su IPv4 pero
# dejaba pasar TODA su IPv6 — y buena parte de los bots/escáneres llegan por
# IPv6, saltándose el bloqueo.
#
# El código del fetcher ya descarga ahora también la zona IPv6 equivalente
# (api/utils/ip_list_fetcher.fetch_url + country_blocklist.country_url_v6). Pero
# el git pull solo trae el código: las listas geo_* ya existentes siguen con su
# sha cacheado y NO se redescargarían hasta el refresco diario. Este update
# fuerza un refetch inmediato (invalida sha → vuelve a bajar v4+v6) y reaplica
# nftables, para que la IPv6 quede bloqueada ya.
#
# Idempotente y no interactivo: si vuelve a correr, simplemente refresca otra
# vez (sin efectos secundarios). Si no hay listas geo, no hace nada.

set -u

echo "→ 0072: geo-bloqueo ahora también cubre IPv6 (refrescar listas de país)…"

cd /opt/svqpanel || { echo "✓ 0072: /opt/svqpanel no existe; nada que hacer"; exit 0; }
VENV_PY=/opt/svqpanel/venv/bin/python
[ -x "$VENV_PY" ] || VENV_PY=$(command -v python3)

"$VENV_PY" - <<'PY'
import sys
sys.path.insert(0, "/opt/svqpanel")
try:
    from api.models.database import SessionLocal, load_all_models
    # Cargar TODOS los modelos antes de tocar la BD: IpList tiene una FK a
    # 'users' y SQLAlchemy peta con NoReferencedTableError si User no se ha
    # importado todavía (las relationships se resuelven por nombre).
    load_all_models()
    from api.models.models_security import IpList
    from api.utils import ip_list_fetcher
    from api.utils import nftables_helper as nft
except Exception as e:
    print(f"  · no se pudo importar el panel ({e}); se aplicará en el refresco diario")
    sys.exit(0)

db = SessionLocal()
try:
    geo = db.query(IpList).filter(IpList.name.like("geo_%")).all()
    if not geo:
        print("  · no hay países bloqueados; nada que refrescar")
        sys.exit(0)

    # Invalidar sha para forzar el refetch (v4 + v6) de cada país.
    for il in geo:
        il.sha256_last = None
    db.commit()

    # Refrescar TODAS las listas habilitadas y regenerar el .nft (igual que el
    # refresh manual del panel: una sola pasada, un solo reload).
    enabled = db.query(IpList).filter(IpList.enabled.is_(True)).all()
    active = []
    for il in enabled:
        v4, v6, err = ip_list_fetcher.refresh_one(il)
        db.commit()
        if err == "unchanged":
            try:
                text, _ = ip_list_fetcher.fetch_url(il.url)
                v4, v6, _ = ip_list_fetcher.parse_list_content(text, il.max_entries)
            except Exception as e:
                print(f"  · {il.name}: refetch falló ({e}); se omite")
                continue
        elif err:
            print(f"  · {il.name}: refresh falló ({err}); se omite")
            continue
        active.append((il, v4, v6))

    content = ip_list_fetcher.regenerate_iplists_nft(active)
    ip_list_fetcher.write_iplists_nft(content)
    ok, msg = nft.reload_nftables()
    if not ok:
        print(f"  ✗ reload nftables falló: {msg}")
        sys.exit(1)

    total_v6 = sum(len(v6) for il, _v4, v6 in active if il.name.startswith("geo_"))
    print(f"  ✓ {len(geo)} país(es) refrescados; rangos IPv6 de geo aplicados: {total_v6}")
finally:
    db.close()
PY

rc=$?
echo "✓ 0072: completado"
exit $rc
