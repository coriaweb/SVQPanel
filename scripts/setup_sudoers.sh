#!/bin/bash
###############################################################################
# SVQPanel — Configurar sudo para FastAPI
#
# Permite que el usuario bajo el que corre FastAPI ejecute apt-get/apt
# sin pedir contraseña (necesario para el panel de actualizaciones)
###############################################################################

if [[ $EUID -ne 0 ]]; then
    echo "Este script debe ejecutarse como root (sudo)"
    exit 1
fi

# Detectar usuario de FastAPI (según systemd service)
# Por defecto es 'root' según install.sh, pero podría variar
SVQPANEL_USER="root"

# Verificar si el usuario existe
if ! id "$SVQPANEL_USER" &>/dev/null; then
    echo "Error: Usuario $SVQPANEL_USER no encontrado"
    exit 1
fi

echo "Configurando sudoers para: $SVQPANEL_USER"

# Crear archivo de sudoers específico (evita editar /etc/sudoers directamente)
SUDOERS_FILE="/etc/sudoers.d/svqpanel-apt"

cat > "$SUDOERS_FILE" << EOF
# SVQPanel — permisos para apt-get/apt (panel de actualizaciones)
$SVQPANEL_USER ALL=(ALL) NOPASSWD: /usr/bin/apt-get, /usr/bin/apt
EOF

chmod 0440 "$SUDOERS_FILE"

# Verificar sintaxis
if ! visudo -c -f "$SUDOERS_FILE" &>/dev/null; then
    echo "Error: Sintaxis inválida en sudoers"
    rm "$SUDOERS_FILE"
    exit 1
fi

echo "✓ Sudoers configurado en $SUDOERS_FILE"
echo "  $SVQPANEL_USER ahora puede ejecutar apt-get/apt sin contraseña"
