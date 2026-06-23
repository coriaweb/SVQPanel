#!/bin/bash
# 0032-fix-home-perms.sh
#
# Repara los permisos del home de usuarios que quedaron en 750. El home DEBE ser
# 711 para que www-data/Apache pueda ATRAVESARLO y servir la web (con 750,
# 'other' no tiene traverse → 403 Forbidden). Un bug del revert de SFTP
# (_revert_chroot_home dejaba 750 en vez de 711) podía dejar homes mal.
#
# NO toca homes con SFTP-only activo (root:root 755). Invoca el código del panel
# (idempotente). Seguro de re-ejecutar.

set -euo pipefail

echo "→ 0032: reparar permisos de home (750 → 711) para traverse de www-data…"

PYBIN=/opt/svqpanel/venv/bin/python
[ -x "$PYBIN" ] || { echo "  Sin venv del panel — nada que hacer."; exit 0; }

cd /opt/svqpanel
"$PYBIN" -m api.cli fix_home_perms || {
    echo "  ⚠ fix_home_perms devolvió error (no crítico)."
    exit 0
}

echo "✓ 0032: permisos de home reparados"
exit 0
