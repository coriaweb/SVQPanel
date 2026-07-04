#!/bin/bash
# 0108-normalizar-txt-importados.sh
#
# Los TXT importados de backups (Hestia/cPanel) se guardaban en BD tal cual
# venian en el fichero de zona: con comillas dentro del contenido ("v=spf1..."),
# en trozos ("a" "b") y con \; escapados. Eso rompia TODOS los buscadores del
# panel sobre TXT (anadir ip6 al SPF al cambiar la preferencia de salida,
# detector de SPF duplicado, etc.) de forma silenciosa.
#
# El importador ya normaliza al importar; este update sanea los TXT ya
# existentes en BD y resincroniza las zonas afectadas (serial + cluster/BIND).
# Idempotente: si no hay TXT con formato de zona, no toca nada.

set -u

echo "-> 0108: normalizar TXT importados en BD..."

if [ -x /opt/svqpanel/venv/bin/python ]; then
    cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -c "
from api.models.database import SessionLocal, load_all_models
load_all_models()
from api.models.models_dns import DnsZone, DnsRecord
from api.routes.dns import _sync_zone_to_bind, _bump_serial
from scripts.hestia_import import _normalize_txt_content

db = SessionLocal()
zonas = set()
for rec in db.query(DnsRecord).filter(DnsRecord.record_type == 'TXT').all():
    nuevo = _normalize_txt_content(rec.content or '')
    if nuevo and nuevo != (rec.content or ''):
        rec.content = nuevo
        zonas.add(rec.zone_id)
if zonas:
    db.commit()
    for zid in sorted(zonas):
        z = db.query(DnsZone).filter(DnsZone.id == zid).first()
        if not z:
            continue
        z.serial = _bump_serial(z.serial)
        db.commit()
        try:
            _sync_zone_to_bind(z, db)
            print('  . zona resincronizada:', z.domain_name)
        except Exception as e:
            print('  . aviso:', z.domain_name, '->', e)
print('  . zonas con TXT normalizados:', len(zonas))
db.close()
" || echo "  . aviso: el saneo devolvio error (se omite)"
else
    echo "  . venv no encontrado; se omite"
fi

echo "OK 0108: TXT normalizados"
exit 0
