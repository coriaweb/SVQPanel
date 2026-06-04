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

OS_VERSION=$(grep -oP '(?<=^VERSION_ID=")[^"]+' /etc/os-release)
OS_NAME=$(grep -oP '(?<=^ID=)[^\n]+' /etc/os-release | tr -d '"')

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
printf "Elige (1 o 2): "; read WEBSERVER_CHOICE </dev/tty

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

# Guardar la opción de webserver para que los scripts de Python la puedan leer
mkdir -p /etc/svqpanel
echo "$WEBSERVER" > /etc/svqpanel/webserver.conf
chmod 644 /etc/svqpanel/webserver.conf

###############################################################################
# 1b. PUERTO DEL PANEL
###############################################################################
# El panel se sirve en un puerto dedicado (no 80/443) para poder cerrarlo
# selectivamente en el firewall perimetral (Proxmox, etc.) y dejar 80/443
# libres para los sitios web de los clientes.
echo -e "${YELLOW}¿En qué puerto quieres servir el panel de control?${NC}"
echo "  Recomendado: 8083 (cierra solo este puerto en tu firewall para máxima seguridad)"
printf "Puerto del panel [8083]: "; read _PANEL_PORT_INPUT </dev/tty
PANEL_WEB_PORT="${_PANEL_PORT_INPUT:-8083}"
# Validar: número 1-65535 y no chocar con puertos comunes de servicios
if ! [[ "$PANEL_WEB_PORT" =~ ^[0-9]+$ ]] || (( PANEL_WEB_PORT < 1 || PANEL_WEB_PORT > 65535 )); then
    echo -e "${RED}Puerto inválido: $PANEL_WEB_PORT${NC}"; exit 1
fi
for _busy in 80 443 22 25 143 993 110 995 587 465 3306 5432 8001; do
    if (( PANEL_WEB_PORT == _busy )); then
        echo -e "${RED}El puerto $PANEL_WEB_PORT está reservado para otro servicio. Elige otro (p.ej. 8083).${NC}"
        exit 1
    fi
done
echo -e "${GREEN}✓ El panel se servirá en el puerto $PANEL_WEB_PORT${NC}\n"

###############################################################################
# 2b. SERVIDOR DE CORREO (OPCIONAL)
###############################################################################
echo -e "${YELLOW}¿Instalar servidor de correo electrónico?${NC}"
echo "  Stack: Postfix (SMTP) + Dovecot (IMAP/POP3) + Rspamd (antispam/DKIM) + Redis"
echo -e "  ${YELLOW}Requisitos: IP con rDNS configurado, puerto 25 desbloqueado, registro MX${NC}"
printf "¿Instalar correo? (s/N): "; read _MAIL_INPUT </dev/tty
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
    printf "¿Instalar Roundcube? (s/N): "; read _RC_INPUT </dev/tty
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
printf "¿Instalar MariaDB? (s/N): "; read _MARIADB_INPUT </dev/tty
INSTALL_MARIADB=false
if [[ "${_MARIADB_INPUT,,}" =~ ^(s|si|y|yes)$ ]]; then
    INSTALL_MARIADB=true
    echo -e "${GREEN}✓ MariaDB seleccionado${NC}\n"
else
    echo -e "${YELLOW}✗ Sin MariaDB para clientes${NC}\n"
fi

###############################################################################
# 2d. CROWDSEC (IPS colaborativo) — recomendado
###############################################################################
echo -e "${YELLOW}¿Instalar CrowdSec?${NC} ${GREEN}(recomendado)${NC}"
echo "  IPS colaborativo: detecta ataques desde logs (sshd, nginx, postfix...)"
echo "  y aplica bans via bouncer de nftables. Complementa a fail2ban con una"
echo "  blocklist comunitaria opcional. Footprint: ~80 MB RAM."
printf "¿Instalar CrowdSec? (S/n): "; read _CS_INPUT </dev/tty
INSTALL_CROWDSEC=true
if [[ "${_CS_INPUT,,}" =~ ^(n|no)$ ]]; then
    INSTALL_CROWDSEC=false
    echo -e "${YELLOW}✗ Sin CrowdSec${NC}\n"
else
    echo -e "${GREEN}✓ CrowdSec seleccionado${NC}\n"
fi

###############################################################################
# 2. ELEGIR VERSIONES PHP
###############################################################################
echo -e "${YELLOW}¿Qué versiones PHP necesitas?${NC}"
echo "Disponibles: 7.4, 8.0, 8.1, 8.2, 8.3, 8.4, 8.5"
echo "Ejemplos: '8.1 8.2' o '8.5' (mínimo 1, máximo 6)"
printf "Versiones PHP (separadas por espacio): "; read PHP_VERSIONS </dev/tty

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
    echo -e "${YELLOW}Solo están disponibles: 7.4, 8.0, 8.1, 8.2, 8.3, 8.4, 8.5${NC}"
    exit 1
fi

echo -e "${GREEN}✓ PHP versions: ${PHP_ARRAY[*]}${NC}\n"

###############################################################################
# 3. ACTUALIZAR SISTEMA
###############################################################################
export DEBIAN_FRONTEND=noninteractive
echo -e "${YELLOW}Actualizando sistema...${NC}"
apt-get update -qq
apt-get upgrade -y -qq -o Dpkg::Options::="--force-confold"
echo -e "${GREEN}✓ Sistema actualizado${NC}\n"

###############################################################################
# 3b. SWAP — crear si no existe (evita OOM killer en VPS con poca RAM)
###############################################################################
if ! swapon --show | grep -q '/'; then
    echo -e "${YELLOW}Creando archivo de swap (2 GB)...${NC}"
    fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
    chmod 600 /swapfile
    mkswap /swapfile -q
    swapon /swapfile
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    # Usar swap solo cuando RAM > 90% ocupada (menor latencia en producción)
    grep -q 'vm.swappiness' /etc/sysctl.conf || echo 'vm.swappiness=10' >> /etc/sysctl.conf
    sysctl -p > /dev/null 2>&1
    echo -e "${GREEN}✓ Swap de 2 GB creado y activado${NC}\n"
else
    echo -e "${GREEN}✓ Swap ya existe, no se recrea${NC}\n"
fi

###############################################################################
# 4. INSTALAR DEPENDENCIAS BASE
###############################################################################
echo -e "${YELLOW}Instalando dependencias base...${NC}"

apt-get install -y -qq -o Dpkg::Options::="--force-confold" \
    curl \
    wget \
    git \
    openssh-client \
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
    acl \
    sshpass \
    dnsutils \
    openssl \
    libssl-dev \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    postgresql \
    postgresql-contrib \
    postgresql-server-dev-all \
    snapd \
    rsyslog \
    rsync \
    zstd \
    mailutils

echo -e "${GREEN}✓ Dependencias instaladas${NC}\n"

###############################################################################
# 4b. INSTALAR CERTBOT (vía snap — versión oficial siempre actualizada)
###############################################################################
# El certbot de Debian apt está MUY desactualizado (2.1.x) y SUFRE un bug con
# Python 3.11: "AttributeError: can't set attribute" al pedir CUALQUIER cert
# (josepy 1.13 + acme 2.1.0) → rompía TODO el SSL. El método recomendado por
# EFF/Let's Encrypt es snap (5.x). Lo instalamos de forma robusta: saltarse
# cualquier paso (snapd, seed, core) deja certbot a medias.
echo -e "${YELLOW}Instalando Certbot vía snap...${NC}"
# snapd instalado y activo (no asumir que ya está)
apt-get install -y -qq snapd 2>/dev/null || true
systemctl enable --now snapd.socket 2>/dev/null || true
# Esperar a que snapd inicialice (seed) — si no, los snap install fallan
snap wait system seed.loaded 2>/dev/null || true
snap install core 2>/dev/null || true
snap refresh core 2>/dev/null || true
# Eliminar versión apt si existía (saca el bug del PATH)
apt-get remove -y -qq certbot python3-certbot-nginx 2>/dev/null || true
# Instalar certbot snap
snap install --classic certbot 2>/dev/null || true
# Permitir que los plugins (nginx, dns) corran con root
snap set certbot trust-plugin-with-root=ok 2>/dev/null || true
# Symlink para que esté en PATH
ln -sf /snap/bin/certbot /usr/bin/certbot 2>/dev/null || true
hash -r 2>/dev/null || true
echo -e "${GREEN}✓ Certbot $(certbot --version 2>&1) instalado${NC}\n"

