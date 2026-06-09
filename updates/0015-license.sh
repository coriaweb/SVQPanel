#!/bin/bash
# 0015-license.sh
#
# Sistema de licencias del panel. En servidores ya instalados, asegura que existe
# el archivo /etc/svqpanel/license (vacío = modo limitado hasta activar desde la
# UI). El estado de licencia se valida al arrancar y cada 12h (hilo interno).
# Idempotente.

set -euo pipefail

echo "→ 0015: Sistema de licencias del panel..."

mkdir -p /etc/svqpanel
if [ ! -f /etc/svqpanel/license ]; then
    touch /etc/svqpanel/license
    chmod 600 /etc/svqpanel/license
    echo "  Archivo de licencia creado (vacío) — actívala en Sistema → Licencia."
else
    echo "  Archivo de licencia ya existe."
fi

# El panel ya trae el código nuevo por git pull; reiniciar para aplicar el
# middleware de licencia y el chequeo periódico.
systemctl restart svqpanel
sleep 2
if systemctl is-active --quiet svqpanel; then
    echo "  ✓ Panel reiniciado con el sistema de licencias activo"
else
    echo "  ✗ El panel no arrancó — revisa: journalctl -u svqpanel -n 50"
    exit 1
fi

echo "✓ 0015: Sistema de licencias instalado"
exit 0
