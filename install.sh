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
# 2b. SERVIDOR DE CORREO (OPCIONAL)
###############################################################################
echo -e "${YELLOW}¿Instalar servidor de correo electrónico?${NC}"
echo "  Stack: Postfix (SMTP) + Dovecot (IMAP/POP3) + Rspamd (antispam/DKIM) + Redis"
echo -e "  ${YELLOW}Requisitos: IP con rDNS configurado, puerto 25 desbloqueado, registro MX${NC}"
read -p "¿Instalar correo? (s/N): " _MAIL_INPUT
INSTALL_MAIL=false
if [[ "${_MAIL_INPUT,,}" =~ ^(s|si|y|yes)$ ]]; then
    INSTALL_MAIL=true
    echo -e "${GREEN}✓ Servidor de correo seleccionado${NC}\n"
else
    echo -e "${YELLOW}✗ Sin servidor de correo${NC}\n"
fi

###############################################################################
# 2. ELEGIR VERSIONES PHP
###############################################################################
echo -e "${YELLOW}¿Qué versiones PHP necesitas?${NC}"
echo "Disponibles: 7.4, 8.0, 8.1, 8.2, 8.3, 8.4, 8.5"
echo "Ejemplos: '8.1 8.2' o '8.5' (mínimo 1, máximo 6)"
read -p "Versiones PHP (separadas por espacio): " PHP_VERSIONS

# Validar que haya al menos una versión
if [[ -z "$PHP_VERSIONS" ]]; then
    echo -e "${RED}Debes elegir al menos una versión PHP${NC}"
    exit 1
fi

# Convertir a array y validar
mapfile -t PHP_ARRAY <<< "$(echo "$PHP_VERSIONS" | tr ' ' '\n')"
VALID_VERSIONS=("7.4" "8.0" "8.1" "8.2" "8.3" "8.4" "8.5")
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
# 6b. INSTALAR BIND9 (DNS)
###############################################################################
echo -e "${YELLOW}Instalando BIND9 (servidor DNS)...${NC}"

apt-get install -y -qq bind9 bind9-utils bind9-doc dnsutils

# Crear directorio de zonas
mkdir -p /etc/bind/zones
chown root:bind /etc/bind/zones
chmod 775 /etc/bind/zones

# Crear named.conf.zones vacío (para SVQPanel)
if [[ ! -f /etc/bind/named.conf.zones ]]; then
    echo "# SVQPanel DNS zones — generado automáticamente" > /etc/bind/named.conf.zones
    chown root:bind /etc/bind/named.conf.zones
fi

# Añadir include a named.conf.local si no está ya
NAMED_LOCAL="/etc/bind/named.conf.local"
if [[ -f "$NAMED_LOCAL" ]]; then
    if ! grep -q "named.conf.zones" "$NAMED_LOCAL"; then
        echo -e '\ninclude "/etc/bind/named.conf.zones";' >> "$NAMED_LOCAL"
        echo -e "    ${GREEN}✓ Include añadido a named.conf.local${NC}"
    fi
fi

systemctl enable bind9
systemctl restart bind9

echo -e "${GREEN}✓ BIND9 instalado y configurado${NC}\n"