###############################################################################
# 5. INSTALAR NODEJS 24 LTS (desde NodeSource — repo oficial)
###############################################################################
echo -e "${YELLOW}Instalando Node.js 24 LTS...${NC}"
curl -fsSL https://deb.nodesource.com/setup_24.x | bash - > /dev/null 2>&1
apt-get install -y -qq nodejs
echo -e "${GREEN}✓ Node.js $(node -v) instalado${NC}\n"

###############################################################################
# 6. INSTALAR WEBSERVER
###############################################################################
if [[ "$WEBSERVER" == "nginx" || "$WEBSERVER" == "apache+nginx" ]]; then
    echo -e "${YELLOW}Instalando Nginx (repo oficial nginx.org — versión stable con HTTP/3)...${NC}"

    # Repositorio oficial de nginx.org: versión stable más reciente (1.26+),
    # con soporte HTTP/3 (QUIC), actualizaciones de seguridad rápidas.
    # El nginx de Debian apt se queda en 1.22 (antiguo, sin HTTP/3).
    curl -fsSL https://nginx.org/keys/nginx_signing.key | gpg --dearmor \
        -o /usr/share/keyrings/nginx-archive-keyring.gpg
    echo "deb [signed-by=/usr/share/keyrings/nginx-archive-keyring.gpg] \
http://nginx.org/packages/debian $(lsb_release -cs) nginx" \
        > /etc/apt/sources.list.d/nginx.list
    # Pin para preferir nginx.org sobre el de Debian
    cat > /etc/apt/preferences.d/99nginx << 'PINEOF'
Package: nginx
Pin: origin nginx.org
Pin-Priority: 900
PINEOF
    apt-get update -qq
    apt-get install -y -qq nginx
    systemctl enable nginx

    # El nginx del repo oficial NO incluye sites-enabled por defecto y
    # corre los workers como 'nginx' en vez de 'www-data' (Debian).
    # Ambas cosas deben corregirse para compatibilidad con la estructura SVQPanel.
    if ! grep -q "sites-enabled" /etc/nginx/nginx.conf; then
        sed -i 's|include /etc/nginx/conf.d/\*.conf;|include /etc/nginx/conf.d/*.conf;\n    include /etc/nginx/sites-enabled/*;|' /etc/nginx/nginx.conf
    fi
    # Worker user -> www-data (todos los permisos de dominios se dan a www-data)
    sed -i 's/^user  nginx;/user www-data;/' /etc/nginx/nginx.conf
    mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled

    # Endurecimiento global: ocultar la versión de nginx (server_tokens off)
    cat > /etc/nginx/conf.d/svqpanel-hardening.conf << 'NGINXHARDEOF'
# SVQPanel — endurecimiento global de nginx
server_tokens off;
NGINXHARDEOF

    systemctl start nginx
    echo -e "${GREEN}✓ Nginx $(nginx -v 2>&1) instalado desde repo oficial${NC}\n"
fi

if [[ "$WEBSERVER" == "apache+nginx" ]]; then
    echo -e "${YELLOW}Instalando Apache...${NC}"
    apt-get install -y -qq apache2
    a2enmod rewrite
    a2enmod headers
    a2enmod ssl
    a2enmod proxy
    a2enmod proxy_fcgi
    a2enmod setenvif
    systemctl enable apache2
    systemctl start apache2
    echo -e "${GREEN}✓ Apache instalado${NC}\n"
fi

###############################################################################
# 6b. INSTALAR BIND9 (DNS)
###############################################################################
# Sin cluster DNS configurado, ESTE servidor sirve el DNS (BIND local).
#
# Cluster DNS (opcional, master/slave): se configura DESDE el panel (vista DNS →
# Cluster). El panel se conecta por SSH (openssh-client/sshpass, instalados
# arriba) a los nodos ns1/ns2 (Debian 12), instala bind9 en ellos, genera una
# clave TSIG compartida (tsig-keygen, de bind9-utils que se instala aquí) y
# configura master→slave (AXFR autenticado por TSIG). Ver scripts/dns_cluster.py.
# A partir de entonces el panel empuja las zonas a ns1 y este replica a ns2.
#
# DNSSEC (por zona, requiere cluster): al activarlo en una zona, el master la
# firma con dnssec-policy (BIND 9.16+, inline-signing) y publica DNSKEY/RRSIG; el
# slave recibe la zona ya firmada por AXFR. Las zonas firmadas y las claves viven
# en /var/lib/bind (escribible por named bajo AppArmor; el aprovisionamiento crea
# el dir como bind:bind). El panel lee el registro DS y lo muestra para subirlo
# al registrador del dominio (paso manual; ningún panel puede automatizarlo).
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

    # Debian trae Exim4 como MTA por defecto. SVQPanel usa Postfix (más fácil de
    # automatizar y estándar en hosting), así que purgamos Exim para que no
    # compita por el puerto 25 ni aparezca en el monitor de servicios del panel.
    if dpkg -l 2>/dev/null | grep -q '^ii.*exim4'; then
        echo -e "  ${YELLOW}→ Eliminando Exim4 (se usa Postfix)...${NC}"
        systemctl stop exim4 2>/dev/null || true
        DEBIAN_FRONTEND=noninteractive apt-get purge -y -qq \
            exim4 exim4-base exim4-config exim4-daemon-light 2>/dev/null || true
    fi

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

    # ── SMTP relay (smarthost) — estructura base ──────────────────────────
    # El panel configura el relay GLOBAL (relayhost) y el override por dominio
    # (sender_dependent_relayhost_maps) desde scripts/mail_manager.py. Aquí
    # dejamos los maps vacíos + las directivas SASL para que esté listo. Las
    # credenciales se guardan en svqpanel_relay_passwd con permisos 0600.
    touch /etc/postfix/svqpanel_relay_sender /etc/postfix/svqpanel_relay_passwd
    chmod 600 /etc/postfix/svqpanel_relay_passwd
    postmap /etc/postfix/svqpanel_relay_sender
    postmap /etc/postfix/svqpanel_relay_passwd
    chmod 600 /etc/postfix/svqpanel_relay_passwd.db 2>/dev/null || true
    postconf -e "smtp_sasl_auth_enable = yes"
    postconf -e "smtp_sasl_password_maps = hash:/etc/postfix/svqpanel_relay_passwd"
    postconf -e "smtp_sasl_security_options = noanonymous"
    postconf -e "sender_dependent_relayhost_maps = hash:/etc/postfix/svqpanel_relay_sender"

    systemctl enable postfix
    systemctl restart postfix
    echo -e "  ${GREEN}✓ Postfix configurado (SMTP 25 + submission 587 + relay listo)${NC}"

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

    # ── TLS por dominio (SNI) — estructura base ───────────────────────────
    # El panel configura un certificado propio por dominio en mail.{dominio}
    # (Dovecot local_name + Postfix tls_server_sni_maps) desde
    # scripts/mail_tls_manager.py. Aquí dejamos los ficheros vacíos listos.
    # Dovecot incluye conf.d/*.conf automáticamente, así que el SNI se aplica
    # en cuanto el panel lo rellena.
    : > /etc/dovecot/conf.d/99-svqpanel-sni.conf
    echo "# SVQPanel — TLS por dominio (SNI). Lo rellena el panel." \
        > /etc/dovecot/conf.d/99-svqpanel-sni.conf
    : > /etc/postfix/svqpanel_sni
    postmap -F hash:/etc/postfix/svqpanel_sni 2>/dev/null || true
    postconf -e "tls_server_sni_maps = hash:/etc/postfix/svqpanel_sni"

    systemctl enable dovecot
    systemctl restart dovecot
    echo -e "  ${GREEN}✓ Dovecot configurado (IMAP 143/993, POP3 110/995, SASL + SNI listo)${NC}"

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

    # ── Rate-limit de envío saliente (anti-abuso) ─────────────────────────
    # Límite de correos/hora por buzón y por dominio del remitente AUTENTICADO.
    # El panel rellena los mapas desde la BD (scripts/rspamd_manager.py →
    # rebuild_ratelimit_from_db); aquí dejamos la estructura base (Lua + conf +
    # mapas vacíos) para que un servidor nuevo nazca con el ratelimit operativo.
    # Usa el mismo Redis ya configurado arriba.
    mkdir -p /etc/rspamd/maps
    touch /etc/rspamd/maps/user_ratelimit.map /etc/rspamd/maps/domain_ratelimit.map
    cat > /etc/rspamd/svqpanel_ratelimit.lua << 'RSPAMDRLLUAEOF'
