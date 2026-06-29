#!/bin/bash
# 0067-migration-tmp-disk.sh
#
# Los temporales del restore de migraciones (descarga del .tar + extracción del
# backup, que pueden ser varios GB) iban a /tmp. En muchos servidores /tmp es un
# tmpfs PEQUEÑO en RAM (p.ej. 2.9 GB): un backup grande lo llenaba ("No space
# left on device") y además competía con la memoria. Ahora van a
# /var/lib/svqpanel/migration-tmp (disco real, decenas de GB).
#
# Este update:
#  1) Crea el dir nuevo en disco real (permisos 700, solo root).
#  2) Limpia los temporales huérfanos que dejó una migración muerta por OOM
#     (el SIGKILL se salta la limpieza del context manager) — directorios de
#     varios GB colgados en /tmp y/o en el dir nuevo.
#
# Idempotente y no interactivo.

set -u

echo "→ 0067: temporales de migración en disco real + limpieza de huérfanos…"

# 1) Dir en disco real.
mkdir -p /var/lib/svqpanel/migration-tmp
chmod 700 /var/lib/svqpanel/migration-tmp
echo "  ✓ /var/lib/svqpanel/migration-tmp"

# 2) Limpiar huérfanos (best-effort). Solo nuestros prefijos, nunca otra cosa.
freed_before=$(df -h /tmp 2>/dev/null | awk 'NR==2{print $4}')
rm -rf /tmp/svq_hestia_* /tmp/svq_webdata_* /tmp/svq_maildata_* /tmp/svq_hestia_up_*.tar 2>/dev/null || true
rm -rf /var/lib/svqpanel/migration-tmp/svq_* 2>/dev/null || true
freed_after=$(df -h /tmp 2>/dev/null | awk 'NR==2{print $4}')
echo "  ✓ huérfanos limpiados (/tmp libre: ${freed_before:-?} → ${freed_after:-?})"

echo "✓ 0067: completado"
exit 0
