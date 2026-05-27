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
# 2b-2. ROUNDCUBE WEBMAIL (solo si se instala correo)
###############################################################################
INSTALL_ROUNDCUBE=false
if [[ "$INSTALL_MAIL" == true ]]; then
    echo -e "${YELLOW}¿Instalar Roundcube Webmail?${NC}"
    echo "  Webmail en /webmail — autologin desde el panel (1 clic por buzón)"
    read -p "¿Instalar Roundcube? (s/N): " _RC_INPUT
    if [[ "${_RC_INPUT,,}" =~ ^(s|si|y|yes)$ ]]; then
        INSTALL_ROUNDCUBE=true
        echo -e "${GREEN}✓ Roundcube seleccionado${NC}\n"
    else
        echo -e "${YELLOW}✗ Sin Roundcube${NC}\n"
    fi
fi

###############################################################################
# 2c. BASE DE DATOS PARA CLIENTES (MariaDB — opcional)
###############################################################################
echo -e "${YELLOW}¿Instalar MariaDB para bases de datos de clientes?${NC}"
echo "  Los clientes podrán crear BDs MySQL/MariaDB para sus aplicaciones"
echo "  (WordPress, Joomla, PrestaShop, Laravel, etc.)"
echo -e "  Se instala MariaDB ${YELLOW}11.4 LTS${NC} desde el repositorio oficial."
read -p "¿Instalar MariaDB? (s/N): " _MARIADB_INPUT
INSTALL_MARIADB=false
if [[ "${_MARIADB_INPUT,,}" =~ ^(s|si|y|yes)$ ]]; then
    INSTALL_MARIADB=true
    echo -e "${GREEN}✓ MariaDB seleccionado${NC}\n"
else
    echo -e "${YELLOW}✗ Sin MariaDB para clientes${NC}\n"
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
    certbot \
    rsyslog \
    mailutils

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

systemctl enable named
systemctl restart named

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
    hostname -f > /etc/mailname
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
# 6d. ROUNDCUBE WEBMAIL (descarga desde GitHub — compatible PHP 8.4/8.5)
###############################################################################
if [[ "$INSTALL_ROUNDCUBE" == true ]]; then
    echo -e "${YELLOW}Instalando Roundcube Webmail...${NC}"

    # Dependencias PHP necesarias (sin el paquete roundcube de Debian, que es viejo)
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        php-net-sieve php-pear php-intl php-zip php-xml \
        php-mbstring php-gd php-pgsql 2>/dev/null || true

    # Generar credenciales aleatorias
    RC_DB_PASS=$(openssl rand -base64 18 | tr -dc 'a-zA-Z0-9' | head -c 20)
    RC_DES_KEY=$(openssl rand -base64 18 | tr -dc 'a-zA-Z0-9' | head -c 24)

    # ── 1. Base de datos PostgreSQL para Roundcube ─────────────────────────
    echo -e "  ${YELLOW}→ Creando BD roundcubemail en PostgreSQL...${NC}"
    sudo -u postgres psql 2>/dev/null << RCDBEOF || true
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'roundcubemail') THEN
        CREATE USER roundcubemail WITH PASSWORD '${RC_DB_PASS}';
    ELSE
        ALTER USER roundcubemail WITH PASSWORD '${RC_DB_PASS}';
    END IF;
END
\$\$;
DROP DATABASE IF EXISTS roundcubemail;
CREATE DATABASE roundcubemail OWNER roundcubemail;
RCDBEOF
    echo -e "  ${GREEN}✓ BD roundcubemail creada${NC}"

    # ── 2. Descargar Roundcube latest desde GitHub ─────────────────────────
    echo -e "  ${YELLOW}→ Descargando Roundcube (última versión estable)...${NC}"

    # Obtener la versión más reciente
    RC_VERSION=$(curl -s https://api.github.com/repos/roundcube/roundcubemail/releases/latest \
                 | grep '"tag_name"' | head -1 \
                 | sed 's/.*"tag_name": "\([^"]*\)".*/\1/')

    # Fallback si la API no responde (1.7.0 = primera versión compatible con PHP 8.5)
    RC_VERSION="${RC_VERSION:-1.7.0}"
    echo -e "  ${YELLOW}  Versión: ${RC_VERSION}${NC}"

    RC_APP_DIR="/var/www/roundcube"
    RC_TGZ="/tmp/roundcubemail-${RC_VERSION}-complete.tar.gz"

    curl -fsSL \
        "https://github.com/roundcube/roundcubemail/releases/download/${RC_VERSION}/roundcubemail-${RC_VERSION}-complete.tar.gz" \
        -o "$RC_TGZ"

    rm -rf "$RC_APP_DIR"
    mkdir -p "$RC_APP_DIR"
    tar -xzf "$RC_TGZ" -C /tmp/
    mv "/tmp/roundcubemail-${RC_VERSION}/"* "$RC_APP_DIR/"
    rm -f "$RC_TGZ"

    # Directorios con permisos de escritura para www-data
    for D in temp logs; do
        mkdir -p "${RC_APP_DIR}/${D}"
        chown -R www-data:www-data "${RC_APP_DIR}/${D}"
        chmod 775 "${RC_APP_DIR}/${D}"
    done

    echo -e "  ${GREEN}✓ Roundcube ${RC_VERSION} descargado en ${RC_APP_DIR}${NC}"

    # ── 3. Parche PHP 8.4/8.5 — array_first / array_last ──────────────────
    # bootstrap.php define funciones que PHP 8.4+ ya trae nativas → conflicto
    BOOTSTRAP="${RC_APP_DIR}/program/lib/Roundcube/bootstrap.php"
    if [[ -f "$BOOTSTRAP" ]]; then
        python3 << PYEOF
import re
filepath = '${BOOTSTRAP}'
with open(filepath, 'r') as f:
    lines = f.readlines()