-- SVQPanel — rate-limit de envío (estructura base; el panel regenera el cuerpo)
local custom_keywords = {}
local user_map = rspamd_config:add_map({
  url = '/etc/rspamd/maps/user_ratelimit.map', type = 'map',
  description = 'SVQPanel: límite de envío por buzón',
})
local domain_map = rspamd_config:add_map({
  url = '/etc/rspamd/maps/domain_ratelimit.map', type = 'map',
  description = 'SVQPanel: límite de envío por dominio',
})
custom_keywords.svq_user_send = function(task)
  local user = task:get_user(); if not user then return end
  local lim = user_map and user_map:get_key(user:lower())
  if lim then return 'svq_user_' .. user:lower(), lim end
end
custom_keywords.svq_domain_send = function(task)
  local user = task:get_user(); if not user then return end
  local dom = user:match('@(.+)$'); if not dom then return end
  local lim = domain_map and domain_map:get_key(dom:lower())
  if lim then return 'svq_domain_' .. dom:lower(), lim end
end
return custom_keywords
RSPAMDRLLUAEOF
    cat > /etc/rspamd/local.d/ratelimit.conf << 'RSPAMDRLCONFEOF'
# SVQPanel — Rate-limit de envío saliente. NO editar manualmente.
custom_keywords = "/etc/rspamd/svqpanel_ratelimit.lua";
RSPAMDRLCONFEOF

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
    # Este Roundcube es COMPARTIDO. Se sirve en /webmail (autologin del panel) y
    # también bajo webmail.{dominio} por cada dominio con correo: el panel genera
    # un vhost svqpanel-webmail-{dominio} apuntando aquí (scripts/webmail_manager.py)
    # al activar el correo del dominio. Un solo Roundcube para todos los dominios.
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

// Carpetas especiales (IMAP standard)
\$config['sent_mbox']   = 'Sent';
\$config['trash_mbox']  = 'Trash';
\$config['drafts_mbox'] = 'Drafts';
\$config['junk_mbox']   = 'Spam';
\$config['create_default_folders'] = true;
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
    # SIEMPRE desde scripts/svqpanel_autologin.php (fuente de verdad). NO se
    # duplica el código aquí: un fallback hardcodeado se desincroniza del repo
    # y ya rompió el autologin una vez (versión vieja sin set_auth_cookie() →
    # "Su sesión no es válida"). Si el fichero no existe, es un error fatal.
    echo -e "  ${YELLOW}→ Instalando plugin de autologin...${NC}"
    RC_PLUGIN_DIR="${RC_APP_DIR}/plugins/svqpanel_autologin"
    mkdir -p "$RC_PLUGIN_DIR"

    if [[ ! -f /opt/svqpanel/scripts/svqpanel_autologin.php ]]; then
        echo -e "  ${RED}✗ Falta /opt/svqpanel/scripts/svqpanel_autologin.php — repo incompleto${NC}"
        exit 1
    fi
    cp /opt/svqpanel/scripts/svqpanel_autologin.php \
       "${RC_PLUGIN_DIR}/svqpanel_autologin.php"
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
        # gmp/bcmath/intl/imagick/apcu: requeridas/recomendadas por Nextcloud.
        for EXT in opcache intl soap readline gmp imagick apcu; do
            apt-get install -y -q "php${PHP_VER}-${EXT}" 2>/dev/null && \
                echo "    ✓ php${PHP_VER}-${EXT}" || \
                echo "    ⚠ php${PHP_VER}-${EXT} no disponible (ignorado)"
        done

        # Habilitar y arrancar FPM
        systemctl enable "php${PHP_VER}-fpm" 2>/dev/null && \
        systemctl start  "php${PHP_VER}-fpm" 2>/dev/null

        # NOTA: NO fijamos disable_functions en el php.ini GLOBAL de FPM.
        # El hardening se aplica por dominio en su pool dedicado (open_basedir +
        # disable_functions). Hacerlo global rompería el toggle "relajar
        # hardening" de un dominio, porque php_admin_value de un pool puede
        # AÑADIR funciones bloqueadas pero NO quitar las ya fijadas globalmente.
        # Dejamos disable_functions vacío en el global a propósito.
        PHP_INI_FPM="/etc/php/${PHP_VER}/fpm/php.ini"
        if [[ -f "$PHP_INI_FPM" ]]; then
            sed -i "s|^\s*disable_functions\s*=.*|disable_functions =|" "$PHP_INI_FPM"
        fi

        # Verificar que FPM arrancó (socket debe existir)
        systemctl restart "php${PHP_VER}-fpm" 2>/dev/null
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

# ── Herramientas para el autoinstalador de apps (WordPress/Laravel/Nextcloud/…) ─
# Nextcloud usa 'unzip' + 'curl' (instalados arriba) y occ; no requiere binario extra.
echo -e "${YELLOW}Instalando herramientas de autoinstalación (wp-cli, composer)...${NC}"
# wp-cli
if [[ ! -f /usr/local/bin/wp ]]; then
    if curl -fsSL -o /usr/local/bin/wp \
        https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar; then
        chmod +x /usr/local/bin/wp
        echo -e "  ${GREEN}✓ wp-cli instalado${NC}"
    else
        echo -e "  ${YELLOW}⚠ no se pudo instalar wp-cli (se reintenta al instalar WordPress)${NC}"
    fi
fi
# composer (para Laravel y otras apps PHP)
if [[ ! -f /usr/local/bin/composer ]]; then
    if curl -fsSL -o /tmp/composer-setup.php https://getcomposer.org/installer; then
        php /tmp/composer-setup.php --install-dir=/usr/local/bin --filename=composer >/dev/null 2>&1 \
            && echo -e "  ${GREEN}✓ composer instalado${NC}" \
            || echo -e "  ${YELLOW}⚠ no se pudo instalar composer${NC}"
        rm -f /tmp/composer-setup.php
    fi
fi
echo ""

# Zona global de rate limiting para nginx (status 429). Las zonas por dominio
# las crea el panel on-demand. Se deja aquí para que exista desde el inicio.
mkdir -p /etc/nginx/conf.d
if [[ ! -f /etc/nginx/conf.d/svqpanel-ratelimit-global.conf ]]; then
    cat > /etc/nginx/conf.d/svqpanel-ratelimit-global.conf << 'RLGEOF'
# SVQPanel — rate limiting (nivel http)
# Las zonas (limit_req_zone) las define cada dominio en su propio fichero.
limit_req_status 429;
RLGEOF
    echo -e "${GREEN}✓ Zona global de rate limiting nginx creada${NC}"
fi

# Endurecimiento global de nginx (nivel http): ocultar versión en banners/errores
cat > /etc/nginx/conf.d/svqpanel-hardening.conf << 'NGHEOF'
# SVQPanel — endurecimiento global nginx
server_tokens off;
NGHEOF

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

    # ── Generar contraseña del usuario admin del panel ────────────────────────
    # root NO usa contraseña: conecta vía unix_socket (default Debian/MariaDB),
    # más seguro e idempotente entre reinstalaciones.
    MARIADB_PANEL_PASS=$(python3 -c \
        "import secrets,string; \
         chars=string.ascii_letters+string.digits; \
         print(''.join(secrets.choice(chars) for _ in range(24)))")

    # ── Garantizar acceso root vía unix_socket (idempotente) ──────────────────
    # En Debian/MariaDB limpio, root usa unix_socket: el root del SO conecta sin
    # contraseña. Pero una instalación ANTERIOR pudo dejar root con
    # mysql_native_password y una contraseña que ya no conocemos. En ese caso
    # 'mariadb -u root' falla con "Access denied (using password: NO)".
    # Esta función fuerza root de vuelta a unix_socket arrancando MariaDB en
    # modo --skip-grant-tables (sin verificación de credenciales) solo si el
    # acceso normal por socket no funciona.
    _ensure_mariadb_root_socket() {
        if mariadb --user=root --connect-timeout=5 -e "SELECT 1" &>/dev/null; then
            return 0   # ya accesible por socket, nada que hacer
        fi
        echo -e "  ${YELLOW}root de MariaDB no accesible por socket; reseteando a unix_socket...${NC}"
        systemctl stop mariadb 2>/dev/null
        # Arrancar el daemon sin tablas de privilegios, solo socket local
        mariadbd-safe --skip-grant-tables --skip-networking &>/dev/null &
        local _pid=$!
        # Esperar a que el socket esté listo (máx ~15s)
        local _i
        for _i in $(seq 1 30); do
            mariadb --user=root -e "SELECT 1" &>/dev/null && break
            sleep 0.5
        done
        # Restaurar root a unix_socket (FLUSH PRIVILEGES reactiva la tabla de grants)
        mariadb --user=root <<'SKIPEOF' &>/dev/null
FLUSH PRIVILEGES;
ALTER USER 'root'@'localhost' IDENTIFIED VIA unix_socket;
FLUSH PRIVILEGES;
SKIPEOF
        # Parar el daemon temporal y arrancar el servicio normal
        mariadb-admin --user=root shutdown &>/dev/null || kill "$_pid" 2>/dev/null
        sleep 2
        systemctl start mariadb
        for _i in $(seq 1 30); do
            mariadb --user=root -e "SELECT 1" &>/dev/null && break
            sleep 0.5
        done
    }
    _ensure_mariadb_root_socket

    # A partir de aquí root conecta siempre por socket sin contraseña.
    _mariadb_root() { mariadb --user=root "$@"; }

    if ! _mariadb_root << MARIADBEOF