###############################################################################
# 6c. SERVIDOR DE CORREO — Postfix + Dovecot + Rspamd + Redis
###############################################################################
if [[ "$INSTALL_MAIL" == true ]]; then
    echo -e "${YELLOW}Instalando servidor de correo...${NC}"

    # Instalar ssl-cert (certificado snakeoil para TLS inicial)
    apt-get install -y -qq ssl-cert

    # ── 1. POSTFIX ────────────────────────────────────────────────────────
    echo -e "  ${YELLOW}→ Instalando Postfix...${NC}"

    # Preseed para evitar el wizard interactivo
    debconf-set-selections <<< "postfix postfix/mailname string $(hostname -f)"
    debconf-set-selections <<< "postfix postfix/main_mailer_type string 'Internet Site'"
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postfix

    # Crear ficheros de maps vacíos
    touch /etc/postfix/virtual_domains \
          /etc/postfix/virtual_mailbox \
          /etc/postfix/virtual_alias
    postmap /etc/postfix/virtual_domains
    postmap /etc/postfix/virtual_mailbox
    postmap /etc/postfix/virtual_alias

    # Virtual mailboxes: buzones bajo /home/{usuario}/mail/{dominio}/{buzon}/
    postconf -e "virtual_mailbox_domains = hash:/etc/postfix/virtual_domains"
    postconf -e "virtual_mailbox_base = /home"
    postconf -e "virtual_mailbox_maps = hash:/etc/postfix/virtual_mailbox"
    postconf -e "virtual_alias_maps = hash:/etc/postfix/virtual_alias"
    postconf -e "virtual_minimum_uid = 100"
    postconf -e "virtual_uid_maps = static:5000"
    postconf -e "virtual_gid_maps = static:5000"

    # SASL auth vía Dovecot (socket compartido)
    postconf -e "smtpd_sasl_auth_enable = yes"
    postconf -e "smtpd_sasl_type = dovecot"
    postconf -e "smtpd_sasl_path = private/auth"
    postconf -e "smtpd_sasl_security_options = noanonymous"

    # TLS (snakeoil por defecto — reemplazar con cert real en producción)
    postconf -e "smtpd_tls_cert_file = /etc/ssl/certs/ssl-cert-snakeoil.pem"
    postconf -e "smtpd_tls_key_file = /etc/ssl/private/ssl-cert-snakeoil.key"
    postconf -e "smtpd_tls_security_level = may"
    postconf -e "smtp_tls_security_level = may"
    postconf -e "smtpd_tls_protocols = !SSLv2,!SSLv3"

    # Rspamd milter
    postconf -e "smtpd_milters = inet:localhost:11332"
    postconf -e "non_smtpd_milters = inet:localhost:11332"
    postconf -e "milter_default_action = accept"
    postconf -e "milter_protocol = 6"

    # Hostname y origen
    postconf -e "myhostname = $(hostname -f)"
    postconf -e "myorigin = /etc/mailname"

    # Submission (puerto 587) para clientes de correo
    if ! grep -q "^submission" /etc/postfix/master.cf; then
        cat >> /etc/postfix/master.cf << 'MASTEREOF'

submission inet n       -       y       -       -       smtpd
  -o syslog_name=postfix/submission
  -o smtpd_tls_security_level=encrypt
  -o smtpd_sasl_auth_enable=yes
  -o smtpd_reject_unlisted_recipient=no
  -o smtpd_recipient_restrictions=permit_sasl_authenticated,reject
  -o milter_macro_daemon_name=ORIGINATING
MASTEREOF
    fi

    systemctl enable postfix
    systemctl restart postfix
    echo -e "  ${GREEN}✓ Postfix configurado (SMTP 25 + submission 587)${NC}"

    # ── 2. DOVECOT ────────────────────────────────────────────────────────
    echo -e "  ${YELLOW}→ Instalando Dovecot...${NC}"
    apt-get install -y -qq dovecot-core dovecot-imapd dovecot-pop3d dovecot-lmtpd

    # Usuario vmail uid/gid 5000 — propietario de todos los buzones
    groupadd -g 5000 vmail 2>/dev/null || true
    useradd -u 5000 -g vmail -d /var/mail -s /usr/sbin/nologin vmail 2>/dev/null || true

    # Fichero de usuarios virtual (vacío al instalar, el panel lo gestiona)
    touch /etc/dovecot/users
    chmod 640 /etc/dovecot/users
    chown root:dovecot /etc/dovecot/users

    # Auth vía passwd-file con ruta completa por usuario
    # Formato: user@domain:{SHA512-CRYPT}hash:5000:5000::/home/panel_user/mail/domain/user::
    cat > /etc/dovecot/conf.d/auth-passwdfile.conf.ext << 'DOVEAUTHEOF'
