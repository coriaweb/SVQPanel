#!/bin/bash

###############################################################################
# SVQPanel - Installation Script
# Instala SVQPanel en un servidor Debian 12/13 limpio
# Uso: curl https://raw.githubusercontent.com/coriaweb/SVQPanel/main/install.sh | bash
###############################################################################

set -e  # Salir si hay error

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== SVQPanel - Instalación ===${NC}\n"

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
echo "Disponibles: 7.4, 8.0, 8.1, 8.2, 8.3, 8.5"
echo "Ejemplos: '8.1 8.2' o '8.5' (mínimo 1, máximo 5)"
read -p "Versiones PHP (separadas por espacio): " PHP_VERSIONS

# Validar que haya al menos una versión
if [[ -z "$PHP_VERSIONS" ]]; then
    echo -e "${RED}Debes elegir al menos una versión PHP${NC}"
    exit 1
fi

# Convertir a array y validar
mapfile -t PHP_ARRAY <<< "$(echo "$PHP_VERSIONS" | tr ' ' '\n')"
VALID_VERSIONS=("7.4" "8.0" "8.1" "8.2" "8.3" "8.5")
INVALID_VERSIONS=()

for VER in "${PHP_ARRAY[@]}"; do
    FOUND=0
    for VALID in "${VALID_VERSIONS[@]}"; do
        if [[ "$VER" == "$VALID" ]]; then
            FOUND=1
            break
        fi
    done
    if [[ $FOUND -eq 0 ]]; then
        INVALID_VERSIONS+=("$VER")
    fi
done