-- Asegurar que root use unix_socket (idempotente, no rompe instalaciones limpias)
ALTER USER 'root'@'localhost' IDENTIFIED VIA unix_socket;
-- Eliminar usuarios anónimos y BD test
DELETE FROM mysql.user WHERE User='';
DROP DATABASE IF EXISTS test;
DELETE FROM mysql.db WHERE Db='test' OR Db='test\\_%';
-- Usuario administrador del panel SVQPanel
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
    then
        echo -e "${RED}✗ Error configurando MariaDB (root no accesible). Abortando.${NC}"
        exit 1
    fi

    echo -e "  ${GREEN}✓ MariaDB asegurado y usuario del panel creado${NC}"

    # ── Guardar credenciales ──────────────────────────────────────────────────
    mkdir -p /opt/svqpanel/.credentials
    cat > /opt/svqpanel/.credentials/mariadb.txt << MDBCREDEOF
# Credenciales MariaDB — NO compartir
MariaDB root:          unix_socket (sin contraseña; usar 'mariadb -u root' como root del SO)
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
        # Generamos la clave con stdlib pura (base64+os.urandom) para no depender
        # de 'cryptography', que aún no está instalada en este punto del install
        # (el venv se crea más adelante en el paso 8). Una clave Fernet válida es
        # exactamente 32 bytes aleatorios en base64-url-safe (44 chars con '=').
        PANEL_ENCRYPTION_KEY=$(python3 -c \
            "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")

        PMA_BLOWFISH_SECRET=$(python3 -c \
            "import secrets, string; \
             chars = string.ascii_letters + string.digits; \
             print(''.join(secrets.choice(chars) for _ in range(56)))")

        PMA_CONTROL_PASS=$(python3 -c \
            "import secrets, string; \
             chars = string.ascii_letters + string.digits; \
             print(''.join(secrets.choice(chars) for _ in range(24)))")

        # ── BD phpmyadmin + usuario pma (controluser) ─────────────────────────
        _mariadb_root << PMADBEOF
CREATE DATABASE IF NOT EXISTS phpmyadmin CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
DROP USER IF EXISTS 'pma'@'localhost';
CREATE USER 'pma'@'localhost' IDENTIFIED BY '${PMA_CONTROL_PASS}';
GRANT SELECT, INSERT, UPDATE, DELETE ON phpmyadmin.* TO 'pma'@'localhost';
FLUSH PRIVILEGES;
PMADBEOF
        _mariadb_root phpmyadmin < "${PMA_DIR}/sql/create_tables.sql"
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

# Clonar repo público. /opt/svqpanel puede YA existir (p.ej. .credentials que
# creó la fase de MariaDB, o una instalación anterior), por lo que git clone
# directo fallaría ("directory exists and is not empty"). Clonamos a un temporal
# y volcamos el contenido preservando lo que ya hubiera (credenciales, .env…).
REPO_URL="https://github.com/coriaweb/SVQPanel.git"
_CLONE_TMP=$(mktemp -d)
rmdir "$_CLONE_TMP"   # git clone exige que el destino no exista
if git clone --depth 1 "$REPO_URL" "$_CLONE_TMP" 2>/tmp/svq_clone.log; then
    mkdir -p /opt/svqpanel
    # Copiar TODO el repo (incluidos dotfiles) sobre /opt/svqpanel sin borrar
    # lo preexistente (.credentials, .env). cp -a preserva permisos.
    cp -a "$_CLONE_TMP"/. /opt/svqpanel/
    rm -rf "$_CLONE_TMP"
    echo -e "${GREEN}✓ Repositorio clonado en /opt/svqpanel${NC}"
else
    echo -e "${RED}✗ No se pudo clonar el repositorio:${NC}"
    cat /tmp/svq_clone.log
    echo -e "${RED}  Verifica conectividad a github.com y que el repo sea accesible.${NC}"
    exit 1
fi

cd /opt/svqpanel

# Verificar que el código realmente está presente
if [[ ! -f /opt/svqpanel/requirements.txt || ! -d /opt/svqpanel/api/models ]]; then
    echo -e "${RED}✗ El repositorio se clonó pero falta código esencial (requirements.txt / api/models).${NC}"
    exit 1
fi

# Crear carpetas auxiliares si no existen
mkdir -p logs data

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
# Usar create_tables() del panel: importa TODOS los modelos y hace create_all.
# Evita listas de import manuales que se desincronizan y rompen FKs.
from api.models.database import create_tables
create_tables()
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
# La API solo escucha en localhost; se sirve al exterior vía nginx.
PANEL_HOST=127.0.0.1
PANEL_PORT=8001
# Puerto público dedicado donde nginx sirve el panel (ver vhost svqpanel).
PANEL_WEB_PORT=${PANEL_WEB_PORT}
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

# El .env contiene credenciales (SECRET_KEY, BD, MariaDB) → solo root
chmod 600 /opt/svqpanel/.env
chown root:root /opt/svqpanel/.env

echo -e "${GREEN}✓ Archivo .env creado (permisos 600)${NC}\n"

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
# PATH debe incluir las rutas del sistema: el panel invoca binarios del SO
# (ssh-keygen/ssh/scp para el cluster DNS, nft, certbot, etc.). Solo con el venv
# fallaban con FileNotFoundError.
Environment="PATH=/opt/svqpanel/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
# --limit-max-requests: reinicia el worker cada N peticiones liberando memoria acumulada
# --timeout-keep-alive: cierra keep-alive rápido para no retener conexiones/memoria
ExecStart=/opt/svqpanel/venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8001 --limit-max-requests 500 --timeout-keep-alive 2
Restart=always
RestartSec=10
TimeoutStartSec=30
# Reiniciar automáticamente si el proceso supera 900 MB de RAM.
# El proceso Python carga muchos modelos y puede acumular memoria;
# con MemoryMax systemd lo reinicia limpiamente antes de llegar al límite del SO.
MemoryMax=1500M
MemorySwapMax=800M

[Install]
WantedBy=multi-user.target
SERVICEEOF

systemctl daemon-reload
systemctl enable svqpanel

echo -e "${GREEN}✓ Servicio systemd creado${NC}\n"

###############################################################################
# 11B. CONFIGURAR SUDOERS PARA APT (panel de actualizaciones)
###############################################################################
echo -e "${YELLOW}Configurando sudoers para panel de actualizaciones...${NC}"

