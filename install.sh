#!/bin/bash

###############################################################################
# Panel Control - Installation Script
# Instala el panel en un servidor Ubuntu limpio
# Uso: curl https://raw.github.com/tu-empresa/panel/main/install.sh | bash
###############################################################################

set -e  # Salir si hay error

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== Panel Control - Instalación ===${NC}\n"

# Detectar SO
if [[ ! -f /etc/os-release ]]; then
    echo -e "${RED}Error: No se puede detectar el SO${NC}"
    exit 1
fi

source /etc/os-release
OS_VERSION=$VERSION_ID
OS_NAME=$ID

# Validar que sea Debian 12 o 13
if [[ "$OS_NAME" != "debian" ]]; then
    echo -e "${RED}Error: Este panel solo es compatible con Debian. Detectado: $OS_NAME${NC}"
    exit 1
fi

if [[ "$OS_VERSION" != "12" && "$OS_VERSION" != "13" ]]; then
    echo -e "${RED}Error: Necesitas Debian 12 o 13. Tienes: $OS_VERSION${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Debian $OS_VERSION detectado${NC}\n"

###############################################################################
# 1. ELEGIR WEBSERVER
###############################################################################
echo -e "${YELLOW}¿Qué webserver necesitas?${NC}"
echo "1) Nginx solo"
echo "2) Apache + Nginx (Apache para legacy, Nginx para velocidad)"
read -p "Elige (1 o 2): " WEBSERVER_CHOICE

case $WEBSERVER_CHOICE in
    1)
        WEBSERVER="nginx"
        echo -e "${GREEN}✓ Nginx seleccionado${NC}\n"
        ;;
    2)
        WEBSERVER="apache+nginx"
        echo -e "${GREEN}✓ Apache + Nginx seleccionado${NC}\n"
        ;;
    *)
        echo -e "${RED}Opción inválida${NC}"
        exit 1
        ;;
esac

###############################################################################
# 2. ELEGIR VERSIONES PHP
###############################################################################
echo -e "${YELLOW}¿Qué versiones PHP necesitas?${NC}"
echo "Disponibles: 7.4, 8.0, 8.1, 8.2, 8.3"
echo "Ejemplos: '8.1 8.2' o '8.2' (mínimo 1, máximo 5)"
read -p "Versiones PHP (separadas por espacio): " PHP_VERSIONS

# Validar que haya al menos una versión
if [[ -z "$PHP_VERSIONS" ]]; then
    echo -e "${RED}Debes elegir al menos una versión PHP${NC}"
    exit 1
fi

# Convertir a array
PHP_ARRAY=($PHP_VERSIONS)
echo -e "${GREEN}✓ PHP versions: ${PHP_ARRAY[@]}${NC}\n"

###############################################################################
# 3. ACTUALIZAR SISTEMA
###############################################################################
echo -e "${YELLOW}Actualizando sistema...${NC}"
apt-get update -qq
apt-get upgrade -y -qq
echo -e "${GREEN}✓ Sistema actualizado${NC}\n"

###############################################################################
# 4. INSTALAR DEPENDENCIAS BASE
###############################################################################
echo -e "${YELLOW}Instalando dependencias base...${NC}"

apt-get install -y -qq \
    curl \
    wget \
    git \
    vim \
    htop \
    net-tools \
    build-essential \
    software-properties-common \
    apt-transport-https \
    ca-certificates \
    gnupg \
    lsb-release \
    unzip \
    zip \
    openssl \
    libssl-dev \
    python3 \
    python3-pip \
    python3-venv \
    postgresql \
    postgresql-contrib \
    certbot

echo -e "${GREEN}✓ Dependencias instaladas${NC}\n"

###############################################################################
# 5. INSTALAR WEBSERVER
###############################################################################
if [[ "$WEBSERVER" == "nginx" || "$WEBSERVER" == "apache+nginx" ]]; then
    echo -e "${YELLOW}Instalando Nginx...${NC}"
    apt-get install -y -qq nginx
    systemctl enable nginx
    systemctl start nginx
    echo -e "${GREEN}✓ Nginx instalado${NC}\n"
fi

if [[ "$WEBSERVER" == "apache+nginx" ]]; then
    echo -e "${YELLOW}Instalando Apache...${NC}"
    apt-get install -y -qq apache2 libapache2-mod-php
    a2enmod rewrite
    a2enmod headers
    a2enmod ssl
    systemctl enable apache2
    systemctl start apache2
    echo -e "${GREEN}✓ Apache instalado${NC}\n"
fi

###############################################################################
# 6. INSTALAR PHP
###############################################################################
echo -e "${YELLOW}Instalando PHP y extensiones...${NC}"

# Añadir PPA de Sury (para múltiples versiones PHP)
add-apt-repository -y ppa:ondrej/php > /dev/null 2>&1
apt-get update -qq