result = []
i = 0
while i < len(lines):
    line = lines[i]
    m = re.search(r'^function (array_first|array_last|array_is_list)\(', line)
    if m:
        fname = m.group(1)
        result.append(f"if (!function_exists('{fname}')) {{\n")
        result.append(line)
        i += 1
        depth = 1
        while i < len(lines) and depth > 0:
            result.append(lines[i])
            depth += lines[i].count('{') - lines[i].count('}')
            i += 1
        result.append("}\n")
        continue
    result.append(line)
    i += 1
with open(filepath, 'w') as f:
    f.writelines(result)
print("bootstrap.php parcheado para PHP 8.4/8.5")
PYEOF
        echo -e "  ${GREEN}✓ Parche PHP 8.4/8.5 aplicado${NC}"
    fi

    # ── 4. Crear symlink /var/www/webmail ──────────────────────────────────
    ln -sfn "$RC_APP_DIR" /var/www/webmail
    echo -e "  ${GREEN}✓ Symlink /var/www/webmail → $RC_APP_DIR${NC}"

    # ── 5. Configurar Roundcube ────────────────────────────────────────────
    echo -e "  ${YELLOW}→ Configurando Roundcube...${NC}"
    mkdir -p "${RC_APP_DIR}/config"
    cat > "${RC_APP_DIR}/config/config.inc.php" << RCCONFEOF
<?php
// SVQPanel — Roundcube config generado automáticamente
\$config['db_dsnw'] = 'pgsql://roundcubemail:${RC_DB_PASS}@localhost/roundcubemail';

// IMAP (Dovecot)
\$config['imap_host']      = 'localhost:143';
\$config['imap_auth_type']  = null;

// SMTP (Postfix submission)
\$config['smtp_host']      = 'localhost:587';
\$config['smtp_user']      = '%u';
\$config['smtp_pass']      = '%p';
\$config['smtp_auth_type']  = '';

// Panel
\$config['product_name']   = 'Webmail';
\$config['support_url']    = '';
\$config['des_key']         = '${RC_DES_KEY}';

// Plugin autologin SVQPanel
\$config['plugins'] = ['svqpanel_autologin'];

// Skin
\$config['skin']             = 'elastic';
\$config['auto_create_user'] = true;
\$config['login_autocomplete'] = 2;
RCCONFEOF

    # Enlace /etc/roundcube → config en RC_APP_DIR (compatibilidad)
    mkdir -p /etc/roundcube
    ln -sfn "${RC_APP_DIR}/config/config.inc.php" /etc/roundcube/config.inc.php 2>/dev/null || true

    echo -e "  ${GREEN}✓ Configuración Roundcube creada${NC}"

    # ── 6. Inicializar esquema de BD ───────────────────────────────────────
    echo -e "  ${YELLOW}→ Inicializando esquema de BD de Roundcube...${NC}"
    RC_SQL="${RC_APP_DIR}/SQL/postgres.initial.sql"
    if [[ -f "$RC_SQL" ]]; then
        PGPASSWORD="$RC_DB_PASS" psql -U roundcubemail -h localhost roundcubemail \
            < "$RC_SQL" 2>/dev/null || true
        echo -e "  ${GREEN}✓ Esquema BD inicializado${NC}"
    else
        echo -e "  ${YELLOW}⚠ No se encontró SQL inicial — inicializa manualmente${NC}"
    fi

    # ── 7. Instalar plugin svqpanel_autologin ──────────────────────────────
    echo -e "  ${YELLOW}→ Instalando plugin de autologin...${NC}"
    RC_PLUGIN_DIR="${RC_APP_DIR}/plugins/svqpanel_autologin"
    mkdir -p "$RC_PLUGIN_DIR"

    if [[ -f /opt/svqpanel/scripts/svqpanel_autologin.php ]]; then
        cp /opt/svqpanel/scripts/svqpanel_autologin.php \
           "${RC_PLUGIN_DIR}/svqpanel_autologin.php"
    else
        cat > "${RC_PLUGIN_DIR}/svqpanel_autologin.php" << 'RCPLUGEOF'
<?php
class svqpanel_autologin extends rcube_plugin
{
    public $task = '.*';
    public $noframe = true;
    private const PANEL_PORT    = 8001;
    private const FETCH_TIMEOUT = 5;
    public function init(): void { $this->add_hook('startup', [$this, 'startup']); }
    public function startup(array $args): array
    {
        $raw = $_GET['svqtoken'] ?? $_POST['svqtoken'] ?? null;
        if (!$raw) return $args;
        $token = preg_replace('/[^a-f0-9]/', '', strtolower($raw));
        if (strlen($token) !== 32) return $args;
        $data = $this->fetch_credentials($token);
        if (!$data || empty($data['username']) || empty($data['password'])) return $args;
        $rcmail = rcube::get_instance();
        if ($rcmail->login($data['username'], $data['password'], $data['imap_host'] ?? 'localhost', false)) {
            $rcmail->session->remove('user_lang');
            $rcmail->output->redirect(['_task' => 'mail']);
            exit;
        }
        return $args;
    }
    private function fetch_credentials(string $token): ?array
    {
        $url = sprintf('http://127.0.0.1:%d/api/internal/webmail-token/%s', self::PANEL_PORT, rawurlencode($token));
        $ctx = stream_context_create(['http' => ['timeout' => self::FETCH_TIMEOUT, 'ignore_errors' => true]]);
        $resp = @file_get_contents($url, false, $ctx);
        if (!$resp) return null;
        $data = json_decode($resp, true);
        return isset($data['detail']) ? null : $data;
    }
}
RCPLUGEOF
    fi
    echo -e "  ${GREEN}✓ Plugin svqpanel_autologin instalado${NC}"

    # ── 8. Permisos finales ────────────────────────────────────────────────
    chown -R www-data:www-data "${RC_APP_DIR}/config" \
                               "${RC_APP_DIR}/temp" \
                               "${RC_APP_DIR}/logs"

    # ── 9. Guardar credenciales ────────────────────────────────────────────
    mkdir -p /opt/svqpanel/.credentials
    cat > /opt/svqpanel/.credentials/roundcube.txt << RCCREDEOF