SUDOERS_FILE="/etc/sudoers.d/svqpanel-apt"
cat > "$SUDOERS_FILE" << 'SUDOERSEOF'
# SVQPanel — permisos para apt-get/apt (panel de actualizaciones)
root ALL=(ALL) NOPASSWD: /usr/bin/apt-get, /usr/bin/apt
SUDOERSEOF
chmod 0440 "$SUDOERS_FILE"
visudo -c -f "$SUDOERS_FILE" >/dev/null 2>&1 && \
    echo -e "${GREEN}✓ Sudoers configurado para apt${NC}\n" || \
    echo -e "${YELLOW}⚠ Advertencia: sudoers no se configuró correctamente${NC}\n"

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
    # El panel se sirve en su PUERTO DEDICADO (no 80/443), para poder cerrarlo
    # selectivamente en el firewall perimetral sin afectar a los sitios de
    # clientes. Al estar solo en su puerto no necesita default_server.
    listen __PANEL_WEB_PORT__;
    server_name _;

    client_max_body_size 100M;

    # Cabeceras de seguridad (a nivel server: válidas para todo el panel).
    # El CSP NO va aquí porque /webmail, /pma, /rspamd son apps aparte que
    # rompen con un CSP estricto; el CSP se aplica solo en "location /" (la SPA).
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "geolocation=(), microphone=(), camera=(), payment=()" always;

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
        # CSP solo para la SPA del panel (un location con add_header no hereda
        # los del server, así que reafirmamos también los de seguridad básicos).
        add_header X-Frame-Options "SAMEORIGIN" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "strict-origin-when-cross-origin" always;
        add_header Permissions-Policy "geolocation=(), microphone=(), camera=(), payment=()" always;
        add_header Content-Security-Policy "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; font-src 'self' https://cdn.jsdelivr.net https://fonts.gstatic.com; script-src 'self' https://cdn.jsdelivr.net; connect-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'" always;
    }
}
NGINXEOF

    # Sustituir el placeholder del puerto del panel por el elegido en el wizard.
    sed -i "s|__PANEL_WEB_PORT__|${PANEL_WEB_PORT}|g" /etc/nginx/sites-available/svqpanel

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
    "        root /var/www;\n"
    "        index index.php;\n"
    "        # Roundcube 1.7.0+: assets servidos por static.php con PATH_INFO\n"
    "        location ~ ^/webmail/static\\.php {\n"
    "            fastcgi_split_path_info ^(/webmail/static\\.php)(/.+)\$;\n"
    "            fastcgi_pass unix:" + sock + ";\n"
    "            include fastcgi_params;\n"
    "            fastcgi_param SCRIPT_FILENAME /var/www/webmail/static.php;\n"
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

    # ── Página de bienvenida para accesos por IP (puerto 80) ──────────────────
    # Quien entre por http://IP (sin un dominio configurado) ve una página
    # neutra "el servidor funciona" en vez del panel. El panel solo se sirve por
    # su hostname:puerto dedicado. Este vhost es default_server: captura todo lo
    # que no haga match con otro server_name en el puerto 80.
    mkdir -p /var/www/html
    if [[ -f /opt/svqpanel/scripts/assets/welcome.html ]]; then
        cp /opt/svqpanel/scripts/assets/welcome.html /var/www/html/index.html
    fi
    chown -R www-data:www-data /var/www/html

    cat > /etc/nginx/sites-available/svqpanel-welcome << 'WELCOMEEOF'
# Página de bienvenida por IP / dominio no configurado (puerto 80, default).
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    # Permitir validación ACME de Let's Encrypt para cualquier dominio.
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    root /var/www/html;
    index index.html;
    location / {
        try_files $uri $uri/ =200;
    }
}
WELCOMEEOF
    ln -sf /etc/nginx/sites-available/svqpanel-welcome /etc/nginx/sites-enabled/svqpanel-welcome

    nginx -t && systemctl restart nginx

    echo -e "${GREEN}✓ Nginx configurado (panel + bienvenida por IP)${NC}\n"
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
        # Política DROP: todo lo que no se acepte explícitamente se descarta.
        type filter hook input priority filter; policy drop;

        # Tráfico local y conexiones ya establecidas
        iif "lo" accept
        ct state { established, related } accept
        ct state invalid drop

        # ICMP básico (ping, path MTU, etc.)
        ip  protocol icmp icmp type { echo-request, destination-unreachable, time-exceeded, parameter-problem } accept
        ip6 nexthdr  icmpv6 icmpv6 type { echo-request, destination-unreachable, packet-too-big, time-exceeded, parameter-problem, nd-router-solicit, nd-router-advert, nd-neighbor-solicit, nd-neighbor-advert } accept

        # Bans dinámicos de fail2ban PRIMERO (un baneado no entra ni al 443)
        ip  saddr @f2b_v4 drop
        ip6 saddr @f2b_v6 drop

        # Whitelist (IPs de confianza: acceso total)
        ip  saddr @whitelist_v4 accept
        ip6 saddr @whitelist_v6 accept

        # ── Puertos PÚBLICOS de los servicios del panel ──────────────────
        # SSH
        tcp dport 22 accept
        # Web (nginx)
        tcp dport { 80, 443 } accept
        # Panel de control SVQPanel (puerto dedicado). Para máxima seguridad
        # puedes cerrar este puerto en tu firewall perimetral y dejarlo abierto
        # solo a tus IPs de administración.
        tcp dport __PANEL_WEB_PORT__ accept
        # UDP mismo puerto: necesario para HTTP/3 (QUIC)
        udp dport __PANEL_WEB_PORT__ accept
        # Correo: SMTP, submission, IMAP(S), POP3(S)
        tcp dport { 25, 587, 465, 143, 993, 110, 995 } accept
        # DNS (BIND) — consultas entrantes a las zonas alojadas
        tcp dport 53 accept
        udp dport 53 accept

        # NOTA: la API del panel (8001) NO se abre: solo escucha en 127.0.0.1
        # y se sirve por nginx en el puerto del panel. MariaDB/PostgreSQL/Redis/
        # rspamd/crowdsec son localhost-only por diseño.
    }
}

# Includes gestionados por el panel (pueden estar vacíos al inicio)
include "/etc/nftables/svqpanel-iplists.nft"
include "/etc/nftables/svqpanel-rules.nft"
NFTEOF

# Sustituir el placeholder del puerto del panel en las reglas del firewall.
sed -i "s|__PANEL_WEB_PORT__|${PANEL_WEB_PORT}|g" /etc/nftables.conf

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

echo -e "${GREEN}✓ nftables: tabla 'inet svqpanel' activa (política DROP + puertos del panel abiertos)${NC}"

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

# Action custom: banea en los sets f2b_v4/f2b_v6 de la tabla 'inet svqpanel',
# que tienen reglas drop para IPv4 E IPv6 (la nftables-multiport por defecto
# solo crea set/regla IPv4 → los atacantes por IPv6 no se bloqueaban).
if [[ -f /opt/svqpanel/scripts/assets/fail2ban-svqpanel-nft.conf ]]; then
    cp /opt/svqpanel/scripts/assets/fail2ban-svqpanel-nft.conf \
       /etc/fail2ban/action.d/svqpanel-nft.conf
fi

# Filtro SVQPanel para scanners de vulnerabilidades (phpunit, cgi-bin, eval-stdin, etc.)
# Solo captura rutas que nunca genera tráfico legítimo → seguro frente a Googlebot.
cp /opt/svqpanel/config/fail2ban/svqpanel-scanner.conf \
   /etc/fail2ban/filter.d/svqpanel-scanner.conf

cat > /etc/fail2ban/jail.local << F2BEOF
# /etc/fail2ban/jail.local — gestionado por SVQPanel (Fase 12)
# Cualquier cambio desde el panel puede sobrescribir este archivo.

[DEFAULT]
bantime  = 1h
findtime = 10m
maxretry = 5
backend  = systemd
# allowipv6=auto: fail2ban detecta y procesa IPs IPv6 si el sistema tiene IPv6.
allowipv6 = auto
# banaction propia → escribe en inet svqpanel (cubre IPv4 + IPv6).
banaction = svqpanel-nft
banaction_allports = svqpanel-nft
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

[svqpanel-scanner]
enabled   = true
filter    = svqpanel-scanner
port      = http,https
logpath   = /home/*/web/*/logs/nginx.access.log
            /var/log/nginx/access.log
backend   = auto
maxretry  = 5
findtime  = 120
bantime   = 86400
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

# Directorio raíz de copias de seguridad (destino local por defecto)
mkdir -p /backups
chmod 700 /backups

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