passdb {
  driver = passwd-file
  args = scheme=SHA512-CRYPT username_format=%u /etc/dovecot/users
}
userdb {
  driver = passwd-file
  username_format = %u
  args = /etc/dovecot/users
}
DOVEAUTHEOF

    # Deshabilitar auth del sistema, activar passwd-file
    sed -i 's/^!include auth-system.conf.ext/#!include auth-system.conf.ext/' \
        /etc/dovecot/conf.d/10-auth.conf
    grep -q "auth-passwdfile.conf.ext" /etc/dovecot/conf.d/10-auth.conf || \
        echo "!include auth-passwdfile.conf.ext" >> /etc/dovecot/conf.d/10-auth.conf

    # Permitir auth en texto plano (clientes deben usar STARTTLS/TLS)
    sed -i 's/^#\?disable_plaintext_auth = yes/disable_plaintext_auth = no/' \
        /etc/dovecot/conf.d/10-auth.conf

    # Mecanismos de auth: PLAIN y LOGIN (compatibles con todos los clientes)
    grep -q "^auth_mechanisms" /etc/dovecot/conf.d/10-auth.conf || \
        sed -i 's/^#auth_mechanisms = plain/auth_mechanisms = plain login/' \
            /etc/dovecot/conf.d/10-auth.conf

    # Mail location: maildir:~/ → el home del passwd-file ES la raíz del buzón
    # El panel escribe el home como /home/{panel_user}/mail/{domain}/{mailbox}
    grep -q "^mail_location = maildir" /etc/dovecot/conf.d/10-mail.conf || \
        echo "mail_location = maildir:~/" >> /etc/dovecot/conf.d/10-mail.conf

    # Socket SASL para que Postfix pueda autenticar usuarios via Dovecot
    cat > /etc/dovecot/conf.d/99-svqpanel-postfix.conf << 'DOVESASLEOF'
# SVQPanel: socket SASL para Postfix
service auth {
  unix_listener /var/spool/postfix/private/auth {
    mode = 0660
    user = postfix
    group = postfix
  }
}
DOVESASLEOF

    systemctl enable dovecot
    systemctl restart dovecot
    echo -e "  ${GREEN}✓ Dovecot configurado (IMAP 143/993, POP3 110/995, SASL para Postfix)${NC}"

    # ── 3. REDIS ──────────────────────────────────────────────────────────
    echo -e "  ${YELLOW}→ Instalando Redis...${NC}"
    apt-get install -y -qq redis-server
    # Redis solo escucha en localhost por defecto (seguro)
    systemctl enable redis-server
    systemctl start redis-server
    echo -e "  ${GREEN}✓ Redis instalado (backend de Rspamd)${NC}"

    # ── 4. RSPAMD ─────────────────────────────────────────────────────────
    echo -e "  ${YELLOW}→ Instalando Rspamd desde repositorio oficial...${NC}"

    RSPAMD_CODENAME="$(lsb_release -cs)"
    # Rspamd stable puede no tener trixie todavía → fallback a bookworm
    if [[ "$RSPAMD_CODENAME" == "trixie" ]]; then
        RSPAMD_CODENAME="bookworm"
        echo -e "  ${YELLOW}  (usando repositorio bookworm para Rspamd en Debian 13)${NC}"
    fi

    curl -fsSL https://rspamd.com/apt-stable/gpg.key 2>/dev/null \
        | gpg --dearmor > /usr/share/keyrings/rspamd-archive-keyring.gpg
    echo "deb [signed-by=/usr/share/keyrings/rspamd-archive-keyring.gpg] https://rspamd.com/apt-stable/ ${RSPAMD_CODENAME} main" \
        > /etc/apt/sources.list.d/rspamd.list
    apt-get update -qq
    apt-get install -y -qq rspamd

    # Directorio para claves DKIM (el panel genera una clave por dominio)
    mkdir -p /etc/rspamd/dkim
    # Rspamd puede correr como _rspamd o rspamd según la versión
    chown -R _rspamd:_rspamd /etc/rspamd/dkim 2>/dev/null || \
        chown -R rspamd:rspamd /etc/rspamd/dkim 2>/dev/null || true
    chmod 700 /etc/rspamd/dkim

    # Backend Redis para Bayes, fuzzy hashes y greylisting
    cat > /etc/rspamd/local.d/redis.conf << 'RSPAMDREDISEOF'
