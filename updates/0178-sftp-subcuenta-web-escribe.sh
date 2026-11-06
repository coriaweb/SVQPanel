#!/bin/bash
# 0178-sftp-subcuenta-web-escribe.sh
#
# Lo que subía una subcuenta SFTP (p. ej. uploads/2026/11) era de la subcuenta
# con el grupo en r-x: la web (PHP corre como el dueño, del mismo grupo) no
# podía escribir ahí, y un chmod 777 no lo arreglaba porque a un miembro del
# grupo Linux le aplica la entrada del grupo, no la de «otros» (social.beyuri.com,
# «el servidor no deja escribir en la carpeta uploads»).
#
# Fix (código del panel, `api.cli sftp_owner_acl` → grant_owner_access): ACL por
# defecto u:dueño:rwX en las carpetas de cada subcuenta (lo nuevo nace
# escribible por la web) y u:dueño:rwX SOLO en lo que ya creó la subcuenta.
# Las subcuentas nuevas lo traen de serie. Idempotente.

set -u

if [ -x /opt/svqpanel/venv/bin/python ] && command -v setfacl >/dev/null 2>&1; then
    cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli sftp_owner_acl \
      && echo "✓ 0178: la web puede escribir en lo que suben las subcuentas SFTP" \
      || echo "⚠ 0178: no se pudieron ajustar las ACL de las subcuentas SFTP"
fi
exit 0