###############################################################################
# 12C. CROWDSEC (IPS colaborativo)
#
# CrowdSec analiza logs (sshd, nginx, postfix...) y genera decisiones de ban
# que aplica el bouncer de nftables. Coexiste con fail2ban: fail2ban es
# reactivo simple (regex sobre logs), CrowdSec añade escenarios complejos +
# blocklist comunitaria opcional via CAPI.
#
# Tablas nftables que coexisten:
#   - 'inet svqpanel'  → gestionado por el panel (whitelist + f2b sets)
#   - 'ip/ip6 crowdsec' → gestionado por crowdsec-firewall-bouncer
###############################################################################
if [[ "$INSTALL_CROWDSEC" == true ]]; then
    echo -e "${YELLOW}Instalando CrowdSec...${NC}"

    # ── 1. Repositorio oficial ────────────────────────────────────────────────
    curl -s https://install.crowdsec.net 2>/dev/null | bash > /dev/null 2>&1 || {
        echo -e "  ${YELLOW}⚠ Fallback: añadiendo repo packagecloud manualmente${NC}"
        curl -s https://packagecloud.io/install/repositories/crowdsec/crowdsec/script.deb.sh 2>/dev/null \
            | bash > /dev/null 2>&1
    }
    apt-get update -qq

    # ── 2. CrowdSec engine + bouncer firewall (nftables) ──────────────────────
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq crowdsec

    # Pre-seleccionar nftables como backend antes de instalar el bouncer,
    # así no salta el wizard interactivo en sistemas con iptables y nftables
    debconf-set-selections <<< "crowdsec-firewall-bouncer crowdsec-firewall-bouncer/backend select nftables"
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq crowdsec-firewall-bouncer-nftables 2>/dev/null \
        || DEBIAN_FRONTEND=noninteractive apt-get install -y -qq crowdsec-firewall-bouncer-iptables

    # Verificar que cscli existe
    if ! command -v cscli >/dev/null 2>&1; then
        echo -e "  ${RED}✗ cscli no disponible — CrowdSec no se instaló correctamente${NC}"
        echo -e "  ${YELLOW}  Revisa: apt-get install crowdsec  (o journalctl -u crowdsec)${NC}"
    else
        echo -e "  ${GREEN}✓ CrowdSec engine $(cscli version 2>/dev/null | grep -oP 'version:\s*\K\S+' | head -1) instalado${NC}"

        # ── 3. Colecciones base ───────────────────────────────────────────────
        echo -e "  ${YELLOW}→ Instalando colecciones (parsers + escenarios)...${NC}"
        for COL in \
            crowdsecurity/linux \
            crowdsecurity/sshd \
            crowdsecurity/nginx \
            crowdsecurity/base-http-scenarios \
            crowdsecurity/http-cve; do
            cscli collections install "$COL" > /dev/null 2>&1 \
                && echo -e "    ${GREEN}✓ $COL${NC}" \
                || echo -e "    ${YELLOW}⚠ $COL (no disponible)${NC}"
        done

        if [[ "$INSTALL_MAIL" == true ]]; then
            for COL in crowdsecurity/postfix crowdsecurity/dovecot; do
                cscli collections install "$COL" > /dev/null 2>&1 \
                    && echo -e "    ${GREEN}✓ $COL${NC}" \
                    || echo -e "    ${YELLOW}⚠ $COL (no disponible)${NC}"
            done
        fi

        cscli hub update > /dev/null 2>&1 || true

        # ── 4. Whitelist IP del instalador ────────────────────────────────────
        if [[ -n "$INSTALLER_IP" ]]; then
            mkdir -p /etc/crowdsec/parsers/s02-enrich
            cat > /etc/crowdsec/parsers/s02-enrich/svqpanel-whitelist.yaml << CSWLEOF
name: svqpanel/installer-whitelist
description: "Whitelist IP del instalador (SVQPanel)"
whitelist:
  reason: "SVQPanel installer / admin SSH origin"
  ip:
    - "${INSTALLER_IP}"
CSWLEOF
            echo -e "  ${GREEN}✓ IP ${INSTALLER_IP} añadida a whitelist CrowdSec${NC}"
        fi

        # ── 5. Acquis extra: log de auth del propio panel ─────────────────────
        # CrowdSec lee /opt/svqpanel/logs/auth.log (mismo log que fail2ban) y
        # podemos reutilizar el filtro 'sshd' si las líneas se parecen, o más
        # adelante crear un parser SVQPanel dedicado.
        mkdir -p /etc/crowdsec/acquis.d
        cat > /etc/crowdsec/acquis.d/svqpanel.yaml << CSACQEOF
# SVQPanel — fuente adicional de logs para CrowdSec
filenames:
  - /opt/svqpanel/logs/auth.log
labels:
  type: syslog
  application: svqpanel
CSACQEOF

        # ── 6. Servicios ──────────────────────────────────────────────────────
        systemctl enable crowdsec >/dev/null 2>&1 || true
        systemctl restart crowdsec >/dev/null 2>&1 || systemctl start crowdsec

        # El bouncer puede llamarse crowdsec-firewall-bouncer.service
        systemctl enable crowdsec-firewall-bouncer >/dev/null 2>&1 || true
        systemctl restart crowdsec-firewall-bouncer >/dev/null 2>&1 \
            || systemctl start crowdsec-firewall-bouncer >/dev/null 2>&1 || true

        # ── 7. Verificación ───────────────────────────────────────────────────
        if systemctl is-active --quiet crowdsec; then
            echo -e "  ${GREEN}✓ Servicio crowdsec activo${NC}"
        else
            echo -e "  ${RED}✗ crowdsec NO activo (revisar: journalctl -u crowdsec)${NC}"
        fi
        if systemctl is-active --quiet crowdsec-firewall-bouncer; then
            echo -e "  ${GREEN}✓ crowdsec-firewall-bouncer activo${NC}"
        else
            echo -e "  ${YELLOW}⚠ crowdsec-firewall-bouncer NO activo (los bans no se aplicarán al firewall)${NC}"
        fi
    fi

    echo -e "${GREEN}✓ CrowdSec instalado${NC}\n"
fi

###############################################################################
# 12D. SFTP (acceso SFTP-only con chroot para clientes)
#
# Crea el grupo 'sftponly' y un snippet de sshd que aplica chroot al home
# y fuerza internal-sftp (sin shell). El panel mete/saca usuarios del grupo
# desde la UI (UserAccount → Acceso SFTP).
###############################################################################
echo -e "${YELLOW}Configurando SFTP (grupo sftponly + sshd)...${NC}"

groupadd sftponly 2>/dev/null && \
    echo -e "  ${GREEN}✓ Grupo sftponly creado${NC}" || \
    echo -e "  ${YELLOW}⚠ Grupo sftponly ya existía${NC}"

# ACL necesario para las subcuentas SFTP (acceso quirúrgico sin tocar owner/grupo)
apt-get install -y -qq acl 2>/dev/null || true

mkdir -p /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/svqpanel-sftponly.conf << 'SFTPEOF'
# SVQPanel — Match Group para usuarios SFTP-only (chroot al home)
# Generado por install.sh; no editar a mano (el panel lo regenera).
Match Group sftponly
    ChrootDirectory %h
    ForceCommand internal-sftp
    AllowTcpForwarding no
    X11Forwarding no
    PermitTunnel no
    AllowAgentForwarding no
    PasswordAuthentication yes
    PubkeyAuthentication yes
SFTPEOF

# Asegurar que sshd_config incluye el directorio sshd_config.d (Debian 12+ ya lo trae)
if ! grep -qE '^\s*Include\s+/etc/ssh/sshd_config\.d/' /etc/ssh/sshd_config; then
    echo "Include /etc/ssh/sshd_config.d/*.conf" >> /etc/ssh/sshd_config
fi

if sshd -t 2>/dev/null; then
    systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
    echo -e "  ${GREEN}✓ sshd configurado para SFTP-only (chroot al home)${NC}"
else
    echo -e "  ${RED}✗ sshd -t falló; revisa /etc/ssh/sshd_config.d/svqpanel-sftponly.conf${NC}"
fi
echo ""

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

# ─── Timer horario para refresco de stats de usuarios (Fase 13.2) ────────────
cat > /etc/systemd/system/svqpanel-user-stats.service << 'USTSEOF'
[Unit]
Description=SVQPanel — recalcula disco + tráfico mensual por usuario
After=network.target svqpanel.service

[Service]
Type=oneshot
User=root
WorkingDirectory=/opt/svqpanel
ExecStart=/opt/svqpanel/venv/bin/python -m api.cli refresh_user_stats
TimeoutStartSec=900

[Install]
WantedBy=multi-user.target
USTSEOF

cat > /etc/systemd/system/svqpanel-user-stats.timer << 'USTTEOF'
[Unit]
Description=SVQPanel — timer horario para stats de usuarios