for PHP_VER in "${PHP_ARRAY[@]}"; do
    echo "  → Instalando PHP $PHP_VER..."
    
    apt-get install -y -qq \
        php${PHP_VER} \
        php${PHP_VER}-cli \
        php${PHP_VER}-fpm \
        php${PHP_VER}-mysql \
        php${PHP_VER}-pgsql \
        php${PHP_VER}-curl \
        php${PHP_VER}-gd \
        php${PHP_VER}-json \
        php${PHP_VER}-mbstring \
        php${PHP_VER}-xml \
        php${PHP_VER}-zip \
        php${PHP_VER}-bcmath \
        php${PHP_VER}-opcache
    
    systemctl enable php${PHP_VER}-fpm
    systemctl start php${PHP_VER}-fpm
done

echo -e "${GREEN}✓ PHP instalado (versiones: ${PHP_ARRAY[@]})${NC}\n"

###############################################################################
# 7. CONFIGURAR POSTGRESQL
###############################################################################
echo -e "${YELLOW}Configurando PostgreSQL...${NC}"

systemctl enable postgresql
systemctl start postgresql

# Crear BD panel
sudo -u postgres psql << EOF
CREATE DATABASE panel_db;
CREATE USER panel_user WITH PASSWORD 'panel_password_123';
ALTER ROLE panel_user SET client_encoding TO 'utf8';
ALTER ROLE panel_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE panel_user SET default_transaction_deferrable TO on;
ALTER ROLE panel_user SET default_transaction_deferrable TO off;
ALTER ROLE panel_user SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE panel_db TO panel_user;
EOF

echo -e "${GREEN}✓ PostgreSQL configurado${NC}\n"

###############################################################################
# 8. CLONAR REPO Y SETUP PYTHON
###############################################################################
echo -e "${YELLOW}Clonando repositorio del panel...${NC}"

# Clonar repo público (cambiar URL por tu repo)
REPO_URL="https://github.com/tu-usuario/panel.git"
git clone "$REPO_URL" /opt/panel 2>/dev/null || {
    echo -e "${YELLOW}⚠ No se pudo clonar el repo. Creando estructura básica...${NC}"
    mkdir -p /opt/panel
}

cd /opt/panel

# Crear carpetas si no existen
mkdir -p {scripts,api,config,logs,data}

echo -e "${GREEN}✓ Panel listo en: /opt/panel${NC}\n"

echo -e "${YELLOW}Configurando entorno Python...${NC}"

cd /opt/panel
python3 -m venv venv
source venv/bin/activate

# Instalar dependencias Python (se crearán luego)
pip install --upgrade pip setuptools wheel -q

echo -e "${GREEN}✓ Entorno Python creado${NC}\n"

###############################################################################
# 9. CREAR ARCHIVO DE CONFIGURACIÓN
###############################################################################
echo -e "${YELLOW}Creando archivo de configuración...${NC}"

cat > /opt/panel/config/config.py << 'CONFIGEOF'
import os

# Panel Settings
PANEL_NAME = "Tu Panel"
PANEL_VERSION = "1.0.0"
PANEL_PORT = 8001
PANEL_HOST = "127.0.0.1"

# Database
DATABASE_URL = "postgresql://panel_user:panel_password_123@localhost/panel_db"

# Paths
BASE_DIR = "/opt/panel"
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
DATA_DIR = os.path.join(BASE_DIR, "data")

# Webserver
WEBSERVER = "WEBSERVER_PLACEHOLDER"
PHP_VERSIONS = [PHP_VERSIONS_PLACEHOLDER]
DEFAULT_PHP = "DEFAULT_PHP_PLACEHOLDER"

# Security
SECRET_KEY = "change-this-in-production"
API_TOKEN = "generate-this-token"

# Logging
LOG_LEVEL = "INFO"
LOG_FILE = os.path.join(LOGS_DIR, "panel.log")
CONFIGEOF

# Reemplazar placeholders
sed -i "s/WEBSERVER_PLACEHOLDER/$WEBSERVER/" /opt/panel/config/config.py
sed -i "s/PHP_VERSIONS_PLACEHOLDER/$(echo \"'${PHP_ARRAY[0]}'\" | sed 's/ /, /g')/" /opt/panel/config/config.py
sed -i "s/DEFAULT_PHP_PLACEHOLDER/${PHP_ARRAY[0]}/" /opt/panel/config/config.py

echo -e "${GREEN}✓ Configuración creada${NC}\n"

###############################################################################
# RESUMEN FINAL
###############################################################################
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ INSTALACIÓN COMPLETADA${NC}"
echo -e "${GREEN}════════════════════════════════════════${NC}\n"

echo "Sistema Operativo: $OS_NAME $OS_VERSION"
echo "Configuración:"
echo "  Webserver: $WEBSERVER"
echo "  PHP versions: ${PHP_ARRAY[@]}"
echo "  Directorio: /opt/panel"
echo "  Base de datos: panel_db (PostgreSQL)"
echo -e "\nPróximos pasos:"
echo "  1. cd /opt/panel"
echo "  2. source venv/bin/activate"
echo "  3. pip install -r requirements.txt (cuando se cree)"
echo "  4. python api/main.py"
echo -e "\n${YELLOW}El panel estará disponible en: http://localhost:8001${NC}\n"