servers = "127.0.0.1";
RSPAMDREDISEOF

    # DKIM signing dinámico por dominio
    # Clave:     /etc/rspamd/dkim/{domain}.{selector}.key
    # Selectores: /etc/rspamd/dkim/selectors.map  (domain → selector)
    cat > /etc/rspamd/local.d/dkim_signing.conf << 'RSPAMDKIMEOF'
path = "/etc/rspamd/dkim/$domain.$selector.key";
selector_map = "/etc/rspamd/dkim/selectors.map";
use_domain = "header";
allow_username_mismatch = true;
sign_local = true;
sign_authenticated = true;
RSPAMDKIMEOF

    # Mapa de selectores vacío (el panel lo rellena al generar DKIM por dominio)
    touch /etc/rspamd/dkim/selectors.map

    # Cabeceras de autenticación añadidas a los mensajes
    cat > /etc/rspamd/local.d/milter_headers.conf << 'RSPAMDMILTEREOF'
use = ["x-spam-status", "x-spam-score", "x-rspamd-score", "authentication-results"];
RSPAMDMILTEREOF

    # Bayes con Redis
    cat > /etc/rspamd/local.d/classifier-bayes.conf << 'RSPAMDBAYESEOF'
backend = "redis";
RSPAMDBAYESEOF

    # Greylisting activado
    cat > /etc/rspamd/local.d/greylisting.conf << 'RSPAMDGREYEOF'
enabled = true;
RSPAMDGREYEOF

    systemctl enable rspamd
    systemctl restart rspamd
    echo -e "  ${GREEN}✓ Rspamd configurado (antispam + DKIM + greylisting + Bayes/Redis)${NC}"

    # ── 5. VERIFICACIÓN FINAL ─────────────────────────────────────────────
    echo ""
    echo -e "  Estado de servicios de correo:"
    for SVC in postfix dovecot rspamd redis-server; do
        if systemctl is-active --quiet "$SVC"; then
            echo -e "    ${GREEN}✓ $SVC — activo${NC}"
        else
            echo -e "    ${RED}✗ $SVC — NO activo (revisar: journalctl -u $SVC)${NC}"
        fi
    done

    echo -e "\n${GREEN}✓ Servidor de correo instalado${NC}\n"
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

PHP_INSTALLED=()

for PHP_VER in "${PHP_ARRAY[@]}"; do
    echo "  → Instalando PHP $PHP_VER..."

    # Paquetes base (obligatorios)
    if apt-get install -y -q \
        php${PHP_VER} \
        php${PHP_VER}-cli \
        php${PHP_VER}-fpm \
        php${PHP_VER}-pgsql \
        php${PHP_VER}-mysql \
        php${PHP_VER}-curl \
        php${PHP_VER}-gd \
        php${PHP_VER}-mbstring \
        php${PHP_VER}-xml \
        php${PHP_VER}-zip \
        php${PHP_VER}-bcmath; then

        echo -e "    ${GREEN}✓ PHP ${PHP_VER} paquetes base instalados${NC}"

        # Extensiones opcionales (fallos ignorados)
        for EXT in opcache intl soap readline; do
            apt-get install -y -q "php${PHP_VER}-${EXT}" 2>/dev/null && \
                echo "    ✓ php${PHP_VER}-${EXT}" || \
                echo "    ⚠ php${PHP_VER}-${EXT} no disponible (ignorado)"
        done

        # Habilitar y arrancar FPM
        systemctl enable "php${PHP_VER}-fpm" 2>/dev/null && \
        systemctl start  "php${PHP_VER}-fpm" 2>/dev/null

        # Verificar que FPM arrancó (socket debe existir)
        sleep 1
        if [[ -S "/run/php/php${PHP_VER}-fpm.sock" ]]; then
            echo -e "    ${GREEN}✓ PHP ${PHP_VER}-fpm arrancado y socket activo${NC}"
            PHP_INSTALLED+=("$PHP_VER")
        else
            echo -e "    ${YELLOW}⚠ PHP ${PHP_VER}-fpm instalado pero socket no activo${NC}"
            PHP_INSTALLED+=("$PHP_VER")   # Lo marcamos igual — el panel puede arrancarlo
        fi
    else
        echo -e "    ${RED}✗ PHP ${PHP_VER} no disponible en este sistema${NC}"
    fi