[Timer]
OnBootSec=5min
OnUnitActiveSec=1h
Persistent=true
Unit=svqpanel-user-stats.service

[Install]
WantedBy=timers.target
USTTEOF

systemctl daemon-reload
systemctl enable --now svqpanel-user-stats.timer >/dev/null 2>&1 || true

echo -e "${GREEN}✓ systemd timer: svqpanel-user-stats.timer (horario)${NC}"

# ─── Timer cada 4h para recalcular disk_usage por dominio ────────────────────
cat > /etc/systemd/system/svqpanel-domain-stats.service << 'DSTEOF'
[Unit]
Description=SVQPanel — recalcula disk_usage por dominio
After=network.target svqpanel.service

[Service]
Type=oneshot
User=root
WorkingDirectory=/opt/svqpanel
ExecStart=/opt/svqpanel/venv/bin/python -m api.cli refresh_domain_stats
TimeoutStartSec=600

[Install]
WantedBy=multi-user.target
DSTEOF

cat > /etc/systemd/system/svqpanel-domain-stats.timer << 'DSTTEOF'
[Unit]
Description=SVQPanel — timer cada 4h para disk_usage de dominios

[Timer]
OnBootSec=10min
OnUnitActiveSec=4h
Persistent=true
Unit=svqpanel-domain-stats.service

[Install]
WantedBy=timers.target
DSTTEOF

# ─── Timer diario para sincronizar fechas de expiración SSL ──────────────────
cat > /etc/systemd/system/svqpanel-ssl-check.service << 'SSLCEOF'
[Unit]
Description=SVQPanel — sincroniza ssl_expires desde certbot
After=network.target svqpanel.service

[Service]
Type=oneshot
User=root
WorkingDirectory=/opt/svqpanel
ExecStart=/opt/svqpanel/venv/bin/python -m api.cli refresh_ssl_expires
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target
SSLCEOF

cat > /etc/systemd/system/svqpanel-ssl-check.timer << 'SSLCTEOF'
[Unit]
Description=SVQPanel — timer diario para comprobación SSL (05:15)

[Timer]
OnCalendar=*-*-* 05:15:00
Persistent=true
Unit=svqpanel-ssl-check.service

[Install]
WantedBy=timers.target
SSLCTEOF

# ─── Timer cada 10 min: salud de sincronización del cluster DNS ──────────────
# Solo hace trabajo real si hay cluster configurado (si no, sale enseguida).
cat > /etc/systemd/system/svqpanel-dns-cluster-health.service << 'DCHEOF'
[Unit]
Description=SVQPanel — comprueba sincronización del cluster DNS (serial BD/ns1/ns2)
After=network.target svqpanel.service

[Service]
Type=oneshot
User=root
WorkingDirectory=/opt/svqpanel
ExecStart=/opt/svqpanel/venv/bin/python -m api.cli dns_cluster_health
TimeoutStartSec=180
DCHEOF

cat > /etc/systemd/system/svqpanel-dns-cluster-health.timer << 'DCHTEOF'
[Unit]
Description=SVQPanel — timer cada 10 min para salud del cluster DNS

[Timer]
OnBootSec=8min
OnUnitActiveSec=10min
Persistent=true
Unit=svqpanel-dns-cluster-health.service

[Install]
WantedBy=timers.target
DCHTEOF

# ─── Timer cada minuto: ejecutar backups programados ─────────────────────────
# Los backups se lanzan desde cli.py (proceso independiente que termina),
# en vez de un hilo de fondo en el panel (causa fuga de memoria).
cat > /etc/systemd/system/svqpanel-backup-scheduler.service << 'BKSEOF'
[Unit]
Description=SVQPanel — ejecuta backups programados (cron)
After=network.target svqpanel.service

[Service]
Type=oneshot
User=root
WorkingDirectory=/opt/svqpanel
Environment="PATH=/opt/svqpanel/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=/opt/svqpanel/venv/bin/python -m api.cli run_scheduled_backups
TimeoutStartSec=3600
BKSEOF

cat > /etc/systemd/system/svqpanel-backup-scheduler.timer << 'BKTEOF'
[Unit]
Description=SVQPanel — timer cada minuto para backups programados

[Timer]
OnBootSec=2min
OnUnitActiveSec=1min
Persistent=false

[Install]
WantedBy=timers.target
BKTEOF

systemctl daemon-reload
systemctl enable --now svqpanel-domain-stats.timer          >/dev/null 2>&1 || true
systemctl enable --now svqpanel-ssl-check.timer             >/dev/null 2>&1 || true
systemctl enable --now svqpanel-dns-cluster-health.timer    >/dev/null 2>&1 || true
systemctl enable --now svqpanel-backup-scheduler.timer      >/dev/null 2>&1 || true

echo -e "${GREEN}✓ systemd timer: svqpanel-domain-stats.timer (cada 4h)${NC}"
echo -e "${GREEN}✓ systemd timer: svqpanel-ssl-check.timer (diario 05:15)${NC}"
echo -e "${GREEN}✓ systemd timer: svqpanel-dns-cluster-health.timer (cada 10 min)${NC}"
echo -e "${GREEN}✓ systemd timer: svqpanel-backup-scheduler.timer (cada minuto)${NC}"
echo ""

###############################################################################
# 13. CREAR USUARIO ADMIN AUTOMÁTICO
###############################################################################
echo -e "${YELLOW}Creando usuario administrador...${NC}"

cd /opt/svqpanel
source venv/bin/activate

# ── Nombre de usuario admin ───────────────────────────────────────────────────
# "admin" es el nombre más atacado por bots de fuerza bruta. Permitimos elegir
# uno personalizado; si se deja en blanco, se genera uno aleatorio tipo svq_a3f9.
# El mismo nombre se usa para el usuario del panel (PostgreSQL) Y para el usuario
# del sistema operativo (estructura /home, pools PHP, etc.).
echo ""
echo -e "${YELLOW}Nombre de usuario administrador del panel:${NC}"
echo -e "  Deja en blanco para generar uno aleatorio (recomendado por seguridad)"
printf "  Usuario admin (Enter = aleatorio): "; read _ADMIN_USER_INPUT </dev/tty
if [[ -z "$_ADMIN_USER_INPUT" ]]; then
    ADMIN_USER="svq_$(python3 -c 'import secrets,string; print(secrets.token_hex(3))')"
    echo -e "  ${GREEN}✓ Usuario generado: ${YELLOW}${ADMIN_USER}${NC}"
else
    # Validar: solo letras minúsculas, números y guiones bajos, 3-32 chars
    if [[ "$_ADMIN_USER_INPUT" =~ ^[a-z][a-z0-9_]{2,31}$ ]]; then
        ADMIN_USER="$_ADMIN_USER_INPUT"
        echo -e "  ${GREEN}✓ Usuario: ${ADMIN_USER}${NC}"
    else
        ADMIN_USER="svq_$(python3 -c 'import secrets; print(secrets.token_hex(3))')"
        echo -e "  ${YELLOW}⚠ Nombre inválido (solo a-z, 0-9, _; mínimo 3 chars). Usando: ${ADMIN_USER}${NC}"
    fi
fi
echo ""

# ── Contraseña aleatoria de 16 caracteres (A-Z, a-z, 0-9) ───────────────────
ADMIN_PASSWORD=$(python3 -c \
    "import secrets,string; chars=string.ascii_letters+string.digits; \
     print(''.join(secrets.choice(chars) for _ in range(16)))")

# Crear usuario del SISTEMA además del usuario del panel.
# El panel necesita un usuario del SO para operaciones de sistema (pools PHP-FPM,
# estructura de directorios, etc.). Hestia hace lo mismo con su cuenta admin.
if ! id "$ADMIN_USER" >/dev/null 2>&1; then
    useradd -m -s /bin/bash -d "/home/${ADMIN_USER}" "$ADMIN_USER"
    echo "${ADMIN_USER}:${ADMIN_PASSWORD}" | chpasswd
    # Estructura web estilo Hestia (igual que UserManager.create_user)
    mkdir -p "/home/${ADMIN_USER}/web"
    chown "${ADMIN_USER}:www-data" "/home/${ADMIN_USER}/web"
    chmod 750 "/home/${ADMIN_USER}/web"
    mkdir -p "/home/${ADMIN_USER}/tmp"
    chown "${ADMIN_USER}:${ADMIN_USER}" "/home/${ADMIN_USER}/tmp"
    chmod 750 "/home/${ADMIN_USER}/tmp"
    echo -e "  ${GREEN}✓ Usuario del sistema '${ADMIN_USER}' creado${NC}"
