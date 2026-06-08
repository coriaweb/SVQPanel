#!/bin/bash
# 0009-restic-backups.sh
#
# Nuevo motor de backups: restic (incremental + deduplicado + cifrado en
# CUALQUIER destino: local, SFTP, S3). Sustituye al motor rsync/tar.gz, que solo
# hacía incremental en local. Este update instala restic. La columna de BD
# (restic_password) la crea el panel al arrancar (ALTER en main.py).
#
# Idempotente.

set -euo pipefail

echo "→ 0009: Instalando restic (nuevo motor de backups)..."

if command -v restic >/dev/null 2>&1; then
    echo "  restic ya instalado ($(restic version 2>/dev/null | head -1))."
else
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq restic 2>&1 | tail -2 || {
        echo "  ✗ No se pudo instalar restic"; exit 1; }
    echo "  ✓ restic instalado ($(restic version 2>/dev/null | head -1))"
fi

# Reiniciar el panel para aplicar el ALTER TABLE (restic_password) y el código nuevo
systemctl restart svqpanel 2>/dev/null || true
sleep 2
systemctl is-active --quiet svqpanel && echo "  ✓ Panel reiniciado" || true

echo "✓ 0009: restic instalado; los nuevos backups usan restic (incremental+cifrado)"
exit 0