if [[ ${#INVALID_VERSIONS[@]} -gt 0 ]]; then
    echo -e "${RED}Error: Versiones PHP inválidas: ${INVALID_VERSIONS[*]}${NC}"
    echo -e "${YELLOW}Solo están disponibles: 7.4, 8.0, 8.1, 8.2, 8.3, 8.5${NC}"
    exit 1
fi

echo -e "${GREEN}✓ PHP versions: ${PHP_ARRAY[*]}${NC}\n"

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
    python3-dev \
    postgresql \
    postgresql-contrib \
    postgresql-server-dev-all \
    certbot

echo -e "${GREEN}✓ Dependencias instaladas${NC}\n"

###############################################################################
# 5. INSTALAR NODEJS (desde NodeSource para versión moderna)
###############################################################################
echo -e "${YELLOW}Instalando Node.js 20...${NC}"
curl -fsSL https://deb.nodesource.com/setup_20.x | bash - > /dev/null 2>&1
apt-get install -y -qq nodejs
echo -e "${GREEN}✓ Node.js $(node -v) instalado${NC}\n"

###############################################################################
# 6. INSTALAR WEBSERVER
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

# Agregar repo de Sury para soportar múltiples versiones PHP
echo -e "${YELLOW}  → Agregando repositorio de Sury para PHP múltiple...${NC}"
curl -sSL https://packages.sury.org/php/apt.gpg | gpg --dearmor -o /usr/share/keyrings/deb.sury.org-php.gpg 2>/dev/null || true

if [[ "$OS_VERSION" == "13" ]]; then
    echo "deb [signed-by=/usr/share/keyrings/deb.sury.org-php.gpg] https://packages.sury.org/php/ trixie main" | tee /etc/apt/sources.list.d/sury-php.list > /dev/null
elif [[ "$OS_VERSION" == "12" ]]; then
    echo "deb [signed-by=/usr/share/keyrings/deb.sury.org-php.gpg] https://packages.sury.org/php/ bookworm main" | tee /etc/apt/sources.list.d/sury-php.list > /dev/null
fi

apt-get update -qq

for PHP_VER in "${PHP_ARRAY[@]}"; do
    echo "  → Instalando PHP $PHP_VER..."

    apt-get install -y -qq \
        php${PHP_VER} \
        php${PHP_VER}-cli \
        php${PHP_VER}-fpm \
        php${PHP_VER}-pgsql \
        php${PHP_VER}-curl \
        php${PHP_VER}-gd \
        php${PHP_VER}-mbstring \
        php${PHP_VER}-xml \
        php${PHP_VER}-zip \
        php${PHP_VER}-bcmath \
        php${PHP_VER}-opcache || echo "  ⚠ PHP $PHP_VER puede no estar disponible"

    systemctl enable php${PHP_VER}-fpm 2>/dev/null || true
    systemctl start php${PHP_VER}-fpm 2>/dev/null || true
done

echo -e "${GREEN}✓ PHP instalado (versiones: ${PHP_ARRAY[*]})${NC}\n"

###############################################################################
# 7. CONFIGURAR POSTGRESQL
###############################################################################
echo -e "${YELLOW}Configurando PostgreSQL...${NC}"

systemctl enable postgresql
systemctl start postgresql

# Crear BD panel (ignorar errores si ya existen)
sudo -u postgres psql << 'EOF' 2>/dev/null || true
DROP DATABASE IF EXISTS panel_db;
DROP ROLE IF EXISTS panel_user;
EOF

# Crear usuario y BD (sin IF NOT EXISTS para compatibilidad con PostgreSQL antiguo)
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

# Dar permisos al schema public para que SQLAlchemy pueda crear tablas
sudo -u postgres psql -d panel_db << 'SQLEOF'
GRANT ALL PRIVILEGES ON SCHEMA public TO panel_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO panel_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO panel_user;
SQLEOF

echo -e "${GREEN}✓ PostgreSQL configurado${NC}\n"

###############################################################################
# 8. CLONAR REPO Y SETUP PYTHON
###############################################################################
echo -e "${YELLOW}Clonando repositorio SVQPanel...${NC}"

# Clonar repo público
REPO_URL="https://github.com/coriaweb/SVQPanel.git"
git clone "$REPO_URL" /opt/svqpanel 2>/dev/null || {
    echo -e "${YELLOW}⚠ No se pudo clonar el repo. Creando estructura básica...${NC}"
    mkdir -p /opt/svqpanel
}

cd /opt/svqpanel

# Crear carpetas si no existen
mkdir -p {scripts,api,config,logs,data}

echo -e "${GREEN}✓ SVQPanel listo en: /opt/svqpanel${NC}\n"

echo -e "${YELLOW}Configurando entorno Python...${NC}"

cd /opt/svqpanel
python3 -m venv venv
source venv/bin/activate

# Instalar dependencias Python
pip install --upgrade pip setuptools wheel -q
pip install -r requirements.txt -q || {
    echo -e "${YELLOW}⚠ Error instalando requirements.txt, instalando manualmente...${NC}"
    pip install fastapi uvicorn sqlalchemy psycopg2 pydantic python-dotenv -q
}

echo -e "${GREEN}✓ Entorno Python creado${NC}\n"

###############################################################################
# 9. CREAR TABLAS EN BASE DE DATOS (via SQLAlchemy)
###############################################################################
echo -e "${YELLOW}Creando tablas en base de datos...${NC}"

cd /opt/svqpanel
source venv/bin/activate

python3 << 'PYEOF'
import sys
sys.path.insert(0, '/opt/svqpanel')
from sqlalchemy import create_engine
from api.models.database import Base
from api.models.models_user import User
from api.models.models_domain import Domain

DATABASE_URL = "postgresql://panel_user:panel_password_123@localhost/panel_db"
engine = create_engine(DATABASE_URL)
Base.metadata.create_all(engine)
print("✓ Tablas creadas correctamente")
PYEOF

echo -e "${GREEN}✓ Base de datos lista${NC}\n"

###############################################################################
# 10. COMPILAR FRONTEND
###############################################################################
echo -e "${YELLOW}Compilando frontend Vue3...${NC}"

if [[ -d "/opt/svqpanel/frontend" ]]; then
    cd /opt/svqpanel/frontend

    # Limpiar node_modules anteriores (evitar conflictos Windows/Linux)
    rm -rf node_modules package-lock.json

    # Instalar dependencias en Linux limpio
    npm install --silent 2>/dev/null || npm install

    # Compilar para producción
    npm run build 2>/dev/null || true

    if [[ -d "dist" ]]; then
        # Arreglar permisos para nginx
        chmod -R 755 /opt/svqpanel/frontend/dist/
        echo -e "${GREEN}✓ Frontend compilado${NC}\n"
    else
        echo -e "${RED}✗ Error: Frontend no se compiló${NC}\n"
    fi

    cd /opt/svqpanel
else
    echo -e "${YELLOW}⚠ Carpeta frontend no encontrada${NC}\n"
fi

###############################################################################
# 10. CREAR ARCHIVO .ENV
###############################################################################
echo -e "${YELLOW}Creando archivo de configuración .env...${NC}"

cat > /opt/svqpanel/.env << 'ENVEOF'
# SVQPanel Configuration
DATABASE_URL=postgresql://panel_user:panel_password_123@localhost/panel_db
PANEL_NAME=SVQPanel
PANEL_VERSION=0.1.0
PANEL_HOST=0.0.0.0
PANEL_PORT=8001
DEBUG=False
SECRET_KEY=change-this-in-production-to-a-random-key
ENVEOF

echo -e "${GREEN}✓ Archivo .env creado${NC}\n"

###############################################################################
# 11. CREAR SYSTEMD SERVICE
###############################################################################
echo -e "${YELLOW}Creando servicio systemd para SVQPanel...${NC}"

cat > /etc/systemd/system/svqpanel.service << 'SERVICEEOF'
[Unit]
Description=SVQPanel Web Control Panel
After=network.target postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/svqpanel
Environment="PATH=/opt/svqpanel/venv/bin"
ExecStart=/opt/svqpanel/venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8001
Restart=always
RestartSec=10
TimeoutStartSec=30

[Install]
WantedBy=multi-user.target
SERVICEEOF

systemctl daemon-reload
systemctl enable svqpanel

echo -e "${GREEN}✓ Servicio systemd creado${NC}\n"

###############################################################################
# 12. CREAR NGINX CONFIG
###############################################################################
if [[ "$WEBSERVER" == "nginx" || "$WEBSERVER" == "apache+nginx" ]]; then
    echo -e "${YELLOW}Creando configuración de Nginx...${NC}"

    cat > /etc/nginx/sites-available/svqpanel << 'NGINXEOF'
upstream svqpanel_backend {
    server 127.0.0.1:8001;
}

server {
    listen 80;
    server_name _;

    client_max_body_size 100M;

    # Servir frontend estático (Vue3 dist)
    root /opt/svqpanel/frontend/dist;
    index index.html;

    # API → proxy al backend
    location /api/ {
        proxy_pass http://svqpanel_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Docs API → proxy al backend
    location /docs {
        proxy_pass http://svqpanel_backend/docs;
        proxy_set_header Host $host;
    }

    location /openapi.json {
        proxy_pass http://svqpanel_backend/openapi.json;
        proxy_set_header Host $host;
    }

    # Frontend → servir archivos estáticos, fallback a index.html (SPA)
    location / {
        try_files $uri $uri/ /index.html;
    }
}
NGINXEOF

    ln -sf /etc/nginx/sites-available/svqpanel /etc/nginx/sites-enabled/svqpanel
    rm -f /etc/nginx/sites-enabled/default
    nginx -t && systemctl restart nginx

    echo -e "${GREEN}✓ Nginx configurado${NC}\n"
fi

###############################################################################
# 13. CREAR USUARIO ADMIN AUTOMÁTICO
###############################################################################
echo -e "${YELLOW}Creando usuario administrador...${NC}"

cd /opt/svqpanel
source venv/bin/activate

# Generar contraseña aleatoria de 16 caracteres (A-Z, a-z, 0-9)
ADMIN_PASSWORD=$(python3 << 'PASSWDEOF'
import random
import string
chars = string.ascii_letters + string.digits
print(''.join(random.choice(chars) for _ in range(16)))
PASSWDEOF
)

# Crear usuario admin en la BD
python3 << 'PYTHONEOF'
import sys
sys.path.insert(0, '/opt/svqpanel')

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from api.models.models_user import User
from api.models.models_domain import Domain

DATABASE_URL = "postgresql://panel_user:panel_password_123@localhost/panel_db"
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()

try:
    # Verificar si el admin ya existe
    existing_admin = session.query(User).filter(User.username == "admin").first()
    if existing_admin:
        print("Admin user already exists")
        sys.exit(0)

    # Crear usuario admin con rol correcto
    admin_user = User(
        username="admin",
        email="admin@localhost",
        role="admin",
        is_admin=True,
        is_active=True
    )
    admin_user.set_password("$ADMIN_PASSWORD")

    session.add(admin_user)
    session.commit()
    print("Admin user created successfully")
except Exception as e:
    print(f"Error creating admin user: {e}")
    session.rollback()
finally:
    session.close()
PYTHONEOF

# Guardar credenciales en archivo seguro
mkdir -p /opt/svqpanel/.credentials
echo "admin:$ADMIN_PASSWORD" > /opt/svqpanel/.credentials/admin.txt
chmod 600 /opt/svqpanel/.credentials/admin.txt

echo -e "${GREEN}✓ Usuario administrador creado${NC}\n"

###############################################################################
# RESUMEN FINAL
###############################################################################
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ INSTALACIÓN COMPLETADA${NC}"
echo -e "${GREEN}════════════════════════════════════════${NC}\n"

echo "Sistema Operativo: $OS_NAME $OS_VERSION"
echo "Configuración:"
echo "  Webserver: $WEBSERVER"
echo "  PHP versions: ${PHP_ARRAY[*]}"
echo "  Directorio: /opt/svqpanel"
echo "  Base de datos: panel_db (PostgreSQL)"
echo -e "\n${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   SVQPanel - Credenciales de Administrador                 ║${NC}"
echo -e "${GREEN}╠════════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║${NC} Usuario:    ${YELLOW}admin${NC}"
echo -e "${GREEN}║${NC} Contraseña: ${YELLOW}$ADMIN_PASSWORD${NC}"
echo -e "${GREEN}║${NC} Email:      ${YELLOW}admin@localhost${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}\n"
# Iniciar servicio automáticamente
systemctl start svqpanel

echo -e "Proximos pasos:"
echo "  1. Verifica el estado: systemctl status svqpanel"
echo "  2. Ver logs: journalctl -u svqpanel -f"
echo -e "\n${GREEN}SVQPanel estará disponible en:${NC}"
echo "  • Panel Web: http://IP_DEL_SERVIDOR"
echo "  • API: http://IP_DEL_SERVIDOR:8001"
echo "  • API Docs: http://IP_DEL_SERVIDOR:8001/docs"
echo -e "\n${YELLOW}Base de datos:${NC}"
echo "  • Host: localhost"
echo "  • User: panel_user"
echo "  • Password: panel_password_123"
echo "  • Database: panel_db"
echo -e "\n${YELLOW}Archivos importantes:${NC}"
echo "  • Configuración: /opt/svqpanel/.env"
echo "  • Credenciales admin: /opt/svqpanel/.credentials/admin.txt"
echo -e "\n${RED}⚠ IMPORTANTE:${NC}"
echo "  • Las credenciales se guardaron en: /opt/svqpanel/.credentials/admin.txt"
echo "  • Cambia la contraseña después de la primera sesión"
echo "  • Cambia las credenciales de BD en .env antes de ir a producción"
echo "  • Asegúrate de usar HTTPS en producción\n"