else
    echo -e "  ${YELLOW}⚠ Usuario del sistema '${ADMIN_USER}' ya existía, no se recrea${NC}"
fi

# Crear usuario admin en la BD (pasar nombre y contraseña via variables de entorno)
SVQPANEL_ADMIN_USER="$ADMIN_USER" SVQPANEL_ADMIN_PASS="$ADMIN_PASSWORD" python3 << 'PYTHONEOF'
import sys
import os
sys.path.insert(0, '/opt/svqpanel')

from api.models.database import SessionLocal, load_all_models
load_all_models()
from api.models.models_user import User

session = SessionLocal()

admin_username = os.environ.get('SVQPANEL_ADMIN_USER', 'svqadmin')
admin_password = os.environ.get('SVQPANEL_ADMIN_PASS', 'changeme123')

try:
    # Idempotente: si ya existe un admin (por username o por role), no duplicar
    existing_admin = session.query(User).filter(
        (User.username == admin_username) | (User.role == "admin")
    ).first()
    if existing_admin:
        print(f"Admin user already exists: {existing_admin.username}")
        sys.exit(0)

    admin_user = User(
        username=admin_username,
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
echo "${ADMIN_USER}:${ADMIN_PASSWORD}" > /opt/svqpanel/.credentials/admin.txt
chmod 600 /opt/svqpanel/.credentials/admin.txt

echo -e "${GREEN}✓ Usuario administrador creado${NC}\n"

# Sembrar un plan global "Ilimitado" por defecto, listo para asignar a clientes
# desde el primer momento. Todos los límites a 0 = ilimitado. owner_id=NULL
# (plan global de admins). Idempotente: si ya existe, no lo duplica.
echo -e "${YELLOW}Creando plan por defecto (Ilimitado)...${NC}"
python3 << 'PLANEOF'
import sys
sys.path.insert(0, '/opt/svqpanel')
from api.models.database import SessionLocal, load_all_models
load_all_models()
from api.models.models_plan import Plan

session = SessionLocal()
try:
    existing = session.query(Plan).filter(
        Plan.owner_id.is_(None), Plan.name == "Ilimitado"
    ).first()
    if existing:
        print("Plan 'Ilimitado' ya existe")
    else:
        plan = Plan(
            name="Ilimitado",
            description="Plan sin límites — todos los recursos ilimitados",
            owner_id=None,            # plan global (admins)
            disk_quota_mb=0,          # 0 = ilimitado
            traffic_quota_mb_month=0,
            domains_limit=0,
            databases_limit=0,
            mailboxes_limit=0,
            dns_zones_limit=0,
            is_default=True,          # se aplica por defecto a nuevos usuarios
        )
        session.add(plan)
        session.commit()
        print("Plan 'Ilimitado' creado y marcado como default")
except Exception as e:
    print(f"Error creando plan por defecto: {e}")
    session.rollback()
finally:
    session.close()
PLANEOF

echo -e "${GREEN}✓ Plan por defecto listo${NC}\n"

###############################################################################
# 14. REGISTRAR IPs DEL SERVIDOR EN EL PANEL
###############################################################################
echo -e "${YELLOW}Registrando IPs del servidor en el panel...${NC}"
cd /opt/svqpanel
/opt/svqpanel/venv/bin/python -m api.cli register_server_ips && \
    echo -e "${GREEN}✓ IPs del servidor registradas automáticamente${NC}" || \
    echo -e "${YELLOW}⚠ No se pudieron registrar las IPs (se pueden añadir manualmente en el panel)${NC}"
echo ""

# Crear/actualizar pools PHP-FPM dedicados (open_basedir SIN /tmp global +
# sys_temp_dir + disable_functions + tmp propio del dominio) para cualquier
# dominio preexistente. --force reescribe también los pools que ya existían,
# para aplicar la política de aislamiento vigente en reinstalaciones.
echo -e "${YELLOW}Aplicando aislamiento PHP por dominio (open_basedir + tmp propio)...${NC}"
/opt/svqpanel/venv/bin/python -m api.cli migrate_php_pools --force && \
    echo -e "${GREEN}✓ Pools PHP-FPM con seguridad aplicados${NC}" || \
    echo -e "${YELLOW}⚠ migrate_php_pools tuvo incidencias (revisar logs)${NC}"
echo ""

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
echo "  Seguridad:    nftables (table inet svqpanel) + fail2ban$( [[ "$INSTALL_CROWDSEC" == true ]] && echo ' + CrowdSec' )"
echo "  Directorio:   /opt/svqpanel"
echo "  Base de datos panel: panel_db (PostgreSQL)"
echo -e "\n${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   SVQPanel - Credenciales de Administrador                 ║${NC}"
echo -e "${GREEN}╠════════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║${NC} Usuario:    ${YELLOW}${ADMIN_USER}${NC}"
echo -e "${GREEN}║${NC} Contraseña: ${YELLOW}$ADMIN_PASSWORD${NC}"
echo -e "${GREEN}║${NC} Email:      ${YELLOW}admin@localhost${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}\n"
# Iniciar servicio automáticamente
systemctl start svqpanel

# ── Detectar la IP pública del servidor para mostrarla en las URLs ──────────
# Prioridad: IP de salida hacia internet (ip route get) → primera IP global de
# hostname -I → servicio externo (por si hay NAT) → placeholder.
SERVER_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[\d.]+' | head -1)"
if [[ -z "$SERVER_IP" ]]; then
    SERVER_IP="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -vE '^(127\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.)' | head -1)"
fi
if [[ -z "$SERVER_IP" ]]; then
    SERVER_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
fi
[[ -z "$SERVER_IP" ]] && SERVER_IP="IP_DEL_SERVIDOR"

echo -e "Proximos pasos:"
echo "  1. Verifica el estado: systemctl status svqpanel"
echo "  2. Ver logs: journalctl -u svqpanel -f"
echo -e "\n${GREEN}SVQPanel estará disponible en:${NC}"
echo "  • Panel Web:    http://${SERVER_IP}:${PANEL_WEB_PORT}"
echo "  • Seguridad:    http://${SERVER_IP}:${PANEL_WEB_PORT}/security  (firewall, fail2ban, listas IP)"
echo "  • API Docs:     http://${SERVER_IP}:${PANEL_WEB_PORT}/docs"
echo -e "  ${YELLOW}Sugerencia de seguridad:${NC} cierra el puerto ${PANEL_WEB_PORT} en tu firewall"
echo "  perimetral (Proxmox, etc.) y ábrelo solo a tus IPs de administración."
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
    echo "  • Rspamd UI:     http://${SERVER_IP}:11334"
    echo "  • Buzones en:    /home/{usuario}/mail/{dominio}/{buzon}/"
    echo -e "  ${YELLOW}Configura por dominio: registro MX, rDNS (PTR), SPF, DKIM y DMARC${NC}"
fi
if [[ "$INSTALL_ROUNDCUBE" == true ]]; then
    echo -e "\n${YELLOW}Roundcube Webmail:${NC}"
    echo "  • URL:           http://${SERVER_IP}/webmail/"
    echo "  • Autologin:     botón ✉ junto a cada buzón en el panel"
    echo "  • Plugin:        svqpanel_autologin (instalado automáticamente)"
    echo "  • Credenciales:  /opt/svqpanel/.credentials/roundcube.txt"
fi

echo -e "\n${YELLOW}Seguridad (Fase 12):${NC}"
echo "  • UI:                  http://${SERVER_IP}/security"
echo "  • Firewall:            nftables (tabla 'inet svqpanel')"
echo "                         /etc/nftables.conf + /etc/nftables/svqpanel-*.nft"
echo "  • Brute-force:         fail2ban (sshd, recidive y más con correo)"
echo "                         /etc/fail2ban/jail.local"
echo "  • Listas IP (URL):     refresh diario via systemd timer"
echo "                         systemctl list-timers svqpanel-iplist-refresh.timer"
if [[ -n "$INSTALLER_IP" ]]; then
    echo "  • Anti-lockout:        $INSTALLER_IP ya está en whitelist y en ignoreip"
fi
if [[ "$INSTALL_CROWDSEC" == true ]]; then
    echo "  • CrowdSec:            cscli decisions list  /  cscli metrics"
    echo "                         UI panel → /security tab CrowdSec"
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