done

echo -e "${GREEN}✓ PHP instalado: ${PHP_INSTALLED[*]:-ninguno}${NC}\n"

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
from api.models.models_settings import Settings
from api.models.models_dns import DnsZone, DnsRecord

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

# MAIL_ENABLED depende de si se seleccionó instalar correo
MAIL_ENABLED_VAL="false"
if [[ "$INSTALL_MAIL" == true ]]; then
    MAIL_ENABLED_VAL="true"
fi

cat > /opt/svqpanel/.env << ENVEOF
# SVQPanel Configuration
DATABASE_URL=postgresql://panel_user:panel_password_123@localhost/panel_db
PANEL_NAME=SVQPanel
PANEL_VERSION=0.1.0
PANEL_HOST=0.0.0.0
PANEL_PORT=8001
DEBUG=False
SECRET_KEY=change-this-in-production-to-a-random-key
MAIL_ENABLED=${MAIL_ENABLED_VAL}
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

# Crear usuario admin en la BD (pasar contraseña via variable de entorno)
SVQPANEL_ADMIN_PASS="$ADMIN_PASSWORD" python3 << 'PYTHONEOF'
import sys
import os
sys.path.insert(0, '/opt/svqpanel')

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from api.models.models_user import User
from api.models.models_domain import Domain

DATABASE_URL = "postgresql://panel_user:panel_password_123@localhost/panel_db"
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()

# Leer contraseña desde variable de entorno
admin_password = os.environ.get('SVQPANEL_ADMIN_PASS', 'changeme123')

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
    admin_user.set_password(admin_password)

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
echo "  Webserver:    $WEBSERVER"
echo "  PHP versions: ${PHP_ARRAY[*]}"
echo "  Correo:       $( [[ "$INSTALL_MAIL" == true ]] && echo 'Postfix + Dovecot + Rspamd' || echo 'No instalado' )"
echo "  Directorio:   /opt/svqpanel"
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
if [[ "$INSTALL_MAIL" == true ]]; then
    echo -e "\n${YELLOW}Servidor de correo:${NC}"
    echo "  • SMTP entrada:  puerto 25   (MX de tus dominios)"
    echo "  • SMTP envío:    puerto 587  (clientes con STARTTLS + auth)"
    echo "  • IMAP:          puerto 143  (STARTTLS) / 993 (TLS)"
    echo "  • POP3:          puerto 110  (STARTTLS) / 995 (TLS)"
    echo "  • Rspamd UI:     http://IP_DEL_SERVIDOR:11334"
    echo "  • Buzones en:    /home/{usuario}/mail/{dominio}/{buzon}/"
    echo -e "  ${YELLOW}Configura por dominio: registro MX, rDNS (PTR), SPF, DKIM y DMARC${NC}"
fi

echo -e "\n${RED}⚠ IMPORTANTE:${NC}"
echo "  • Las credenciales se guardaron en: /opt/svqpanel/.credentials/admin.txt"
echo "  • Cambia la contraseña después de la primera sesión"
echo "  • Cambia las credenciales de BD en .env antes de ir a producción"
echo "  • Asegúrate de usar HTTPS en producción"
if [[ "$INSTALL_MAIL" == true ]]; then
    echo "  • Correo: sustituye el certificado snakeoil por uno real (Let's Encrypt)"
fi