roundcubemail_db_pass=${RC_DB_PASS}
roundcube_des_key=${RC_DES_KEY}
roundcube_version=${RC_VERSION}
roundcube_path=${RC_APP_DIR}
RCCREDEOF
    chmod 600 /opt/svqpanel/.credentials/roundcube.txt

    echo -e "\n${GREEN}✓ Roundcube ${RC_VERSION} instalado en ${RC_APP_DIR}${NC}\n"
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
# 7b. INSTALAR MARIADB 11.4 LTS (bases de datos para clientes)
###############################################################################
MARIADB_PANEL_PASS=""
if [[ "$INSTALL_MARIADB" == true ]]; then
    echo -e "${YELLOW}Instalando MariaDB 11.4 LTS (repositorio oficial)...${NC}"

    # ── Repositorio oficial de MariaDB ────────────────────────────────────────
    curl -LsS https://r.mariadb.com/downloads/mariadb_repo_setup \
        | bash -s -- --mariadb-server-version="mariadb-11.4" > /dev/null 2>&1
    apt-get update -qq
    apt-get install -y mariadb-server mariadb-client

    systemctl enable mariadb
    systemctl start mariadb

    # Verificar binario cliente (necesario para que el panel gestione BDs)
    if [[ ! -x /usr/bin/mariadb && ! -x /usr/bin/mysql ]]; then
        echo -e "${RED}Error: binario cliente mariadb no encontrado tras instalar mariadb-client${NC}"
        exit 1
    fi
    echo -e "  ${GREEN}✓ MariaDB 11.4 instalado${NC}"

    # ── Generar contraseñas aleatorias ────────────────────────────────────────
    MARIADB_ROOT_PASS=$(python3 -c \
        "import secrets,string; \
         chars=string.ascii_letters+string.digits; \
         print(''.join(secrets.choice(chars) for _ in range(24)))")

    MARIADB_PANEL_PASS=$(python3 -c \
        "import secrets,string; \
         chars=string.ascii_letters+string.digits; \
         print(''.join(secrets.choice(chars) for _ in range(24)))")

    # ── Asegurar instalación (equivale a mysql_secure_installation) ────────────
    mysql --user=root << MARIADBEOF
-- Contraseña root
ALTER USER 'root'@'localhost' IDENTIFIED BY '${MARIADB_ROOT_PASS}';
-- Eliminar usuarios anónimos y BD test
DELETE FROM mysql.user WHERE User='';
DROP DATABASE IF EXISTS test;
DELETE FROM mysql.db WHERE Db='test' OR Db='test\\_%';
-- Usuario administrador del panel SVQPanel
-- Necesita privilegios de datos WITH GRANT OPTION para poder otorgarlos
-- a los usuarios cliente (GRANT ALL ON db.* TO cliente)
DROP USER IF EXISTS 'svqpanel_admin'@'localhost';
CREATE USER 'svqpanel_admin'@'localhost'
    IDENTIFIED BY '${MARIADB_PANEL_PASS}';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, INDEX, ALTER,
      CREATE TEMPORARY TABLES, LOCK TABLES, EXECUTE,
      CREATE VIEW, SHOW VIEW, CREATE ROUTINE, ALTER ROUTINE,
      EVENT, TRIGGER, CREATE USER, RELOAD
      ON *.* TO 'svqpanel_admin'@'localhost' WITH GRANT OPTION;
FLUSH PRIVILEGES;
MARIADBEOF

    echo -e "  ${GREEN}✓ MariaDB asegurado y usuario del panel creado${NC}"

    # ── Guardar credenciales ──────────────────────────────────────────────────
    mkdir -p /opt/svqpanel/.credentials
    cat > /opt/svqpanel/.credentials/mariadb.txt << MDBCREDEOF
