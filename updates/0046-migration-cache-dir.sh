#!/bin/bash
# 0046-migration-cache-dir.sh
#
# Crea la carpeta de staging de migraciones: el backup descargado en el ANÁLISIS
# se guarda aquí y se REUTILIZA en la importación, en vez de volver a generarlo y
# traerlo por SSH. Solo root. Idempotente.

set -euo pipefail

echo "→ 0046: carpeta de staging de migraciones…"

mkdir -p /var/lib/svqpanel/migrations
chmod 700 /var/lib/svqpanel/migrations

echo "✓ 0046: /var/lib/svqpanel/migrations listo"
exit 0
