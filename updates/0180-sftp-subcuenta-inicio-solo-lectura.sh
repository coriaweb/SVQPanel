#!/bin/bash
# 0180-sftp-subcuenta-inicio-solo-lectura.sh
#
# Subcuentas SFTP: entran YA dentro de su carpeta y pueden ser de solo lectura.
#
# Antes la subcuenta aparecía en la raíz de su jaula (veía .ssh y la carpeta) y
# tenía que entrar a mano, y siempre podía escribir: Oskarbi (.65) quería dar a
# un cliente acceso para DESCARGAR un Excel de stock sin que pudiera subir,
# crear carpetas ni borrar.
#
# Fix (código del panel, `api.cli sftp_sshd_sync`): un `Match User` por
# subcuenta en /etc/ssh/sshd_config.d/svqpanel-sftp-accounts.conf con
# `ForceCommand internal-sftp -d /<carpeta>` y `-R` si es de solo lectura. Va
# antes que svqpanel-sftponly.conf (sshd usa el primer ForceCommand). Se valida
# con sshd -t antes de recargar; si falla queda la configuración anterior. El
# panel regenera el fichero al crear/borrar/cambiar una subcuenta, así que un
# servidor nuevo no necesita nada en install.sh. Idempotente.

set -u

if [ -x /opt/svqpanel/venv/bin/python ]; then
    cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli sftp_sshd_sync \
      && echo "✓ 0180: subcuentas SFTP con carpeta de inicio (y solo lectura si se marca)" \
      || echo "⚠ 0180: no se pudo aplicar la configuración de sshd de las subcuentas (sigue la anterior)"
fi
exit 0
