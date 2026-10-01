#!/bin/bash
# 0157-swappiness-sysctl-d.sh
#
# vm.swappiness=10 no sobrevivía a un reinicio en Debian 13.
#
# El install lo escribía en /etc/sysctl.conf, pero Debian 13 (trixie) ya no trae
# ese archivo ni lo lee al arrancar (systemd-sysctl solo lee /etc/sysctl.d/ y ya
# no existe el symlink 99-sysctl.conf). El install ahora usa
# /etc/sysctl.d/90-svqpanel-swap.conf; este update lo crea en los servidores ya
# instalados que tienen el swapfile del panel. Idempotente.

set -u

echo "-> 0157: vm.swappiness persistente en /etc/sysctl.d/..."

CONF=/etc/sysctl.d/90-svqpanel-swap.conf
if [ ! -f /swapfile ] || ! grep -q '^/swapfile' /etc/fstab 2>/dev/null; then
    echo "  . sin /swapfile del panel; se omite"
    echo "OK 0157: sin cambios"
    exit 0
fi

if [ -f "$CONF" ]; then
    echo "  . $CONF ya existe"
else
    echo 'vm.swappiness=10' > "$CONF"
    echo "  OK $CONF creado"
fi
sysctl -q -p "$CONF" >/dev/null 2>&1 || true

echo "OK 0157: vm.swappiness = $(sysctl -n vm.swappiness 2>/dev/null)"
exit 0