# Credenciales MariaDB — NO compartir
MariaDB root:          root / ${MARIADB_ROOT_PASS}
Panel admin (svqpanel_admin): ${MARIADB_PANEL_PASS}
MDBCREDEOF
    chmod 600 /opt/svqpanel/.credentials/mariadb.txt

    # ── Verificar servicio ────────────────────────────────────────────────────
    if systemctl is-active --quiet mariadb; then
        echo -e "${GREEN}✓ MariaDB activo y listo para clientes${NC}\n"
    else
        echo -e "${RED}✗ MariaDB NO activo (revisar: journalctl -u mariadb)${NC}\n"
    fi

    # ── Instalar phpMyAdmin con autologin ─────────────────────────────────────
    echo -e "${YELLOW}Instalando phpMyAdmin...${NC}"
    PMA_VERSION="5.2.2"
    PMA_DIR="/var/www/pma"
    PMA_DL="https://files.phpmyadmin.net/phpMyAdmin/${PMA_VERSION}/phpMyAdmin-${PMA_VERSION}-all-languages.tar.gz"
    PMA_TMP="/tmp/phpmyadmin.tar.gz"

    apt-get install -y php-mbstring php-xml php-curl php-zip > /dev/null 2>&1

    curl -Lo "$PMA_TMP" "$PMA_DL" 2>/dev/null || wget -qO "$PMA_TMP" "$PMA_DL"
    if [[ -f "$PMA_TMP" && -s "$PMA_TMP" ]]; then
        rm -rf "${PMA_DIR:?}"
        mkdir -p "$PMA_DIR"
        tar xzf "$PMA_TMP" -C "$PMA_DIR" --strip-components=1
        rm -f "$PMA_TMP"
        chown -R www-data:www-data "$PMA_DIR"
        chmod -R 755 "$PMA_DIR"
        mkdir -p /tmp/phpmyadmin && chmod 777 /tmp/phpmyadmin
        mkdir -p /tmp/pma_tokens && chmod 711 /tmp/pma_tokens

        # Generar clave Fernet (se añade al .env más abajo, en sección env)
        PANEL_ENCRYPTION_KEY=$(python3 -c \
            "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

        PMA_BLOWFISH_SECRET=$(python3 -c \
            "import secrets, string; \
             chars = string.ascii_letters + string.digits; \
             print(''.join(secrets.choice(chars) for _ in range(56)))")

        PMA_CONTROL_PASS=$(python3 -c \
            "import secrets, string; \
             chars = string.ascii_letters + string.digits; \
             print(''.join(secrets.choice(chars) for _ in range(24)))")

        # ── BD phpmyadmin + usuario pma (controluser) ─────────────────────────
        mariadb --user=root << PMADBEOF
CREATE DATABASE IF NOT EXISTS phpmyadmin CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
DROP USER IF EXISTS 'pma'@'localhost';
CREATE USER 'pma'@'localhost' IDENTIFIED BY '${PMA_CONTROL_PASS}';
GRANT SELECT, INSERT, UPDATE, DELETE ON phpmyadmin.* TO 'pma'@'localhost';
FLUSH PRIVILEGES;
PMADBEOF
        mariadb --user=root phpmyadmin < "${PMA_DIR}/sql/create_tables.sql"
        echo -e "  ${GREEN}✓ BD phpmyadmin y usuario pma creados${NC}"

        cat > "${PMA_DIR}/config.inc.php" << PMACFGEOF
<?php
\$cfg['blowfish_secret'] = '${PMA_BLOWFISH_SECRET}';
\$i = 0; \$i++;
\$cfg['Servers'][\$i]['host']          = '127.0.0.1';
\$cfg['Servers'][\$i]['port']          = '3306';
\$cfg['Servers'][\$i]['compress']      = false;
\$cfg['Servers'][\$i]['auth_type']     = 'signon';
\$cfg['Servers'][\$i]['SignonSession'] = 'SignonSession';
\$cfg['Servers'][\$i]['SignonURL']     = '/pma/signon.php';
\$cfg['Servers'][\$i]['LogoutURL']     = '/databases';
\$cfg['Servers'][\$i]['AllowRoot']     = false;

// Almacenamiento de configuración (elimina el aviso de funciones extendidas)
\$cfg['Servers'][\$i]['controlhost']        = '127.0.0.1';
\$cfg['Servers'][\$i]['controlport']        = '3306';
\$cfg['Servers'][\$i]['controluser']        = 'pma';
\$cfg['Servers'][\$i]['controlpass']        = '${PMA_CONTROL_PASS}';
\$cfg['Servers'][\$i]['pmadb']             = 'phpmyadmin';
\$cfg['Servers'][\$i]['bookmarktable']     = 'pma__bookmark';
\$cfg['Servers'][\$i]['relation']          = 'pma__relation';
\$cfg['Servers'][\$i]['table_info']        = 'pma__table_info';
\$cfg['Servers'][\$i]['table_coords']      = 'pma__table_coords';
\$cfg['Servers'][\$i]['pdf_pages']         = 'pma__pdf_pages';
\$cfg['Servers'][\$i]['column_info']       = 'pma__column_info';
\$cfg['Servers'][\$i]['history']           = 'pma__history';
\$cfg['Servers'][\$i]['table_uiprefs']     = 'pma__table_uiprefs';
\$cfg['Servers'][\$i]['tracking']          = 'pma__tracking';
\$cfg['Servers'][\$i]['userconfig']        = 'pma__userconfig';
\$cfg['Servers'][\$i]['recent']            = 'pma__recent';
\$cfg['Servers'][\$i]['favorite']          = 'pma__favorite';
\$cfg['Servers'][\$i]['users']             = 'pma__users';
\$cfg['Servers'][\$i]['usergroups']        = 'pma__usergroups';
\$cfg['Servers'][\$i]['navigationhide']    = 'pma__navigationhide';
\$cfg['Servers'][\$i]['savedsearches']     = 'pma__savedsearches';
\$cfg['Servers'][\$i]['central_columns']   = 'pma__central_columns';
\$cfg['Servers'][\$i]['designer_settings'] = 'pma__designer_settings';
\$cfg['Servers'][\$i]['export_templates']  = 'pma__export_templates';

// Directorios
\$cfg['TempDir']   = '/tmp/phpmyadmin/';
\$cfg['UploadDir'] = '';
\$cfg['SaveDir']   = '';

// UI
\$cfg['ServerDefault']       = 1;
\$cfg['LoginCookieValidity'] = 1440;
\$cfg['SendErrorReports']    = 'never';
\$cfg['CheckConfigurationPermissions'] = false;
PMACFGEOF
        chmod 640 "${PMA_DIR}/config.inc.php"
        chown root:www-data "${PMA_DIR}/config.inc.php"

        cat > "${PMA_DIR}/signon.php" << 'SIGNONEOF'
<?php
$token = isset($_GET['token']) ? preg_replace('/[^a-f0-9]/', '', $_GET['token']) : '';
if (empty($token)) { header('Location: /'); exit; }
$token_file = '/tmp/pma_tokens/' . $token . '.json';
if (!file_exists($token_file)) { http_response_code(403); die('<p>Token inválido o expirado. <a href="/">Volver al panel</a></p>'); }
$data = json_decode(file_get_contents($token_file), true);
@unlink($token_file);
if (!$data || !isset($data['exp']) || time() > $data['exp']) { http_response_code(403); die('<p>Token expirado. <a href="/databases">Volver al panel</a></p>'); }
session_name('SignonSession');
session_start();
$_SESSION['PMA_single_signon_user']     = $data['user'];
$_SESSION['PMA_single_signon_password'] = $data['password'];
$_SESSION['PMA_single_signon_host']     = '127.0.0.1';
$_SESSION['PMA_single_signon_port']     = '';
session_write_close();
header('Location: /pma/index.php');
exit;
SIGNONEOF
        chmod 644 "${PMA_DIR}/signon.php"
        chown www-data:www-data "${PMA_DIR}/signon.php"
        echo -e "  ${GREEN}✓ phpMyAdmin ${PMA_VERSION} instalado en $PMA_DIR${NC}"
    else
        echo -e "  ${YELLOW}⚠ No se pudo descargar phpMyAdmin — instálalo manualmente${NC}"
        PANEL_ENCRYPTION_KEY=""
    fi
fi

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
from api.models.models_mail import MailDomain, Mailbox, MailAlias
from api.models.models_client_db import ClientDatabase
from api.models.models_security import (
    FirewallRule, BannedIp, IpList, SecurityAuditLog,
)

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

# MARIADB_ENABLED depende de si se seleccionó instalar MariaDB
MARIADB_ENABLED_VAL="false"
if [[ "$INSTALL_MARIADB" == true ]]; then
    MARIADB_ENABLED_VAL="true"
fi

# ROUNDCUBE_ENABLED / ROUNDCUBE_URL
ROUNDCUBE_ENABLED_VAL="false"
ROUNDCUBE_URL_VAL="/webmail"
if [[ "$INSTALL_ROUNDCUBE" == true ]]; then
    ROUNDCUBE_ENABLED_VAL="true"
fi

# SECRET_KEY aleatorio para JWT
SECRET_KEY_VAL=$(python3 -c \
    "import secrets; print(secrets.token_hex(32))")

cat > /opt/svqpanel/.env << ENVEOF
# SVQPanel Configuration
DATABASE_URL=postgresql://panel_user:panel_password_123@localhost/panel_db
PANEL_NAME=SVQPanel
PANEL_VERSION=0.1.0
PANEL_HOST=0.0.0.0
PANEL_PORT=8001
DEBUG=False
SECRET_KEY=${SECRET_KEY_VAL}

# Servidor de correo (Postfix + Dovecot + Rspamd)
MAIL_ENABLED=${MAIL_ENABLED_VAL}

# MariaDB — bases de datos para clientes
MARIADB_ENABLED=${MARIADB_ENABLED_VAL}
MARIADB_HOST=localhost
MARIADB_PANEL_USER=svqpanel_admin
MARIADB_PANEL_PASSWORD=${MARIADB_PANEL_PASS}
PANEL_ENCRYPTION_KEY=${PANEL_ENCRYPTION_KEY}

# Administrador de archivos integrado
FILE_MANAGER_ENABLED=true
FILE_MANAGER_MAX_UPLOAD_MB=100
FILE_MANAGER_MAX_TEXT_FILE_MB=2

# Roundcube Webmail (autologin desde el panel)
ROUNDCUBE_ENABLED=${ROUNDCUBE_ENABLED_VAL}
ROUNDCUBE_URL=${ROUNDCUBE_URL_VAL}
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
    # default_server: garantiza que el panel atienda peticiones por IP o
    # hostnames no configurados. Sin esto, cuando se anaden dominios de
    # clientes (que alfabeticamente vengan antes que 'svqpanel' en
    # sites-enabled), uno de ellos roba el rol de default y el panel
    # deja de responder a la IP del servidor.
    listen 80 default_server;
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

    # Autoconfig — Thunderbird y clientes Mozilla
    location /.well-known/autoconfig/ {
        proxy_pass http://svqpanel_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Autodiscover — Outlook y clientes Microsoft
    location /autodiscover/ {
        proxy_pass http://svqpanel_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    location /Autodiscover/ {
        proxy_pass http://svqpanel_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Rspamd web UI
    location /rspamd/ {
        proxy_pass http://127.0.0.1:11334/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # Frontend → servir archivos estáticos, fallback a index.html (SPA)
    location / {
        try_files $uri $uri/ /index.html;
    }
}
NGINXEOF

    # ── phpMyAdmin: inyectar bloque /pma si se instaló ───────────────────────
    if [[ "$INSTALL_MARIADB" == true && -d /var/www/pma ]]; then
        PHP_FPM_SOCK=$(find /run/php /var/run/php -name 'php*-fpm.sock' 2>/dev/null \
                       | sort -rV | head -1)
        if [[ -n "$PHP_FPM_SOCK" ]]; then
            python3 - << PYEOF
sock = "${PHP_FPM_SOCK}"
pma_block = (
    "\n"
    "    # phpMyAdmin — acceso autenticado via panel SVQPanel\n"
    "    location /pma/ {\n"
    "        root /var/www;\n"
    "        index index.php index.html;\n"
    "        location ~ \\.php$ {\n"
    "            include snippets/fastcgi-php.conf;\n"
    "            fastcgi_pass unix:" + sock + ";\n"
    "            fastcgi_param SCRIPT_FILENAME \$document_root\$fastcgi_script_name;\n"
    "            include fastcgi_params;\n"
    "        }\n"
    "    }\n"
    "\n"
)
with open('/etc/nginx/sites-available/svqpanel', 'r') as f:
    content = f.read()
marker = '    location / {'
if marker in content and 'location /pma' not in content:
    content = content.replace(marker, pma_block + marker)
    with open('/etc/nginx/sites-available/svqpanel', 'w') as f:
        f.write(content)
PYEOF
            echo -e "  ${GREEN}✓ Bloque phpMyAdmin añadido a nginx${NC}"
        else
            echo -e "  ${YELLOW}⚠ No se encontró PHP-FPM socket; configura nginx para /pma manualmente${NC}"
        fi
    fi

    # ── Roundcube: inyectar bloque /webmail/ si se instaló ───────────────────
    if [[ "$INSTALL_ROUNDCUBE" == true && -L /var/www/webmail ]]; then
        PHP_FPM_SOCK_RC=$(find /run/php /var/run/php -name 'php*-fpm.sock' 2>/dev/null \
                          | sort -rV | head -1)
        if [[ -n "$PHP_FPM_SOCK_RC" ]]; then
            python3 - << RCPYEOF
sock = "${PHP_FPM_SOCK_RC}"
rc_block = (
    "\n"
    "    # Roundcube Webmail — autologin desde SVQPanel\n"
    "    location /webmail {\n"
    "        return 301 /webmail/;\n"
    "    }\n"
    "    location /webmail/ {\n"
    "        root /var/www/roundcube/public_html;\n"
    "        index index.php;\n"
    "        # Roundcube 1.7.0+: assets servidos por static.php con PATH_INFO\n"
    "        location ~ ^/webmail/static\\.php {\n"
    "            fastcgi_split_path_info ^(/webmail/static\\.php)(/.+)\$;\n"
    "            fastcgi_pass unix:" + sock + ";\n"
    "            include fastcgi_params;\n"
    "            fastcgi_param SCRIPT_FILENAME /var/www/roundcube/public_html/static.php;\n"
    "            fastcgi_param PATH_INFO \$fastcgi_path_info;\n"
    "            fastcgi_param SCRIPT_NAME /webmail/static.php;\n"
    "        }\n"
    "        location ~ \\.php\$ {\n"
    "            include snippets/fastcgi-php.conf;\n"
    "            fastcgi_pass unix:" + sock + ";\n"
    "            fastcgi_param SCRIPT_FILENAME \$document_root\$fastcgi_script_name;\n"
    "            include fastcgi_params;\n"
    "        }\n"
    "        location ~ ^/webmail/(config|logs|temp|vendor/bin)/ {\n"
    "            deny all;\n"
    "        }\n"
    "    }\n"
    "\n"
)
with open('/etc/nginx/sites-available/svqpanel', 'r') as f:
    content = f.read()
marker = '    location / {'
if marker in content and 'location /webmail' not in content:
    content = content.replace(marker, rc_block + marker)
    with open('/etc/nginx/sites-available/svqpanel', 'w') as f:
        f.write(content)
RCPYEOF
            echo -e "  ${GREEN}✓ Bloque Roundcube /webmail/ añadido a nginx${NC}"
        else
            echo -e "  ${YELLOW}⚠ No se encontró PHP-FPM socket; configura nginx para /webmail manualmente${NC}"
        fi
    fi

    ln -sf /etc/nginx/sites-available/svqpanel /etc/nginx/sites-enabled/svqpanel
    rm -f /etc/nginx/sites-enabled/default
    nginx -t && systemctl restart nginx

    echo -e "${GREEN}✓ Nginx configurado${NC}\n"
fi

###############################################################################
# 12B. SEGURIDAD: nftables (firewall) + fail2ban   (Fase 12)
#
# Diseño:
#   - Tabla nftables propia 'inet svqpanel' aislada del sistema, evita pisar
#     reglas existentes del admin. Si algo va mal, se borra entera.
#   - Política por defecto ACCEPT en la chain del panel; el panel solo AÑADE
#     reglas de deny/block desde la UI. Así la instalación nunca bloquea.
#   - Auto-whitelist de la IP desde la que se está ejecutando el instalador
#     (típicamente la sesión SSH) → cuando el admin active modo restrictivo
#     desde la UI, su IP ya estará protegida.
#   - fail2ban ignoreip incluye 127.0.0.1, ::1 y la IP del instalador.
###############################################################################
echo -e "${YELLOW}Instalando nftables + fail2ban...${NC}"

apt-get install -y -qq nftables fail2ban

# Detectar IP origen de la sesión SSH (el que ejecuta el instalador)
INSTALLER_IP=""
if [[ -n "$SSH_CLIENT" ]]; then
    INSTALLER_IP="$(echo "$SSH_CLIENT" | awk '{print $1}')"
elif [[ -n "$SSH_CONNECTION" ]]; then
    INSTALLER_IP="$(echo "$SSH_CONNECTION" | awk '{print $1}')"
fi
if [[ -z "$INSTALLER_IP" ]]; then
    echo -e "  ${YELLOW}⚠ No se detectó SSH_CLIENT; sin auto-whitelist de IP origen${NC}"
else
    echo -e "  ${GREEN}✓ IP del instalador detectada: $INSTALLER_IP (se añadirá a whitelist)${NC}"
fi

# Plantar nftables.conf con table 'inet svqpanel' aislada
cat > /etc/nftables.conf << 'NFTEOF'
#!/usr/sbin/nft -f
# /etc/nftables.conf — gestionado por SVQPanel (Fase 12)
# La tabla 'inet svqpanel' contiene todo lo que gestiona el panel.
# NO edites a mano salvo emergencia; el panel regenera este archivo.

flush ruleset

table inet svqpanel {
    # Named sets — los rellena el panel y/o fail2ban
    set whitelist_v4 { type ipv4_addr; flags interval; }
    set whitelist_v6 { type ipv6_addr; flags interval; }
    set f2b_v4 { type ipv4_addr; flags timeout; }
    set f2b_v6 { type ipv6_addr; flags timeout; }

    chain input {
        type filter hook input priority filter; policy accept;

        # Tráfico local y conexiones ya establecidas
        iif "lo" accept
        ct state { established, related } accept
        ct state invalid drop

        # ICMP básico
        ip  protocol icmp icmp type { echo-request, destination-unreachable, time-exceeded, parameter-problem } accept
        ip6 nexthdr  icmpv6 icmpv6 type { echo-request, destination-unreachable, packet-too-big, time-exceeded, parameter-problem, nd-router-solicit, nd-router-advert, nd-neighbor-solicit, nd-neighbor-advert } accept

        # Whitelist con prioridad máxima
        ip  saddr @whitelist_v4 accept
        ip6 saddr @whitelist_v6 accept

        # Bans dinámicos de fail2ban
        ip  saddr @f2b_v4 drop
        ip6 saddr @f2b_v6 drop
    }
}

# Includes gestionados por el panel (pueden estar vacíos al inicio)
include "/etc/nftables/svqpanel-iplists.nft"
include "/etc/nftables/svqpanel-rules.nft"
NFTEOF

# Crear los includes vacíos
mkdir -p /etc/nftables
: > /etc/nftables/svqpanel-iplists.nft
: > /etc/nftables/svqpanel-rules.nft

# Inyectar la IP del instalador en svqpanel-rules.nft para que persista a reboots
if [[ -n "$INSTALLER_IP" ]]; then
    if [[ "$INSTALLER_IP" =~ : ]]; then
        SET="whitelist_v6"
    else
        SET="whitelist_v4"
    fi
    cat > /etc/nftables/svqpanel-rules.nft << SVQRULESEOF
# Generado por install.sh — auto-whitelist del IP del instalador
add element inet svqpanel $SET { $INSTALLER_IP }
SVQRULESEOF
fi

systemctl enable nftables >/dev/null 2>&1 || true
nft -f /etc/nftables.conf
systemctl restart nftables >/dev/null 2>&1 || systemctl start nftables

echo -e "${GREEN}✓ nftables: tabla 'inet svqpanel' activa (política ACCEPT)${NC}"

# ─── fail2ban ────────────────────────────────────────────────────────────────
IGNOREIP="127.0.0.1/8 ::1"
if [[ -n "$INSTALLER_IP" ]]; then
    IGNOREIP="$IGNOREIP $INSTALLER_IP"
fi

# jail.local condicional según servicios instalados
MAIL_JAILS_ENABLED="false"
if [[ "$INSTALL_MAIL" == true ]]; then
    MAIL_JAILS_ENABLED="true"
fi

cat > /etc/fail2ban/jail.local << F2BEOF
# /etc/fail2ban/jail.local — gestionado por SVQPanel (Fase 12)
# Cualquier cambio desde el panel puede sobrescribir este archivo.

[DEFAULT]
bantime  = 1h
findtime = 10m
maxretry = 5
backend  = systemd
banaction = nftables-multiport
banaction_allports = nftables-allports
ignoreip = $IGNOREIP

[sshd]
enabled  = true
port     = ssh
filter   = sshd
maxretry = 5

[svqpanel-auth]
enabled  = true
# El panel escribe a este log las lineas 'auth_failed ip=X user=Y reason=Z'
# desde Fase 12.6 (api/utils/auth_log.py). backend=auto (=inotify) en lugar
# del 'systemd' del DEFAULT porque queremos vigilar un fichero, no el journal.
port     = http,https,8001
filter   = svqpanel-auth
logpath  = /opt/svqpanel/logs/auth.log
backend  = auto
maxretry = 5

[dovecot]
enabled  = $MAIL_JAILS_ENABLED
port     = pop3,pop3s,imap,imaps,submission,sieve
filter   = dovecot
maxretry = 5

[postfix-sasl]
enabled  = $MAIL_JAILS_ENABLED
port     = smtp,465,submission,imap,imaps,pop3,pop3s
filter   = postfix-sasl
maxretry = 5

[nginx-limit-req]
enabled  = false
port     = http,https
filter   = nginx-limit-req
maxretry = 10

[recidive]
enabled  = true
filter   = recidive
logpath  = /var/log/fail2ban.log
backend  = auto
bantime  = 1w
findtime = 1d
maxretry = 3
F2BEOF

# Filtro custom para fallos de login del panel
cat > /etc/fail2ban/filter.d/svqpanel-auth.conf << 'F2BFILTEREOF'
# fail2ban filter for SVQPanel login failures
# Espera líneas tipo: "auth_failed ip=1.2.3.4 user=admin"
[Definition]
failregex = ^.* auth_failed ip=<HOST>.*$
ignoreregex =
F2BFILTEREOF

# Asegurar que existe el log que vigila [svqpanel-auth]; si no fail2ban
# da error de "logpath not found" al iniciar el jail
mkdir -p /opt/svqpanel/logs
touch /opt/svqpanel/logs/auth.log

# logrotate para que auth.log no crezca sin freno
cat > /etc/logrotate.d/svqpanel << 'LRTEOF'
/opt/svqpanel/logs/auth.log {
    weekly
    rotate 8
    compress
    delaycompress
    notifempty
    missingok
    create 0644 root root
    postrotate
        fail2ban-client reload svqpanel-auth >/dev/null 2>&1 || true
    endscript
}
LRTEOF

systemctl enable fail2ban >/dev/null 2>&1 || true
systemctl restart fail2ban >/dev/null 2>&1 || systemctl start fail2ban

echo -e "${GREEN}✓ fail2ban: jails activas (sshd, recidive, svqpanel-auth$( [[ "$INSTALL_MAIL" == true ]] && echo ', dovecot, postfix-sasl' ))${NC}"
if [[ -n "$INSTALLER_IP" ]]; then
    echo -e "  ${GREEN}✓ Anti-lockout: $INSTALLER_IP en whitelist nftables + ignoreip fail2ban${NC}"
fi

# ─── Systemd timer para refresco diario de IP lists ──────────────────────────
cat > /etc/systemd/system/svqpanel-iplist-refresh.service << 'IPLRSEOF'
[Unit]
Description=SVQPanel — refresca listas IP desde URLs externas
After=network-online.target nftables.service
Wants=network-online.target

[Service]
Type=oneshot
User=root
WorkingDirectory=/opt/svqpanel
ExecStart=/opt/svqpanel/venv/bin/python -m api.cli refresh_ip_lists
TimeoutStartSec=600

[Install]
WantedBy=multi-user.target
IPLRSEOF

cat > /etc/systemd/system/svqpanel-iplist-refresh.timer << 'IPLRTEOF'
[Unit]
Description=SVQPanel — timer diario para refrescar listas IP

[Timer]
OnCalendar=daily
RandomizedDelaySec=2h
Persistent=true
Unit=svqpanel-iplist-refresh.service

[Install]
WantedBy=timers.target
IPLRTEOF

systemctl daemon-reload
systemctl enable --now svqpanel-iplist-refresh.timer >/dev/null 2>&1 || true

echo -e "${GREEN}✓ systemd timer: svqpanel-iplist-refresh.timer (refresco diario)${NC}"
echo ""

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

# Crear usuario del SISTEMA 'admin' además del usuario del panel.
# Si el admin del panel intenta alojar dominios (chown user:www-data ...) y
# no existe en /etc/passwd, falla. Hestia hace lo mismo: el admin tiene
# cuenta de sistema desde el primer momento.
if ! id admin >/dev/null 2>&1; then
    useradd -m -s /bin/bash -d /home/admin admin
    echo "admin:$ADMIN_PASSWORD" | chpasswd
    # Estructura web estilo Hestia (igual que UserManager.create_user)
    mkdir -p /home/admin/web
    chown admin:www-data /home/admin/web
    chmod 750 /home/admin/web
    mkdir -p /home/admin/tmp
    chown admin:admin /home/admin/tmp
    chmod 750 /home/admin/tmp
    echo -e "  ${GREEN}✓ Usuario del sistema 'admin' creado${NC}"
else
    echo -e "  ${YELLOW}⚠ Usuario del sistema 'admin' ya existía, no se recrea${NC}"
fi

# Crear usuario admin en la BD (pasar contraseña via variable de entorno)
SVQPANEL_ADMIN_PASS="$ADMIN_PASSWORD" python3 << 'PYTHONEOF'
import sys
import os
sys.path.insert(0, '/opt/svqpanel')

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from api.models.models_user import User
from api.models.models_domain import Domain
from api.models.models_dns import DnsZone, DnsRecord
from api.models.models_mail import MailDomain, Mailbox, MailAlias
from api.models.models_client_db import ClientDatabase

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
echo "  Roundcube:    $( [[ "$INSTALL_ROUNDCUBE" == true ]] && echo 'Instalado — /webmail' || echo 'No instalado' )"
echo "  MariaDB:      $( [[ "$INSTALL_MARIADB" == true ]] && echo 'MariaDB 11.4 LTS (bases de datos de clientes)' || echo 'No instalado' )"
echo "  Seguridad:    nftables (table inet svqpanel) + fail2ban"
echo "  Directorio:   /opt/svqpanel"
echo "  Base de datos panel: panel_db (PostgreSQL)"
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
echo "  • Panel Web:    http://IP_DEL_SERVIDOR"
echo "  • Seguridad:    http://IP_DEL_SERVIDOR/security  (firewall, fail2ban, listas IP)"
echo "  • API:          http://IP_DEL_SERVIDOR:8001"
echo "  • API Docs:     http://IP_DEL_SERVIDOR:8001/docs"
echo -e "\n${YELLOW}Base de datos:${NC}"
echo "  • Host: localhost"
echo "  • User: panel_user"
echo "  • Password: panel_password_123"
echo "  • Database: panel_db"
echo -e "\n${YELLOW}Archivos importantes:${NC}"
echo "  • Configuración:        /opt/svqpanel/.env"
echo "  • Credenciales admin:   /opt/svqpanel/.credentials/admin.txt"
if [[ "$INSTALL_MARIADB" == true ]]; then
    echo "  • Credenciales MariaDB: /opt/svqpanel/.credentials/mariadb.txt"
fi
if [[ "$INSTALL_MARIADB" == true ]]; then
    echo -e "\n${YELLOW}MariaDB (bases de datos de clientes):${NC}"
    echo "  • Host:       localhost:3306"
    echo "  • Panel user: svqpanel_admin"
    echo "  • API:        POST /api/databases  → crear BD de cliente"
    echo "  • Credenciales completas: /opt/svqpanel/.credentials/mariadb.txt"
fi
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
if [[ "$INSTALL_ROUNDCUBE" == true ]]; then
    echo -e "\n${YELLOW}Roundcube Webmail:${NC}"
    echo "  • URL:           http://IP_DEL_SERVIDOR/webmail/"
    echo "  • Autologin:     botón ✉ junto a cada buzón en el panel"
    echo "  • Plugin:        svqpanel_autologin (instalado automáticamente)"
    echo "  • Credenciales:  /opt/svqpanel/.credentials/roundcube.txt"
fi

echo -e "\n${YELLOW}Seguridad (Fase 12):${NC}"
echo "  • UI:                  http://IP_DEL_SERVIDOR/security"
echo "  • Firewall:            nftables (tabla 'inet svqpanel')"
echo "                         /etc/nftables.conf + /etc/nftables/svqpanel-*.nft"
echo "  • Brute-force:         fail2ban (sshd, recidive y más con correo)"
echo "                         /etc/fail2ban/jail.local"
echo "  • Listas IP (URL):     refresh diario via systemd timer"
echo "                         systemctl list-timers svqpanel-iplist-refresh.timer"
if [[ -n "$INSTALLER_IP" ]]; then
    echo "  • Anti-lockout:        $INSTALLER_IP ya está en whitelist y en ignoreip"
fi

echo -e "\n${RED}⚠ IMPORTANTE:${NC}"
echo "  • Las credenciales se guardaron en: /opt/svqpanel/.credentials/admin.txt"
echo "  • Cambia la contraseña después de la primera sesión"
echo "  • Cambia las credenciales de BD en .env antes de ir a producción"
echo "  • Asegúrate de usar HTTPS en producción"
if [[ "$INSTALL_MAIL" == true ]]; then
    echo "  • Correo: sustituye el certificado snakeoil por uno real (Let's Encrypt)"
fi
if [[ "$INSTALL_ROUNDCUBE" == true ]]; then
    echo "  • Roundcube: los tokens de autologin caducan en 60 segundos (uso único)"
fi
