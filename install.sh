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

# Recomendación: para instalaciones nuevas se prefiere Debian 13 (trixie).
# Debian 12 sigue soportado, pero conviene actualizarlo con
# scripts/dist_upgrade_debian13.sh (ver docs/UPGRADE_DEBIAN_12_A_13.md).
if [[ "$OS_VERSION" == "12" ]]; then
    echo -e "${YELLOW}⚠ Recomendado: Debian 13 para instalaciones nuevas. Debian 12 está soportado pero se aconseja actualizar.${NC}\n"
fi

###############################################################################
# 0. MODO DESATENDIDO (opcional) — instalación tipo Hestia por variables de entorno
###############################################################################
# Si SVQ_UNATTENDED=1 (o se define cualquier SVQ_*), el instalador NO pregunta:
# usa las variables de entorno y, las que falten, valores por defecto. Pensado
# para el generador de comandos (svqhost.com) y para automatizar.
#
#   Variables soportadas (todas opcionales):
#     SVQ_UNATTENDED=1            → no preguntar nada
#     SVQ_WEBSERVER=nginx|apache  → webserver (default: nginx)
#     SVQ_LICENSE=<clave>         → clave de licencia (default: vacía)
#     SVQ_PANEL_PORT=8083         → puerto del panel (default: 8083)
#     SVQ_HOSTNAME=panel.dom.com  → hostname + SSL auto (default: vacío = por IP)
#     SVQ_MAIL=yes|no             → servidor de correo (default: no)
#     SVQ_ROUNDCUBE=yes|no        → webmail (default: no; requiere SVQ_MAIL=yes)
#     SVQ_MARIADB=yes|no          → MariaDB para clientes (default: no)
#     SVQ_CROWDSEC=yes|no         → CrowdSec (default: yes)
#
# Ejemplo:
#   SVQ_UNATTENDED=1 SVQ_WEBSERVER=nginx SVQ_MAIL=yes SVQ_MARIADB=yes \
#     bash install.sh
UNATTENDED=false
if [[ "${SVQ_UNATTENDED:-}" == "1" || "${SVQ_UNATTENDED:-}" == "yes" ]]; then
    UNATTENDED=true
    echo -e "${GREEN}✓ Modo desatendido: usando variables de entorno (sin preguntas)${NC}\n"
fi
# Helper: normaliza un sí/no a true/false
_is_yes() { [[ "${1,,}" =~ ^(s|si|y|yes|1|true)$ ]]; }

###############################################################################
# 1. ELEGIR WEBSERVER
###############################################################################
if [[ "$UNATTENDED" == true || -n "${SVQ_WEBSERVER:-}" ]]; then
    # apache → opción 2 (Apache+Nginx); cualquier otra cosa → 1 (Nginx solo)
    if [[ "${SVQ_WEBSERVER,,}" == "apache" || "${SVQ_WEBSERVER,,}" == "apache+nginx" ]]; then
        WEBSERVER_CHOICE=2
    else
        WEBSERVER_CHOICE=1
    fi
else
    echo -e "${YELLOW}¿Qué webserver necesitas?${NC}"
    echo "1) Nginx solo"
    echo "2) Apache + Nginx (Apache para legacy, Nginx para velocidad)"
    printf "Elige (1 o 2): "; read WEBSERVER_CHOICE </dev/tty
fi

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
# 1a-bis. LICENCIA DEL PANEL
###############################################################################
# SVQPanel requiere una licencia (obtenla en tu área de cliente de svqhost.com).
# Sin licencia válida el panel se instala pero arranca en modo limitado (puedes
# verlo y activar la licencia desde Sistema → Licencia, pero no operar).
if [[ "$UNATTENDED" == true || -n "${SVQ_LICENSE:-}" ]]; then
    _LICENSE_INPUT="${SVQ_LICENSE:-}"
else
    echo -e "${YELLOW}Licencia de SVQPanel${NC}"
    echo "  Obtén tu clave en tu área de cliente de https://www.svqhost.com"
    echo "  (puedes dejarlo vacío ahora y activarla luego desde el panel)"
    printf "Clave de licencia [Enter para omitir]: "; read _LICENSE_INPUT </dev/tty
fi
if [ -n "$_LICENSE_INPUT" ]; then
    echo "$_LICENSE_INPUT" > /etc/svqpanel/license
    chmod 600 /etc/svqpanel/license
    echo -e "${GREEN}✓ Licencia guardada (se validará al arrancar el panel)${NC}"
else
    touch /etc/svqpanel/license
    chmod 600 /etc/svqpanel/license
    echo -e "${YELLOW}⚠ Sin licencia: el panel arrancará en modo limitado hasta activarla${NC}"
fi

###############################################################################
# 1b. PUERTO DEL PANEL
###############################################################################
# El panel se sirve en un puerto dedicado (no 80/443) para poder cerrarlo
# selectivamente en el firewall perimetral (Proxmox, etc.) y dejar 80/443
# libres para los sitios web de los clientes.
if [[ "$UNATTENDED" == true || -n "${SVQ_PANEL_PORT:-}" ]]; then
    _PANEL_PORT_INPUT="${SVQ_PANEL_PORT:-}"
else
    echo -e "${YELLOW}¿En qué puerto quieres servir el panel de control?${NC}"
    echo "  Recomendado: 8083 (cierra solo este puerto en tu firewall para máxima seguridad)"
    printf "Puerto del panel [8083]: "; read _PANEL_PORT_INPUT </dev/tty
fi
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
# 1c. HOSTNAME DEL PANEL + SSL AUTOMÁTICO (OPCIONAL)
###############################################################################
# Si el usuario da un hostname (FQDN) que ya apunta por DNS a la IP de este
# servidor, al final de la instalación se emitirá automáticamente el certificado
# SSL Let's Encrypt y el panel quedará en HTTPS. Si lo omite o el DNS no apunta
# todavía, el panel queda en HTTP y el SSL se puede emitir luego desde el panel.
PANEL_HOSTNAME=""
PANEL_SSL_READY=false

# Detectar la IP pública del servidor para comparar con el DNS del hostname.
# Prioriza la IP pública real (descarta privadas); si no, usa un servicio externo.
_detect_server_ip() {
    local ip
    ip="$(hostname -I 2>/dev/null | tr ' ' '\n' \
          | grep -vE '^(127\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.|169\.254\.)' \
          | head -1)"
    if [[ -z "$ip" ]]; then
        ip="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)"
    fi
    echo "$ip"
}
_INSTALL_SERVER_IP="$(_detect_server_ip)"

if [[ "$UNATTENDED" == true || -n "${SVQ_HOSTNAME:-}" ]]; then
    _PANEL_HOSTNAME_INPUT="${SVQ_HOSTNAME:-}"
else
    echo -e "${YELLOW}¿Quieres acceder al panel por un dominio con HTTPS?${NC}"
    echo "  Si tienes un dominio (ej: panel.midominio.com) apuntando a este servidor,"
    echo "  el instalador emitirá el certificado SSL automáticamente."
    echo "  Deja en blanco para acceder por IP:puerto (puedes emitir el SSL después)."
    printf "Hostname del panel [Enter para omitir]: "; read _PANEL_HOSTNAME_INPUT </dev/tty
fi
_PANEL_HOSTNAME_INPUT="$(echo "$_PANEL_HOSTNAME_INPUT" | tr -d ' ' | tr 'A-Z' 'a-z')"

if [[ -n "$_PANEL_HOSTNAME_INPUT" ]]; then
    # Validar que sea un FQDN razonable
    if [[ "$_PANEL_HOSTNAME_INPUT" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$ ]]; then
        PANEL_HOSTNAME="$_PANEL_HOSTNAME_INPUT"
        echo -e "${GREEN}✓ Hostname válido: $PANEL_HOSTNAME${NC}"

        # Comprobar que el DNS del hostname resuelve a la IP del servidor
        echo "  Comprobando DNS de $PANEL_HOSTNAME ..."
        _RESOLVED_IPS="$(getent ahostsv4 "$PANEL_HOSTNAME" 2>/dev/null | awk '{print $1}' | sort -u)"
        if [[ -z "$_RESOLVED_IPS" ]]; then
            _RESOLVED_IPS="$(dig +short A "$PANEL_HOSTNAME" 2>/dev/null | grep -E '^[0-9.]+$')"
        fi

        if [[ -n "$_INSTALL_SERVER_IP" ]] && echo "$_RESOLVED_IPS" | grep -qx "$_INSTALL_SERVER_IP"; then
            PANEL_SSL_READY=true
            echo -e "${GREEN}✓ $PANEL_HOSTNAME apunta a este servidor ($_INSTALL_SERVER_IP). Se emitirá SSL automáticamente.${NC}\n"
        else
            echo -e "${YELLOW}⚠ $PANEL_HOSTNAME no resuelve a la IP de este servidor.${NC}"
            echo -e "${YELLOW}    IP del servidor : ${_INSTALL_SERVER_IP:-desconocida}${NC}"
            echo -e "${YELLOW}    DNS resuelve a  : ${_RESOLVED_IPS:-(sin registro A)}${NC}"
            echo -e "${YELLOW}    El panel quedará en HTTP. Configura el DNS y emite el SSL después${NC}"
            echo -e "${YELLOW}    desde Configuración → SSL del Panel cuando el DNS propague.${NC}\n"
        fi
    else
        echo -e "${YELLOW}⚠ '$_PANEL_HOSTNAME_INPUT' no es un FQDN válido. Se ignora; el panel será accesible por IP.${NC}\n"
    fi
else
    echo -e "${GREEN}✓ Sin hostname: el panel será accesible por IP:$PANEL_WEB_PORT${NC}\n"
fi

###############################################################################
# 2b. SERVIDOR DE CORREO (OPCIONAL)
###############################################################################
if [[ "$UNATTENDED" == true || -n "${SVQ_MAIL:-}" ]]; then
    _MAIL_INPUT="${SVQ_MAIL:-no}"
else
    echo -e "${YELLOW}¿Instalar servidor de correo electrónico?${NC}"
    echo "  Stack: Postfix (SMTP) + Dovecot (IMAP/POP3) + Rspamd (antispam/DKIM) + Redis"
    echo -e "  ${YELLOW}Requisitos: IP con rDNS configurado, puerto 25 desbloqueado, registro MX${NC}"
    printf "¿Instalar correo? (s/N): "; read _MAIL_INPUT </dev/tty
fi
INSTALL_MAIL=false
if _is_yes "$_MAIL_INPUT"; then
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
    if [[ "$UNATTENDED" == true || -n "${SVQ_ROUNDCUBE:-}" ]]; then
        _RC_INPUT="${SVQ_ROUNDCUBE:-no}"
    else
        echo -e "${YELLOW}¿Instalar Roundcube Webmail?${NC}"
        echo "  Webmail en /webmail — autologin desde el panel (1 clic por buzón)"
        printf "¿Instalar Roundcube? (s/N): "; read _RC_INPUT </dev/tty
    fi
    if _is_yes "$_RC_INPUT"; then
        INSTALL_ROUNDCUBE=true
        echo -e "${GREEN}✓ Roundcube seleccionado${NC}\n"
    else
        echo -e "${YELLOW}✗ Sin Roundcube${NC}\n"
    fi
fi

###############################################################################
# 2c. BASE DE DATOS PARA CLIENTES (MariaDB — opcional)
###############################################################################
if [[ "$UNATTENDED" == true || -n "${SVQ_MARIADB:-}" ]]; then
    _MARIADB_INPUT="${SVQ_MARIADB:-no}"
else
    echo -e "${YELLOW}¿Instalar MariaDB para bases de datos de clientes?${NC}"
    echo "  Los clientes podrán crear BDs MySQL/MariaDB para sus aplicaciones"
    echo "  (WordPress, Joomla, PrestaShop, Laravel, etc.)"
    echo -e "  Se instala MariaDB ${YELLOW}11.4 LTS${NC} desde el repositorio oficial."
    printf "¿Instalar MariaDB? (s/N): "; read _MARIADB_INPUT </dev/tty
fi
INSTALL_MARIADB=false
if _is_yes "$_MARIADB_INPUT"; then
    INSTALL_MARIADB=true
    echo -e "${GREEN}✓ MariaDB seleccionado${NC}\n"
else
    echo -e "${YELLOW}✗ Sin MariaDB para clientes${NC}\n"
fi

###############################################################################
# 2d. CROWDSEC (IPS colaborativo) — recomendado
###############################################################################
# Default 'yes' (recomendado): en desatendido se instala salvo SVQ_CROWDSEC=no.
if [[ "$UNATTENDED" == true || -n "${SVQ_CROWDSEC:-}" ]]; then
    _CS_INPUT="${SVQ_CROWDSEC:-yes}"
else
    echo -e "${YELLOW}¿Instalar CrowdSec?${NC} ${GREEN}(recomendado)${NC}"
    echo "  IPS colaborativo: detecta ataques desde logs (sshd, nginx, postfix...)"
    echo "  y aplica bans via bouncer de nftables. Complementa a fail2ban con una"
    echo "  blocklist comunitaria opcional. Footprint: ~80 MB RAM."
    printf "¿Instalar CrowdSec? (S/n): "; read _CS_INPUT </dev/tty
fi
INSTALL_CROWDSEC=true
if [[ "${_CS_INPUT,,}" =~ ^(n|no|0|false)$ ]]; then
    INSTALL_CROWDSEC=false
    echo -e "${YELLOW}✗ Sin CrowdSec${NC}\n"
else
    echo -e "${GREEN}✓ CrowdSec seleccionado${NC}\n"
fi

###############################################################################
# 2. ELEGIR VERSIONES PHP
###############################################################################
if [[ "$UNATTENDED" == true || -n "${SVQ_PHP:-}" ]]; then
    # Default 8.3 si no se especifica (versiones separadas por espacio o coma)
    PHP_VERSIONS="$(echo "${SVQ_PHP:-8.3}" | tr ',' ' ')"
else
    echo -e "${YELLOW}¿Qué versiones PHP necesitas?${NC}"
    echo "Disponibles: 7.3, 7.4, 8.0, 8.1, 8.2, 8.3, 8.4, 8.5 (7.3/7.4/8.0/8.1 EOL, sin soporte)"
    echo "Ejemplos: '8.1 8.2' o '8.5' (mínimo 1, máximo 6)"
    printf "Versiones PHP (separadas por espacio): "; read PHP_VERSIONS </dev/tty
fi

# Validar que haya al menos una versión
if [[ -z "$PHP_VERSIONS" ]]; then
    echo -e "${RED}Debes elegir al menos una versión PHP${NC}"
    exit 1
fi

# Convertir a array y validar
mapfile -t PHP_ARRAY <<< "$(echo "$PHP_VERSIONS" | tr ' ' '\n')"
VALID_VERSIONS=("7.3" "7.4" "8.0" "8.1" "8.2" "8.3" "8.4" "8.5")
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
    echo -e "${YELLOW}Solo están disponibles: 7.3, 7.4, 8.0, 8.1, 8.2, 8.3, 8.4, 8.5${NC}"
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

# Prerequisitos MÍNIMOS antes de añadir repos externos. En un Debian minimal
# 'gpg' (gnupg) y 'curl' NO vienen de serie, y los repos PGDG/nginx/rspamd/sury
# usan 'curl ... | gpg --dearmor' para sus claves. Sin esto, la instalación
# fallaba con "gpg: command not found" al añadir el repo de PostgreSQL.
echo -e "${YELLOW}Instalando prerequisitos (gnupg, curl)...${NC}"
apt-get install -y -qq -o Dpkg::Options::="--force-confold" \
    gnupg ca-certificates curl wget apt-transport-https
echo -e "${GREEN}✓ Prerequisitos instalados${NC}\n"

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
# 4. REPO PGDG — PostgreSQL oficial (versión más reciente estable)
###############################################################################
echo -e "${YELLOW}Añadiendo repo PostgreSQL oficial (PGDG)...${NC}"
mkdir -p /usr/share/keyrings   # puede no existir en un Debian minimal
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    | gpg --yes --dearmor -o /usr/share/keyrings/postgresql-archive-keyring.gpg
case "$OS_VERSION" in
    12) _PG_CODENAME="bookworm-pgdg" ;;
    13) _PG_CODENAME="trixie-pgdg" ;;
esac
echo "deb [signed-by=/usr/share/keyrings/postgresql-archive-keyring.gpg] \
https://apt.postgresql.org/pub/repos/apt ${_PG_CODENAME} main" \
    > /etc/apt/sources.list.d/pgdg.list
apt-get update -qq
echo -e "${GREEN}✓ Repo PGDG añadido${NC}\n"

###############################################################################
# 5. INSTALAR DEPENDENCIAS BASE
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
    cron \
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
    restic \
    quota \
    quotatool \
    mailutils

# El daemon cron es IMPRESCINDIBLE: los cronjobs de cliente se escriben a
# /var/spool/cron/crontabs/{user} y los ejecuta cron. Sin él, nada programado
# corre (ni crons de cliente ni tareas del panel). Habilitar + arrancar.
systemctl enable --now cron 2>/dev/null || true

# Wrapper de historial de cron (svq-cron-run) + cola en disco (1733): cada
# ejecución de cron registra estado/duración/salida sin que el cliente toque BD.
(cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -c \
  "from scripts.cron_manager import install_cron_wrapper; install_cron_wrapper()" 2>/dev/null) || true

echo -e "${GREEN}✓ Dependencias instaladas${NC}\n"

###############################################################################
# 5b. ACTIVAR CUOTAS DE DISCO POR USUARIO (kernel quota, estilo cPanel)
###############################################################################
# El sistema de cuotas del kernel impide físicamente que un usuario escriba más
# de su límite de disco (el write falla con "Disk quota exceeded"). El panel
# fija los límites con setquota a partir del plan de cada usuario.
#
# Requiere montar el filesystem con la opción usrquota. Aplicamos la cuota sobre
# /home si es su propia partición, o sobre / en caso contrario.
echo -e "${YELLOW}Activando sistema de cuotas de disco (ext4 interno: user+group+project)...${NC}"

# Cuotas ext4 en modo FEATURE INTERNO (journalled), con los TRES tipos:
#   - user/group: límite de disco por cuenta (estilo cPanel).
#   - PROJECT: para que el CORREO (que vive en /home/{u}/mail con owner vmail)
#     cuente en el disco del usuario. Sin project quota, el correo no se sumaría.
# El feature 'project' de ext4 solo se puede activar con el FS DESMONTADO, así que
# lo hacemos vía un hook del initramfs en el primer arranque (igual para / o /home).
QUOTA_MOUNT="/"
mountpoint -q /home && QUOTA_MOUNT="/home"
QUOTA_DEV="$(findmnt -no SOURCE "$QUOTA_MOUNT" 2>/dev/null)"
echo "  Montaje: $QUOTA_MOUNT ($QUOTA_DEV)"

cp /etc/fstab /etc/fstab.svqpanel.bak

# fstab: opción 'prjquota' (modo interno). El feature 'quota' del FS activa
# user/group internas al montar; no se usan ficheros externos aquota.*.
python3 - "$QUOTA_MOUNT" << 'FSTABEOF'
import sys
mount = sys.argv[1]
with open("/etc/fstab") as f:
    lines = f.readlines()
out, changed = [], False
for line in lines:
    if line.strip().startswith("#") or not line.strip():
        out.append(line); continue
    parts = line.split()
    if len(parts) >= 4 and parts[1] == mount and "ext4" in parts[2]:
        opts = [o for o in parts[3].split(",") if o not in ("usrquota", "grpquota")]
        if "prjquota" not in opts:
            opts.append("prjquota"); changed = True
        parts[3] = ",".join(opts)
        out.append("\t".join(parts) + "\n")
    else:
        out.append(line)
if changed:
    with open("/etc/fstab", "w") as f:
        f.writelines(out)
    print("  fstab: prjquota (modo interno ext4)")
else:
    print("  fstab ya en modo prjquota")
FSTABEOF

# Hook del initramfs: activa los features quota internos (user/group/project) en
# el primer arranque, con el FS aún desmontado (única forma de tocar 'project').
cat > /etc/initramfs-tools/scripts/init-premount/svq-quota <<'HOOKEOF'
#!/bin/sh
PREREQ=""; prereqs() { echo "$PREREQ"; }
case "$1" in prereqs) prereqs; exit 0;; esac
. /scripts/functions
ROOTDEV=""
for x in $(cat /proc/cmdline); do case "$x" in root=*) ROOTDEV="${x#root=}";; esac; done
case "$ROOTDEV" in PARTUUID=*|UUID=*) ROOTDEV="$(blkid -l -t "$ROOTDEV" -o device 2>/dev/null)";; esac
[ -b "$ROOTDEV" ] || exit 0
tune2fs -l "$ROOTDEV" 2>/dev/null | grep -q "User quota inode" && exit 0
log_begin_msg "SVQPanel: activando cuotas ext4 internas (user/group/project)"
e2fsck -f -y "$ROOTDEV" >/dev/null 2>&1
tune2fs -O ^quota "$ROOTDEV" >/dev/null 2>&1
tune2fs -Q usrquota,grpquota,prjquota "$ROOTDEV" >/dev/null 2>&1
e2fsck -f -y "$ROOTDEV" >/dev/null 2>&1
log_end_msg
exit 0
HOOKEOF
chmod +x /etc/initramfs-tools/scripts/init-premount/svq-quota

# Hook que mete tune2fs/e2fsck/blkid en el initramfs.
cat > /etc/initramfs-tools/hooks/svq-quota-bins <<'HOOKEOF'
#!/bin/sh
PREREQ=""; prereqs() { echo "$PREREQ"; }
case "$1" in prereqs) prereqs; exit 0;; esac
. /usr/share/initramfs-tools/hook-functions
copy_exec /usr/sbin/tune2fs /sbin
copy_exec /usr/sbin/e2fsck /sbin
copy_exec /usr/sbin/blkid /sbin
HOOKEOF
chmod +x /etc/initramfs-tools/hooks/svq-quota-bins

update-initramfs -u >/dev/null 2>&1 || true
echo -e "${GREEN}✓ Cuotas ext4 internas configuradas (se activan en el primer reinicio).${NC}\n"

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
    curl -fsSL https://nginx.org/keys/nginx_signing.key | gpg --yes --dearmor \
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

    # GoAccess: informes de visitas por dominio (estadísticas web del panel).
    apt-get install -y -qq goaccess 2>/dev/null || true

    # El nginx del repo oficial NO incluye sites-enabled por defecto y
    # corre los workers como 'nginx' en vez de 'www-data' (Debian).
    # Ambas cosas deben corregirse para compatibilidad con la estructura SVQPanel.
    if ! grep -q "sites-enabled" /etc/nginx/nginx.conf; then
        sed -i 's|include /etc/nginx/conf.d/\*.conf;|include /etc/nginx/conf.d/*.conf;\n    include /etc/nginx/sites-enabled/*;|' /etc/nginx/nginx.conf
    fi
    # Worker user -> www-data (todos los permisos de dominios se dan a www-data)
    sed -i 's/^user  nginx;/user www-data;/' /etc/nginx/nginx.conf
    mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled /etc/nginx/snippets

    # fastcgi-php.conf — incluido por nginx-full en Debian pero no por nginx básico.
    # Siempre se sobreescribe para garantizar que la versión instalada es la correcta.
    cat > /etc/nginx/snippets/fastcgi-php.conf << 'FCGIEOF'
# Sets $path_info from the $fastcgi_path_info variable
fastcgi_split_path_info ^(.+?\.php)(/.*)$;
# Check that the PHP script exists before passing it
try_files $fastcgi_script_name =404;
# Bypass the fact that try_files resets $fastcgi_path_info
set $path_info $fastcgi_path_info;
fastcgi_param PATH_INFO $path_info;
fastcgi_index index.php;
include fastcgi_params;
fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
FCGIEOF

    # Endurecimiento global: ocultar la versión de nginx (server_tokens off)
    cat > /etc/nginx/conf.d/svqpanel-hardening.conf << 'NGINXHARDEOF'
# SVQPanel — endurecimiento global de nginx
server_tokens off;
NGINXHARDEOF

    # Bad bots: map base. Los vhosts consultan $bad_bot (if ($bad_bot) return 444),
    # así que este map DEBE existir o nginx no arranca. El panel lo reescribe con
    # los patrones elegidos en Seguridad → Bloqueo de bots; aquí solo el default.
    if [[ ! -f /etc/nginx/conf.d/bad-bots.conf ]]; then
        cat > /etc/nginx/conf.d/bad-bots.conf << 'NGINXBADBOTSEOF'
# Generado por SVQPanel — Bad Bots Blocker
# No editar manualmente
map $http_user_agent $bad_bot {
    default 0;
}
NGINXBADBOTSEOF
    fi

    # stub_status: endpoint interno (solo 127.0.0.1) para el monitor del panel.
    # Expone conexiones activas, accepted/handled/requests, reading/writing/waiting.
    cat > /etc/nginx/conf.d/svqpanel-status.conf << 'NGINXSTATUSEOF'
# SVQPanel — métricas internas de nginx (solo localhost)
server {
    listen 127.0.0.1:8089;
    server_name _;
    access_log off;
    location = /nginx_status {
        stub_status;
        allow 127.0.0.1;
        deny all;
    }
}
NGINXSTATUSEOF

    systemctl start nginx
    echo -e "${GREEN}✓ Nginx $(nginx -v 2>&1) instalado desde repo oficial${NC}\n"
fi

if [[ "$WEBSERVER" == "apache+nginx" ]]; then
    echo -e "${YELLOW}Instalando Apache (backend para .htaccess)...${NC}"
    apt-get install -y -qq apache2

    # ── Arquitectura: Nginx FRONT (80/443) + Apache BACKEND (8181) ──
    # Nginx maneja SSL, HTTP/3, headers de seguridad, bad bots y sirve los
    # dominios "nginx" directamente. Para los dominios "apache", Nginx hace
    # proxy_pass a Apache (127.0.0.1:8181), que sirve el PHP RESPETANDO los
    # ficheros .htaccess (mod_rewrite, deny/allow, auth básica, etc.) — el
    # único motivo real para tener Apache. Apache NO escucha de cara a internet.

    # Módulos: rewrite (.htaccess), proxy_fcgi (PHP-FPM), remoteip (IP real
    # del visitante a través del proxy nginx), headers (por si un .htaccess los usa).
    a2enmod rewrite
    a2enmod headers
    a2enmod expires       # cache de navegador para estáticos (mod_expires)
    a2enmod proxy
    a2enmod proxy_fcgi
    a2enmod setenvif
    a2enmod remoteip

    # Apache escucha SOLO en 127.0.0.1:8181 (no expuesto a internet).
    cat > /etc/apache2/ports.conf << 'APACHEPORTS'
# SVQPanel — Apache es BACKEND de Nginx. Solo escucha en localhost:8181.
# Nginx (front) hace proxy_pass aquí para los dominios servidos por Apache.
Listen 127.0.0.1:8181
APACHEPORTS

    # RemoteIP: confiar en la X-Forwarded-For que envía nginx (front local),
    # para que Apache y los .htaccess vean la IP real del visitante, no 127.0.0.1.
    #
    # SetEnvIf X-Forwarded-Proto: nginx termina el SSL y habla con Apache por
    # HTTP plano (127.0.0.1:8181). Sin esto, PHP ve $_SERVER['HTTPS'] vacío y
    # WordPress/PrestaShop/etc. creen estar en HTTP → redirigen a HTTPS, pero
    # nginx ya servía HTTPS → bucle ERR_TOO_MANY_REDIRECTS. Traducimos la
    # cabecera que envía nginx a la variable estándar HTTPS=on para que la app
    # sepa que la conexión original es segura.
    cat > /etc/apache2/conf-available/svqpanel-remoteip.conf << 'APACHEREMOTEIP'
RemoteIPHeader X-Forwarded-For
RemoteIPTrustedProxy 127.0.0.1
# Log con la IP real (remoteip) en vez de la del proxy
LogFormat "%a %l %u %t \"%r\" %>s %O \"%{Referer}i\" \"%{User-Agent}i\"" svq_combined
# Propagar HTTPS desde el front nginx (evita bucles de redirección a HTTPS)
SetEnvIf X-Forwarded-Proto "https" HTTPS=on
APACHEREMOTEIP
    a2enconf svqpanel-remoteip

    # Quitar el vhost por defecto de Apache (000-default escucha en *:80 y
    # chocaría con nginx). Con ports.conf en 8181 ya no escucha en 80, pero
    # deshabilitamos el default igualmente por limpieza.
    a2dissite 000-default 2>/dev/null || true
    a2dissite default-ssl 2>/dev/null || true

    # Endurecer: ocultar versión de Apache
    cat > /etc/apache2/conf-available/svqpanel-security.conf << 'APACHESEC'
ServerTokens Prod
ServerSignature Off
TraceEnable Off
APACHESEC
    a2enconf svqpanel-security

    apache2ctl configtest && systemctl enable apache2 && systemctl restart apache2
    echo -e "${GREEN}✓ Apache instalado como backend (127.0.0.1:8181)${NC}\n"
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

# Endurecer named: nameserver AUTORITATIVO, SIN recursión. Sin esto BIND recurre
# por defecto → "open resolver" usable para amplificación DDoS contra terceros
# (y acaba en listas negras). Responde sus zonas a todo Internet, pero no recurre.
cat > /etc/bind/named.conf.options <<'NAMEDOPTS'
options {
	version "none";
	directory "/var/cache/bind";
	dnssec-validation auto;
	listen-on-v6 { any; };

	// Autoritativo puro: sin recursión (evita open resolver / amplificación).
	recursion no;
	allow-query { any; };
	allow-recursion { none; };
	allow-query-cache { none; };
};
NAMEDOPTS
named-checkconf 2>/dev/null && rndc reload 2>/dev/null || systemctl restart named 2>/dev/null || true

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

# Forzar named a resolver SOLO por IPv4 si el servidor no tiene IPv6 saliente.
# Si no, named intenta los NS por IPv6, falla con "network unreachable" e inunda
# el log (sobre todo desde que Rspamd usa este BIND para las DNSBL). Resuelve
# igual por IPv4, solo que ensucia; con -4 ni lo intenta.
if ! ping6 -c1 -W2 2606:4700:4700::1111 >/dev/null 2>&1; then
    if [[ -f /etc/default/named ]] && ! grep -q '\-4' /etc/default/named; then
        sed -i 's/^OPTIONS="\(.*\)"/OPTIONS="\1 -4"/' /etc/default/named
        echo -e "    ${GREEN}✓ named en modo IPv4 (sin IPv6 saliente)${NC}"
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

    # Tamaño máximo de mensaje: 25 MB (como Gmail). Postfix trae 10 MB por
    # defecto, que se queda corto para adjuntos. Ajustable después desde el
    # panel (Configuración → Email → Tamaño máximo de mensaje).
    postconf -e "message_size_limit = 26214400"

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

    # SMTPS (puerto 465, SSL/TLS directo) — los clientes de correo modernos
    # (Thunderbird, Apple Mail, Outlook) prefieren SSL directo en 465 sobre
    # STARTTLS en 587. Ambos cifran igual, pero ofrecer 465 hace que el
    # autoconfig de Thunderbird muestre "SSL/TLS" en el saliente (como cPanel/
    # Hestia). Mantenemos también el 587 para máxima compatibilidad.
    if ! grep -qE "^smtps|^465" /etc/postfix/master.cf; then
        cat >> /etc/postfix/master.cf << 'MASTEREOF'

smtps     inet  n       -       y       -       -       smtpd
  -o syslog_name=postfix/smtps
  -o smtpd_tls_wrappermode=yes
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
    echo -e "  ${GREEN}✓ Postfix configurado (SMTP 25 + submission 587 + smtps 465 + relay listo)${NC}"

    # ── 2. DOVECOT ────────────────────────────────────────────────────────
    echo -e "  ${YELLOW}→ Instalando Dovecot...${NC}"
    # dovecot-sieve: necesario para el aprendizaje de spam (IMAPSieve dispara
    # rspamc learn_spam/learn_ham al mover correos a/desde la carpeta Junk).
    apt-get install -y -qq dovecot-core dovecot-imapd dovecot-pop3d dovecot-lmtpd \
        dovecot-sieve

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
        | gpg --yes --dearmor > /usr/share/keyrings/rspamd-archive-keyring.gpg
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

    # Greylisting activado. El módulo se llama 'greylist' → el fichero debe ser
    # greylist.conf (greylisting.conf NO lo lee Rspamd). El panel lo activa/
    # desactiva globalmente desde aquí (Settings.greylisting_enabled).
    cat > /etc/rspamd/local.d/greylist.conf << 'RSPAMDGREYEOF'
# SVQPanel — greylisting global. NO editar manualmente.
enabled = true;
RSPAMDGREYEOF
    # Limpiar el nombre antiguo erróneo si existe de instalaciones previas.
    rm -f /etc/rspamd/local.d/greylisting.conf 2>/dev/null || true

    # ── Resolver DNS propio para Rspamd (unbound) ─────────────────────────
    # CLAVE para el antispam: Rspamd necesita resolver DNS (SPF, DKIM, DMARC,
    # listas negras RBL). NO puede usar el 'named' del cluster DNS porque ese es
    # autoritativo y tiene 'recursion no' (rechaza dominios externos → REFUSED →
    # SPF/DKIM/DMARC/RBL caídos). Montamos unbound como resolver recursivo
    # cacheante SOLO en localhost:5353 (NO es open resolver: no escucha en la IP
    # pública). Rspamd apunta ahí.
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq unbound 2>/dev/null || true
    systemctl disable unbound-resolvconf 2>/dev/null || true
    systemctl stop unbound-resolvconf 2>/dev/null || true
    cat > /etc/unbound/unbound.conf.d/svqpanel.conf << 'UNBOUNDEOF'
# SVQPanel — resolver recursivo cacheante SOLO localhost para Rspamd (antispam).
# Puerto 5353 para no chocar con named (DNS autoritativo del cluster en :53).
# NO es open resolver: solo escucha e atiende a 127.0.0.1/::1.
server:
    port: 5353
    interface: 127.0.0.1@5353
    interface: ::1@5353
    access-control: 127.0.0.0/8 allow
    access-control: ::1 allow
    do-ip6: yes
    prefetch: yes
    cache-min-ttl: 60
    cache-max-ttl: 86400
    hide-identity: yes
    hide-version: yes
UNBOUNDEOF
    systemctl enable unbound 2>/dev/null || true
    systemctl restart unbound 2>/dev/null || true
    # Apuntar Rspamd a unbound (en vez del 127.0.0.1:53 de named).
    cat > /etc/rspamd/local.d/options.inc << 'RSPAMDDNSEOF'
dns {
  nameserver = ["127.0.0.1:5353"];
  timeout = 1s;
  sockets = 16;
  retransmits = 5;
}
RSPAMDDNSEOF

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

// SMTP (Postfix submission, puerto 587 con STARTTLS)
\$config['smtp_host']      = 'tls://localhost:587';
\$config['smtp_user']      = '%u';
\$config['smtp_pass']      = '%p';
\$config['smtp_auth_type'] = 'PLAIN';
// Roundcube y Postfix estan en la MISMA maquina: el cert es del hostname real
// (no de 'localhost'), asi que no verificamos el certificado en esta conexion
// local (el trafico nunca sale del servidor). Sin esto, STARTTLS falla con
// "Peer certificate CN did not match expected CN=localhost".
\$config['smtp_conn_options'] = array(
    'ssl' => array(
        'verify_peer'       => false,
        'verify_peer_name'  => false,
        'allow_self_signed' => true,
    ),
);

// Panel
\$config['product_name']   = 'Webmail';
\$config['support_url']    = '';
\$config['des_key']         = '${RC_DES_KEY}';

// Plugins: autologin SVQPanel + utilidades. markasjunk da el botón Spam/No-spam;
// zipdownload baja varios adjuntos en ZIP; archive añade botón Archivar;
// attachment_reminder avisa si mencionas un adjunto y no lo pusiste.
\$config['plugins'] = ['svqpanel_autologin', 'markasjunk', 'zipdownload', 'archive', 'attachment_reminder'];

// Skin
\$config['skin']             = 'elastic';
\$config['auto_create_user'] = true;
\$config['login_autocomplete'] = 2;

// Zona horaria por defecto para TODAS las cuentas (España peninsular). Sin esto,
// Roundcube usa 'auto' → suele quedar en UTC y las fechas salen 1-2h atrasadas.
// El usuario puede sobreescribirla en Ajustes → Preferencias → Fecha y hora.
\$config['timezone'] = 'Europe/Madrid';

// Carpetas especiales (IMAP standard)
\$config['sent_mbox']   = 'Sent';
\$config['trash_mbox']  = 'Trash';
\$config['drafts_mbox'] = 'Drafts';
# Junk = carpeta de spam canónica del sistema (Dovecot special_use \\Junk y a la
# que está enganchado el aprendizaje imapsieve de Rspamd). NO usar 'Spam': sería
# una carpeta paralela que el filtro no aprende. Roundcube la muestra traducida
# como "Correo no deseado".
\$config['junk_mbox']   = 'Junk';
\$config['create_default_folders'] = true;

// ── markasjunk: botón Spam/No-spam ──
// Sin driver de learning propio: el botón solo MUEVE el correo a Junk (y de Junk
// a Inbox para "no es spam"). El aprendizaje Bayes lo dispara el imapsieve del
// sistema al entrar/salir de Junk (learn-spam/learn-ham), así no duplicamos la
// lógica de entrenamiento ni exponemos rspamc al webmail.
\$config['markasjunk_learning_driver'] = null;
\$config['markasjunk_read_spam']       = true;   // marcar leído al mover a Junk
\$config['markasjunk_unread_ham']      = false;
\$config['markasjunk_spam_mbox']       = 'Junk';
\$config['markasjunk_ham_mbox']        = 'INBOX';
// archive: carpeta destino del botón Archivar
\$config['archive_mbox'] = 'Archive';

// Tamaño máx. de adjunto por webmail. Acompaña al message_size_limit de Postfix
// (25 MB por defecto) + margen base64 (~40%). Lo mantiene sincronizado el panel
// (Configuración → Email → Tamaño máximo de mensaje → WebmailManager.sync_upload_limit).
\$config['max_message_size'] = 36700160; // 35 MB
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

    if [[ -f /opt/svqpanel/scripts/svqpanel_autologin.php ]]; then
        cp /opt/svqpanel/scripts/svqpanel_autologin.php \
           "${RC_PLUGIN_DIR}/svqpanel_autologin.php"
    else
        # El repo aún no está clonado — descargarlo directamente desde GitHub
        curl -fsSL "https://raw.githubusercontent.com/coriaweb/SVQPanel/main/scripts/svqpanel_autologin.php" \
            -o "${RC_PLUGIN_DIR}/svqpanel_autologin.php"
    fi
    echo -e "  ${GREEN}✓ Plugin svqpanel_autologin instalado${NC}"

    # ── 8. Permisos finales ────────────────────────────────────────────────
    chown -R www-data:www-data "${RC_APP_DIR}/config" \
                               "${RC_APP_DIR}/temp" \
                               "${RC_APP_DIR}/logs"

    # ── 8b. Límite de subida del webmail en PHP ─────────────────────────────
    # El webmail (Roundcube) sube los adjuntos por HTTP→PHP antes de que lleguen
    # a Postfix; el PHP de fábrica trae upload_max_filesize=2M, así que el cliente
    # no puede adjuntar aunque el correo admita 25 MB. Subimos el límite de PHP
    # (con margen base64) para que acompañe al message_size_limit de Postfix.
    # Drop-in en cada versión de PHP-FPM instalada (idempotente).
    for _confd in /etc/php/*/fpm/conf.d; do
        [[ -d "$_confd" ]] || continue
        cat > "${_confd}/zz-svqpanel-webmail.ini" << 'RCPHPEOF'
; SVQPanel — límite de subida del webmail (Roundcube).
; Acompaña al message_size_limit de Postfix + margen base64. Gestionado por el
; panel (Configuración → Email → Tamaño máximo de mensaje). No editar a mano.
upload_max_filesize = 35M
post_max_size = 35M
RCPHPEOF
    done
    echo -e "  ${GREEN}✓ Límite de subida del webmail (PHP) → 35 MB${NC}"

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
curl -sSL https://packages.sury.org/php/apt.gpg | gpg --yes --dearmor -o /usr/share/keyrings/deb.sury.org-php.gpg 2>/dev/null || true

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
        # redis: cliente phpredis para el Redis dedicado por dominio (caché de objetos).
        for EXT in opcache intl soap readline gmp imagick apcu redis; do
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
            # mail.add_x_header = On → PHP añade la cabecera X-PHP-Originating-Script
            # con el UID y el script que envía. Imprescindible para identificar QUÉ
            # fichero de un sitio comprometido está enviando spam.
            if grep -q "^\s*;\?\s*mail.add_x_header" "$PHP_INI_FPM"; then
                sed -i "s|^\s*;\?\s*mail.add_x_header\s*=.*|mail.add_x_header = On|" "$PHP_INI_FPM"
            else
                echo "mail.add_x_header = On" >> "$PHP_INI_FPM"
            fi
            # memory_limit GLOBAL = techo máximo (512M). Es el máximo que el panel
            # permite subir via override por dominio. Cada pool nace con 128M
            # explícito (DOMAIN_DEFAULT_OVERRIDES): consumo contenido por defecto,
            # solo lo sube quien lo necesite. 512M da margen a editores pesados como
            # Elementor (recomienda ≥256M y agota 128M al abrir el editor → error 500).
            sed -i "s|^\s*memory_limit\s*=.*|memory_limit = 512M|" "$PHP_INI_FPM"
            # max_execution_time GLOBAL = techo (120s). El default 30s corta la carga
            # del editor de Elementor (con packs de widgets tarda >30s) → el editor se
            # queda "cargando" y ofrece "modo seguro". 120s le da margen. Es el cap:
            # el panel no deja pedir por dominio más que esto. nginx (proxy_read_timeout
            # 300) y Apache (Timeout 300) ya cubren de sobra estos 120s.
            sed -i "s|^\s*max_execution_time\s*=.*|max_execution_time = 120|" "$PHP_INI_FPM"
            sed -i "s|^\s*max_input_time\s*=.*|max_input_time = 120|" "$PHP_INI_FPM"
            # upload_max_filesize/post_max_size GLOBAL = techo (64M). El default de
            # fábrica (2M/8M) es ridículo para WordPress: subir un PDF o imagen de
            # pocos MB a la biblioteca falla. 64M es el cap; el panel puede subirlo
            # por dominio. OJO: además nginx pone client_max_body_size en el vhost
            # (scripts/utils.py) o cortaría antes con 413 aunque PHP admitiera más.
            sed -i "s|^\s*upload_max_filesize\s*=.*|upload_max_filesize = 64M|" "$PHP_INI_FPM"
            sed -i "s|^\s*post_max_size\s*=.*|post_max_size = 64M|" "$PHP_INI_FPM"
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

# ── Redis para el caché de objetos por dominio ───────────────────────────────
# Cada dominio puede activar SU instancia redis (socket unix en private/,
# corre como el usuario, maxmemory acotado) — scripts/redis_manager.py.
# Solo necesitamos el binario: si no hay stack de correo (que usa la instancia
# global como backend de Rspamd), la instancia por defecto se deja apagada.
echo -e "${YELLOW}Instalando Redis (caché de objetos por dominio)...${NC}"
if ! command -v redis-server >/dev/null 2>&1; then
    apt-get install -y -qq redis-server
    if [[ "$INSTALL_MAIL" != true ]]; then
        systemctl disable --now redis-server >/dev/null 2>&1 || true
        echo -e "  ${GREEN}✓ redis-server instalado (instancia global desactivada: solo instancias por dominio)${NC}"
    else
        echo -e "  ${GREEN}✓ redis-server instalado${NC}"
    fi
else
    echo -e "  ${GREEN}✓ redis-server ya presente${NC}"
fi
mkdir -p /etc/svqpanel/redis

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

# Compresión gzip GLOBAL (acelera todas las webs: HTML/CSS/JS/JSON ~65% menos).
# El nginx de Debian/oficial trae gzip pero viene comentado por defecto.
cat > /etc/nginx/conf.d/svqpanel-gzip.conf << 'NGGZEOF'
# SVQPanel — compresión gzip global (todas las webs)
gzip on;
gzip_vary on;
gzip_proxied any;
gzip_comp_level 5;
gzip_min_length 256;
gzip_types
    text/plain text/css text/xml text/javascript
    application/javascript application/x-javascript application/json
    application/xml application/xml+rss application/rss+xml
    application/atom+xml application/vnd.ms-fontobject
    application/x-font-ttf font/opentype image/svg+xml image/x-icon;
NGGZEOF
# max_headers (nginx >= 1.29.8): limita el nº de cabeceras por petición. Defensa
# contra el "HTTP/2 Bomb" (amplificación HPACK + window stall). El panel instala
# nginx del repo oficial (reciente), pero lo añadimos condicionalmente por si
# alguna instalación tuviera una versión vieja donde la directiva no existe.
if nginx -V 2>&1 | grep -qoE 'nginx/[0-9]+\.[0-9]+\.[0-9]+' && \
   printf '%s\n%s\n' "1.29.8" "$(nginx -v 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')" | sort -V -C; then
    echo "max_headers 100;" >> /etc/nginx/conf.d/svqpanel-hardening.conf
    echo -e "${GREEN}✓ nginx: max_headers 100 (mitiga HTTP/2 Bomb)${NC}"
fi

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
# --limit-max-requests: reinicia el worker cada N peticiones liberando memoria acumulada.
#   OJO: valor bajo (p.ej. 500) recicla cada pocos minutos por el polling del dashboard;
#   durante el reinicio nginx devuelve HTML y el frontend muestra "la API no responde".
#   50000 recicla cada muchas horas (el pico real de RAM es ~300M, MemoryMax cubre fugas).
# --timeout-keep-alive: cierra keep-alive rápido para no retener conexiones/memoria
ExecStart=/opt/svqpanel/venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8001 --limit-max-requests 50000 --timeout-keep-alive 2
Restart=always
# RestartSec bajo: acorta la ventana de caída al reciclar el worker (menos error visible).
RestartSec=2
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

    # Subidas grandes: file manager y, sobre todo, los .tar de migración de
    # otros paneles (Hestia) pueden pesar varios GB. Sin esto nginx corta con
    # 413 antes de llegar al backend.
    client_max_body_size 6g;

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

    # Página amable si el backend (uvicorn) no responde (reinicio, caída).
    # No afecta a los sitios/correo de clientes, solo al panel.
    error_page 502 503 504 /502.html;
    location = /502.html {
        internal;
        root /opt/svqpanel/frontend/dist;
    }

    # API → proxy al backend
    location /api/ {
        include snippets/svqpanel-whitelist.conf;
        proxy_pass http://svqpanel_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # Operaciones legítimamente largas (migración de backups, emisión SSL,
        # restauraciones) pueden superar el default de 60s y dar un 504.
        proxy_read_timeout 1800s;
        proxy_send_timeout 1800s;
    }

    # Docs API → proxy al backend (Swagger /docs, ReDoc /redoc, esquema OpenAPI)
    location /docs {
        proxy_pass http://svqpanel_backend/docs;
        proxy_set_header Host $host;
    }

    location /redoc {
        proxy_pass http://svqpanel_backend/redoc;
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

    # Terminal web (ttyd) — consola SSH en el navegador. ttyd escucha solo en
    # localhost; la autorización la da un token de un solo uso emitido por el
    # panel (ver scripts/terminal_manager.py). Necesita WebSocket.
    location /terminal/ {
        include snippets/svqpanel-whitelist.conf;
        proxy_pass http://127.0.0.1:7681/terminal/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400s;
    }

    # Frontend → servir archivos estáticos, fallback a index.html (SPA)
    location / {
        include snippets/svqpanel-whitelist.conf;
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

    # Snippet de whitelist del panel (vacío por defecto = sin filtrado). El
    # vhost lo incluye con `include`; debe existir aunque esté vacío. El panel
    # lo reescribe al activar la whitelist de IPs desde Configuración.
    mkdir -p /etc/nginx/snippets
    echo "# SVQPanel — whitelist desactivada (sin filtrado)" > /etc/nginx/snippets/svqpanel-whitelist.conf

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

# OJO: NO usar `flush ruleset` — borra TODAS las tablas, incluidas las del
# firewall-bouncer de CrowdSec (ip crowdsec / ip6 crowdsec6). Eso deja al bouncer
# fallando en bucle (netlink: no such file) y CrowdSec deja de aplicar baneos al
# firewall (detecta pero no bloquea). Recreamos SOLO nuestra tabla: la creamos
# vacía (para que el delete no falle si no existía) y la borramos antes de
# redefinirla. Idempotente y sin tocar las tablas de otros (crowdsec, etc.).
table inet svqpanel {}
delete table inet svqpanel

table inet svqpanel {
    # Named sets — los rellena el panel y/o fail2ban
    set whitelist_v4 { type ipv4_addr; flags interval; }
    set whitelist_v6 { type ipv6_addr; flags interval; }
    set f2b_v4 { type ipv4_addr; flags timeout; }
    set f2b_v6 { type ipv6_addr; flags timeout; }

    # Puertos abiertos del sistema. Gestionados por el panel (Seguridad →
    # Puertos del sistema): abrir/cerrar un puerto = añadir/quitar del set.
    # Incluye el del panel (__PANEL_WEB_PORT__) en TCP y UDP (UDP por HTTP/3).
    set base_tcp_ports {
        type inet_service
        flags interval
        elements = { 22, 80, 443, 25, 587, 465, 143, 993, 110, 995, 53, __PANEL_WEB_PORT__ }
    }
    set base_udp_ports {
        type inet_service
        flags interval
        elements = { 53, __PANEL_WEB_PORT__ }
    }

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
        # Gestionados vía sets (el panel los abre/cierra). De serie incluyen:
        # SSH(22), web(80,443), panel(__PANEL_WEB_PORT__), correo(25,587,465,
        # 143,993,110,995) y DNS(53). UDP: 53 (DNS) y el panel (HTTP/3).
        tcp dport @base_tcp_ports accept
        udp dport @base_udp_ports accept

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

# Unidad systemd de Postfix para el journalmatch de fail2ban. CAMBIA según la
# versión de Debian: en Debian 12 es 'postfix@-.service', en Debian 13
# 'postfix.service'. Si el journalmatch apunta a la unit equivocada, las jails
# de correo quedan CIEGAS (Total failed: 0 pese a haber ataques). Detectar la
# activa evita ese bug.
# OJO: ambas units pueden EXISTIR; hay que mirar cuál está ACTIVA (la otra está
# dead). En D12 la activa es postfix@-.service; en D13, postfix.service.
if systemctl is-active --quiet postfix@-.service 2>/dev/null; then
    PF_UNIT="postfix@-.service"
else
    PF_UNIT="postfix.service"
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
# ── Baneo escalado para reincidentes (global a todas las jails) ──────────────
# Sin esto, una IP baneada vuelve cada 'bantime' indefinidamente (puerta
# giratoria). Con increment, cada nueva reincidencia multiplica el tiempo por
# 'factor' hasta 'maxtime'. El historial de cada IP se guarda en la BD de
# fail2ban (persiste reinicios). rndtime añade jitter para no banear "en bloque".
bantime.increment = true
bantime.factor    = 2
bantime.maxtime   = 4w
bantime.rndtime   = 30m

[sshd]
enabled  = true
port     = ssh
filter   = sshd
# SSH es el blanco nº1 (miles de fallos/día de cientos de IPs). Política
# estricta: 3 fallos en 30m → baneo inicial 12h, escalando (12h→24h→48h…→4sem)
# para cualquier IP que reincida. El factor/maxtime los hereda del [DEFAULT].
maxretry = 3
findtime = 30m
bantime  = 12h

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
# mode=aggressive: el filtro normal NO casa el formato real de Dovecot moderno
#   'pop3-login: Disconnected: Connection reset by peer (auth failed, N attempts...)'
# y dejaba la jail con 0 capturas pese a cientos de fallos. Aggressive sí lo coge.
filter   = dovecot[mode=aggressive]
maxretry = 5

[postfix-sasl]
enabled  = $MAIL_JAILS_ENABLED
port     = smtp,465,submission,imap,imaps,pop3,pop3s
# Filtro propio (svqpanel-postfix-sasl): banea todos los fallos de login SMTP,
# incluido 'Invalid authentication mechanism'. journalmatch a la unit real de
# Postfix (varía D12/D13 → detectada en \$PF_UNIT).
filter   = svqpanel-postfix-sasl
journalmatch = _SYSTEMD_UNIT=$PF_UNIT
maxretry = 5

[postfix]
# Bots que abusan del puerto 25 (entrada SMTP): intentos de relay no autorizado
# ('Relay access denied'), destinatarios/dominios inexistentes, RBL, etc. El modo
# 'aggressive' del filtro estándar de Debian incluye 'Relay access denied'.
# NO afecta a clientes legítimos: estos envían autenticados por submission
# (587/465), no por el puerto 25; un cliente autenticado nunca recibe ese error.
enabled  = $MAIL_JAILS_ENABLED
port     = smtp,465,submission
filter   = postfix[mode=aggressive]
journalmatch = _SYSTEMD_UNIT=$PF_UNIT
maxretry = 3

# NOTA: NO hay jail propia para "Relay access denied". El relay a dominios no
# alojados es spam DISTRIBUIDO (muchas IPs, 1-2 intentos c/u) → fail2ban no puede
# (banea por IP que repite). De eso se encarga CrowdSec (escenario
# crowdsecurity/postfix-relay-denied), que banea por reputación y comparte
# inteligencia. Además, el servidor ya rechaza todo el relay (cero riesgo).

# Banea a quien acumula muchos 429 (rate-limit de nginx disparado): es justo el
# patrón del flood a wp-login.php de WordPress. El rate-limit SOLO frena (429);
# esta jail además BANEA al que insiste. Lee los access logs de los dominios y el
# global. Va de la mano con la protección wp-bruteforce (limit_req en el vhost).
[nginx-limit-req]
enabled  = true
port     = http,https
filter   = nginx-limit-req
logpath  = /home/*/web/*/logs/nginx.access.log
           /var/log/nginx/access.log
backend  = auto
maxretry = 10
findtime = 120
bantime  = 86400

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

# fail2ban.local: subir dbpurgeage para que el escalado (bantime.increment) tenga
# memoria suficiente. fail2ban guarda el historial de reincidencias en su SQLite
# y lo purga cada 'dbpurgeage' (default 1 día). Si la purga es < bantime.maxtime
# (4 semanas), las IPs se "olvidan" antes de poder escalar y el incremento nunca
# llega a semanas. 5w > 4w deja margen. (.local sobreescribe a fail2ban.conf y
# sobrevive a upgrades del paquete.)
cat > /etc/fail2ban/fail2ban.local << 'F2BLOCALEOF'
# /etc/fail2ban/fail2ban.local — gestionado por SVQPanel
[Definition]
dbpurgeage = 5w
F2BLOCALEOF

# Filtro custom para fallos de login del panel
cat > /etc/fail2ban/filter.d/svqpanel-auth.conf << 'F2BFILTEREOF'
# fail2ban filter for SVQPanel login failures
# Espera líneas tipo: "auth_failed ip=1.2.3.4 user=admin"
[Definition]
failregex = ^.* auth_failed ip=<HOST>.*$
ignoreregex =
F2BFILTEREOF

# Filtro propio de Postfix SASL: banea CUALQUIER fallo de login SMTP, incluido
# 'Invalid authentication mechanism' (que el filtro estándar 'postfix' excluye).
# Esos intentos son casi siempre bots de spam. El jail [postfix-sasl] lo usa.
cat > /etc/fail2ban/filter.d/svqpanel-postfix-sasl.conf << 'F2BPSASLEOF'
[Definition]
failregex = warning: [^[]*\[<HOST>\]: SASL (?:(?i)LOGIN|PLAIN|CRAM-MD5|DIGEST-MD5) authentication failed
ignoreregex =
F2BPSASLEOF

# (El relay denied lo gestiona CrowdSec, no fail2ban — ver nota en jail.local.)

# Asegurar que existe el log que vigila [svqpanel-auth]; si no fail2ban
# da error de "logpath not found" al iniciar el jail
mkdir -p /opt/svqpanel/logs
touch /opt/svqpanel/logs/auth.log

# Caché de staging de migraciones: el backup descargado en el análisis se guarda
# aquí y se reutiliza en la importación (no se vuelve a traer). Solo root.
mkdir -p /var/lib/svqpanel/migrations
chmod 700 /var/lib/svqpanel/migrations

# Temporales de migración (descarga/extracción del backup): en disco real, NO en
# /tmp (que suele ser un tmpfs pequeño y lo llenaría un backup de varios GB).
mkdir -p /var/lib/svqpanel/migration-tmp
chmod 700 /var/lib/svqpanel/migration-tmp

# Locale español para que los informes de GoAccess salgan en español (la
# traducción goaccess.mo viene con el paquete; falta generar el locale).
if ! locale -a 2>/dev/null | grep -qiE "^es_ES\.(utf8|UTF-8)$"; then
    grep -q "^es_ES.UTF-8" /etc/locale.gen 2>/dev/null || echo "es_ES.UTF-8 UTF-8" >> /etc/locale.gen
    locale-gen es_ES.UTF-8 >/dev/null 2>&1 || true
fi

# GeoIP (países en las estadísticas de dominio con GoAccess): base gratuita de
# DB-IP + cron mensual para mantenerla al día.
mkdir -p /var/lib/svqpanel/geoip
(cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli update_geoip) || \
    echo "  ⚠ GeoIP no descargada (se reintentará por cron)"
cat > /etc/cron.d/svqpanel-geoip <<'CRONEOF'
# SVQPanel — actualización mensual de la base GeoIP (países en estadísticas)
15 4 5 * * root cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli update_geoip >> /var/log/svqpanel-update.log 2>&1
CRONEOF
chmod 644 /etc/cron.d/svqpanel-geoip

# Cloudflare real_ip para nginx: recupera la IP real del visitante tras Cloudflare
# (si no, el rate-limit por IP, los logs y fail2ban/CrowdSec ven la IP de CF y no
# sirven). Escribe /etc/nginx/conf.d/svqpanel-cloudflare-realip.conf + cron mensual
# para mantener los rangos al día.
(cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli refresh_cloudflare_ips) || \
    echo "  ⚠ Rangos Cloudflare no descargados (se reintentará por cron)"
cat > /etc/cron.d/svqpanel-cloudflare <<'CRONEOF'
# SVQPanel — actualización mensual de los rangos de Cloudflare (real_ip nginx)
20 4 5 * * root cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli refresh_cloudflare_ips >> /var/log/svqpanel-update.log 2>&1
CRONEOF
chmod 644 /etc/cron.d/svqpanel-cloudflare

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

echo -e "${GREEN}✓ fail2ban: jails activas (sshd, recidive, svqpanel-auth$( [[ "$INSTALL_MAIL" == true ]] && echo ', dovecot, postfix-sasl, postfix' ))${NC}"
if [[ -n "$INSTALLER_IP" ]]; then
    echo -e "  ${GREEN}✓ Anti-lockout: $INSTALLER_IP en whitelist nftables + ignoreip fail2ban${NC}"
fi

###############################################################################
# 12B-bis. HARDENING DEL SISTEMA OPERATIVO
#   - Kernel/red (sysctl): anti-spoofing, anti-redirect/MITM, log de marcianos.
#   - SSH: desactivar X11Forwarding (inútil en servidor). Se MANTIENE el login
#     de root por contraseña (decisión del operador); fail2ban cubre la fuerza
#     bruta (5 intentos → ban 1h) + svqpanel-auth + recidive.
#   - Deshabilitar servicios innecesarios en un servidor de hosting (rpcbind,
#     avahi, cups, telnet) → menos superficie de ataque.
#   - Desactivar LLMNR (resolución multicast, vector de envenenamiento).
###############################################################################
echo -e "${YELLOW}Aplicando hardening del sistema operativo...${NC}"

# ── Kernel / red (sysctl) ──────────────────────────────────────────────────
cat > /etc/sysctl.d/99-svqpanel-security.conf << 'SYSCTLEOF'
# SVQPanel — hardening de red/kernel
# Anti-spoofing: descarta paquetes cuya ruta de retorno no cuadra con la interfaz
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
# No aceptar ni enviar ICMP redirects (previene MITM por redirección de rutas)
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.default.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0
# No aceptar source routing (paquetes que dictan su propia ruta)
net.ipv4.conf.all.accept_source_route = 0
net.ipv6.conf.all.accept_source_route = 0
# SYN cookies (mitiga SYN flood)
net.ipv4.tcp_syncookies = 1
# Ignorar broadcast ICMP (evita ser amplificador de smurf attacks)
net.ipv4.icmp_echo_ignore_broadcasts = 1
# Ignorar respuestas ICMP erróneas (bogus)
net.ipv4.icmp_ignore_bogus_error_responses = 1
# Loguear paquetes con direcciones imposibles ("martians")
net.ipv4.conf.all.log_martians = 1
# ASLR completo (aleatorización del espacio de memoria) — ya suele estar a 2
kernel.randomize_va_space = 2
# Protección contra ataques de hardlink/symlink en directorios world-writable
fs.protected_hardlinks = 1
fs.protected_symlinks = 1
SYSCTLEOF
sysctl --system >/dev/null 2>&1 || true
echo -e "  ${GREEN}✓ sysctl de seguridad aplicado (/etc/sysctl.d/99-svqpanel-security.conf)${NC}"

# ── SSH: quitar X11Forwarding (se mantiene root+password) ──────────────────
SSHD_HARDEN="/etc/ssh/sshd_config.d/99-svqpanel.conf"
cat > "$SSHD_HARDEN" << 'SSHDEOF'
# SVQPanel — hardening SSH (mínimo, no rompe el acceso por contraseña de root)
X11Forwarding no
# No permitir contraseñas vacías (por si acaso)
PermitEmptyPasswords no
# Límite de intentos de auth por conexión (estricto: 3, complementa a fail2ban)
MaxAuthTries 3
# Tiempo máximo para autenticarse antes de cerrar (corta bots que se cuelgan)
LoginGraceTime 20
# Sin sesiones múltiples sin autenticar en paralelo desde una misma conexión
MaxStartups 10:30:60
SSHDEOF
# Validar la config antes de recargar para no romper el SSH
if sshd -t 2>/dev/null; then
    systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
    echo -e "  ${GREEN}✓ SSH endurecido (X11 off, sin passwords vacías). Root por contraseña: SIGUE activo.${NC}"
else
    rm -f "$SSHD_HARDEN"
    echo -e "  ${YELLOW}⚠ La config SSH no validó; se omite el hardening de SSH${NC}"
fi

# ── Deshabilitar servicios innecesarios en un servidor de hosting ──────────
for _svc in rpcbind.service rpcbind.socket avahi-daemon.service avahi-daemon.socket cups.service cups.socket cups-browsed.service telnet.socket; do
    if systemctl list-unit-files 2>/dev/null | grep -q "^${_svc}"; then
        systemctl disable --now "$_svc" >/dev/null 2>&1 || true
    fi
done
echo -e "  ${GREEN}✓ Servicios innecesarios deshabilitados (rpcbind, avahi, cups, telnet)${NC}"

# ── Desactivar LLMNR (resolución multicast, vector de envenenamiento) ──────
mkdir -p /etc/systemd/resolved.conf.d
cat > /etc/systemd/resolved.conf.d/99-svqpanel.conf << 'RESOLVEDEOF'
[Resolve]
LLMNR=no
MulticastDNS=no
RESOLVEDEOF
systemctl restart systemd-resolved >/dev/null 2>&1 || true
echo -e "  ${GREEN}✓ LLMNR/mDNS desactivados${NC}\n"

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
        # Las colecciones deben coincidir con los servicios que corren. Base:
        # linux + sshd. http-dos añade detección de floods HTTP (capa 7).
        # NOTA: NO instalamos crowdsecurity/iptables — es un parser del log de
        # iptables/UFW, pero SVQPanel usa nftables sin logging, así que no tendría
        # nada que parsear (solo añadiría ruido).
        echo -e "  ${YELLOW}→ Instalando colecciones (parsers + escenarios)...${NC}"
        # crowdsecurity/wordpress: escenarios de fuerza bruta de wp-login
        # (http-bf-wordpress_bf), enumeración de usuarios y sondeo de wp-config.
        # Casi todos los sitios alojados son WordPress y el ataque más habitual es
        # el flood DISTRIBUIDO a wp-login, que el rate-limit por IP no puede parar
        # (cada IP va bajo el umbral) pero CrowdSec sí (banea por acumulación).
        for COL in \
            crowdsecurity/linux \
            crowdsecurity/sshd \
            crowdsecurity/nginx \
            crowdsecurity/base-http-scenarios \
            crowdsecurity/http-cve \
            crowdsecurity/http-dos \
            crowdsecurity/wordpress; do
            cscli collections install "$COL" > /dev/null 2>&1 \
                && echo -e "    ${GREEN}✓ $COL${NC}" \
                || echo -e "    ${YELLOW}⚠ $COL (no disponible)${NC}"
        done

        # Apache: solo si el webserver elegido lo usa (modo apache+nginx). Las
        # reglas de nginx NO entienden el log de Apache, así que sin esta
        # colección los dominios servidos por Apache quedarían sin protección.
        if [[ "$WEBSERVER" == "apache+nginx" || "$WEBSERVER" == "apache" ]]; then
            cscli collections install crowdsecurity/apache2 > /dev/null 2>&1 \
                && echo -e "    ${GREEN}✓ crowdsecurity/apache2${NC}" \
                || echo -e "    ${YELLOW}⚠ crowdsecurity/apache2 (no disponible)${NC}"
        fi

        # Fuerza bruta de WordPress vía XML-RPC: NO viene en la colección
        # crowdsecurity/wordpress, hay que instalar el escenario aparte. Complementa
        # el bloqueo de xmlrpc en nginx (defensa en profundidad).
        cscli scenarios install crowdsecurity/http-bf-wordpress_bf_xmlrpc > /dev/null 2>&1 \
            && echo -e "    ${GREEN}✓ crowdsecurity/http-bf-wordpress_bf_xmlrpc${NC}" \
            || echo -e "    ${YELLOW}⚠ http-bf-wordpress_bf_xmlrpc (no disponible)${NC}"

        # Escenario propio: banear IPs que insisten tras un 444. El catálogo de
        # bad-bots de nginx corta a los bots conocidos con 444 (cierra sin
        # responder, no llega a PHP), pero los escenarios http-* de CrowdSec miran
        # 200/403/404, NO el 444, así que un bot cortado reconecta ~1/seg sin fin.
        # Este escenario cuenta los 444 por IP y escala al firewall-bouncer.
        mkdir -p /etc/crowdsec/scenarios
        cat > /etc/crowdsec/scenarios/svqpanel-http-444-flood.yaml << 'CS444EOF'
# SVQPanel — banear IPs que insisten tras ser cortadas con 444 por nginx.
type: leaky
name: svqpanel/http-444-flood
description: "IP que recibe muchos 444 (cortada por bad-bots de nginx) y sigue reconectando"
filter: "evt.Meta.log_type in ['http_access-log'] && evt.Meta.http_status == '444'"
groupby: "evt.Meta.source_ip"
capacity: 30
leakspeed: "2s"
blackhole: 5m
labels:
  confidence: 2
  spoofable: 0
  service: http
  behavior: "http:bruteforce"
  label: "Bot insistente cortado con 444"
  remediation: true
CS444EOF
        echo -e "    ${GREEN}✓ svqpanel/http-444-flood (banear bots que insisten tras 444)${NC}"

        # NOTA (Laravel / apps PHP a medida): NO existe colección específica de
        # Laravel (su login no es una ruta fija). Quedan cubiertas por los
        # escenarios genéricos que ya trae base-http-scenarios + http-cve:
        # http-generic-bf, http-probing, http-sqli-probing, http-xss-probing,
        # http-path-traversal-probing, http-backdoors-attempts, http-cve-probing…
        # (agnósticos del framework). Protección de peticiones a fondo (WAF OWASP
        # con AppSec) queda como mejora futura — requiere el componente appsec y
        # rodaje en modo detección para evitar falsos positivos.

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

        # ── 4b. Whitelist REST API de WordPress (/wp-json/) ───────────────────
        # Elementor y otros plugins de WP disparan ráfagas de GET a /wp-json/...
        # que devuelven 404 cuando el endpoint no existe (típico: Elementor Pro
        # pidiendo rutas de licencia que solo existen con la versión de pago). El
        # escenario genérico http-probing cuenta esos 404 como sondeo de rutas y
        # banea al ADMINISTRADOR legítimo del sitio mientras edita/actualiza.
        # /wp-json/ es la API REST estándar de WordPress; un 404 ahí es normal, no
        # un ataque. Los probes reales (.env, .git, /vendor, /wp-admin/xxx) NO
        # empiezan por /wp-json/ y siguen baneándose (comprobado con cscli explain).
        mkdir -p /etc/crowdsec/parsers/s02-enrich
        cat > /etc/crowdsec/parsers/s02-enrich/svqpanel-wp-rest-whitelist.yaml << 'CSWPWLEOF'
name: svqpanel/wp-rest-whitelist
description: "No contar como http-probing los 404 de la REST API de WordPress (/wp-json/). Elementor y otros plugins piden rutas /wp-json/ que devuelven 404 cuando el endpoint no existe (p.ej. Elementor Pro sin licencia); son peticiones legitimas del admin del sitio, no un escaneo. Los probes reales (.env, .git, /vendor, /wp-admin/xxx) NO empiezan por /wp-json/ y siguen baneandose."
whitelist:
  reason: "WordPress REST API (/wp-json/) — 404 normales de plugins, no probing"
  expression:
    - "evt.Meta.http_path startsWith '/wp-json/'"
CSWPWLEOF
        echo -e "  ${GREEN}✓ Whitelist REST API de WordPress (/wp-json/) para CrowdSec${NC}"

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

        # ── 5b. Acquis: logs de acceso de los DOMINIOS de clientes ────────────
        # Sin esto CrowdSec SOLO ve /var/log/nginx|apache2 (el panel) y queda
        # CIEGO ante los ataques a las webs alojadas (fuerza bruta wp-login
        # DISTRIBUIDA, scans WP, probing…). Con estos logs, los escenarios http-*
        # banean esas IPs por reputación — que es lo que el rate-limit por IP NO
        # puede frenar cuando el ataque viene de decenas de IPs a la vez.
        cat > /etc/crowdsec/acquis.d/svqpanel-domains.yaml << CSDOMEOF
# SVQPanel — logs de acceso Y error de los dominios de clientes.
# access.log → escenarios http-* (fuerza bruta wp-login, scans, probing…).
# error.log  → nginx-req-limit-exceeded: los 429 del rate-limit (p.ej. wp-login)
#              quedan en el error.log, NO en el access → sin él CrowdSec no banea
#              al que dispara el límite repetidamente.
filenames:
  - /home/*/web/*/logs/nginx.access.log
labels:
  type: nginx
---
filenames:
  - /home/*/web/*/logs/nginx.error.log
labels:
  type: nginx
---
filenames:
  - /home/*/web/*/logs/apache.access.log
labels:
  type: apache2
---
filenames:
  - /home/*/web/*/logs/apache.error.log
labels:
  type: apache2
CSDOMEOF

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

# ─── Timer diario: backup del propio panel (BD + config) ─────────────────────
# Red de seguridad: si la BD del panel se corrompe, puedes restaurar usuarios,
# dominios, DNS, correo y config. Guarda en /var/backups/svqpanel (rota 7 días).
cat > /etc/systemd/system/svqpanel-backup-panel.service << 'BKPEOF'
[Unit]
Description=SVQPanel — backup de la BD y config del propio panel
After=network.target svqpanel.service postgresql.service

[Service]
Type=oneshot
User=root
WorkingDirectory=/opt/svqpanel
Environment="PATH=/opt/svqpanel/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=/opt/svqpanel/venv/bin/python -m api.cli backup_panel
TimeoutStartSec=600
BKPEOF

cat > /etc/systemd/system/svqpanel-backup-panel.timer << 'BKPTEOF'
[Unit]
Description=SVQPanel — timer diario para backup del panel (03:30)

[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true
Unit=svqpanel-backup-panel.service

[Install]
WantedBy=timers.target
BKPTEOF

systemctl enable --now svqpanel-backup-panel.timer >/dev/null 2>&1 || true
echo -e "${GREEN}✓ systemd timer: svqpanel-backup-panel.timer (backup del panel diario 03:30)${NC}"

# Hacer un primer backup ya, para no esperar al primer disparo del timer.
/opt/svqpanel/venv/bin/python -m api.cli backup_panel >/dev/null 2>&1 || true

# Nota: la salud del cluster DNS y el muestreo de métricas los hace un hilo de
# fondo DENTRO del panel (scripts/metrics_scheduler.py). El dns-health solo
# trabaja si hay cluster configurado (si no, no hace nada, sin ruido). Ya NO se
# usan timers systemd para esto. Retiramos el timer dns-cluster si quedó de antes.
systemctl disable --now svqpanel-dns-cluster-health.timer >/dev/null 2>&1 || true
rm -f /etc/systemd/system/svqpanel-dns-cluster-health.timer \
      /etc/systemd/system/svqpanel-dns-cluster-health.service 2>/dev/null || true

# ─── Métricas + alertas ──────────────────────────────────────────────────────
# Guarda una muestra de CPU/RAM/disco/load/red en el histórico (retención 30d)
# y evalúa las alertas configuradas (disco/servicio/carga/SSL), enviando email
# si alguna se dispara (vía el SMTP del panel).
# Nota: el muestreo de métricas lo hace un hilo de fondo DENTRO del panel
# (scripts/metrics_scheduler.py, arrancado en api/main.py startup), igual que el
# backup scheduler. Ya NO se usa un timer systemd cada 5 min (arrancaba un
# proceso Python entero 288 veces/día → ruido en el log + CPU). Retiramos el
# timer si quedó de una instalación previa.
systemctl disable --now svqpanel-metrics.timer >/dev/null 2>&1 || true
rm -f /etc/systemd/system/svqpanel-metrics.timer \
      /etc/systemd/system/svqpanel-metrics.service 2>/dev/null || true
echo -e "${GREEN}✓ Métricas + alertas: hilo interno del panel (sin timer cada 5 min)${NC}"

# Nota: los backups programados los gestiona un hilo de fondo DENTRO del panel
# (scripts/backup_scheduler.py, arrancado en api/main.py startup). Ya NO se usa
# un timer systemd cada minuto (arrancaba un proceso Python entero 1440 veces/día
# para 0 jobs casi siempre → ruido en el log y CPU desperdiciada). La fuga de
# memoria que motivó el timer ya está resuelta (imports a nivel de módulo).

systemctl daemon-reload
systemctl enable --now svqpanel-domain-stats.timer          >/dev/null 2>&1 || true
systemctl enable --now svqpanel-ssl-check.timer             >/dev/null 2>&1 || true
# Por si una instalación previa dejó timers que ahora son hilos internos, los retiramos.
systemctl disable --now svqpanel-backup-scheduler.timer     >/dev/null 2>&1 || true
rm -f /etc/systemd/system/svqpanel-backup-scheduler.timer \
      /etc/systemd/system/svqpanel-backup-scheduler.service 2>/dev/null || true

echo -e "${GREEN}✓ systemd timer: svqpanel-domain-stats.timer (cada 4h)${NC}"
echo -e "${GREEN}✓ systemd timer: svqpanel-ssl-check.timer (diario 05:15)${NC}"
echo -e "${GREEN}✓ Métricas, backups y salud DNS: hilos internos del panel (sin timers)${NC}"
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
if [[ "$UNATTENDED" == true || -n "${SVQ_ADMIN_USER:-}" ]]; then
    _ADMIN_USER_INPUT="${SVQ_ADMIN_USER:-}"   # vacío = aleatorio (recomendado)
else
    echo -e "${YELLOW}Nombre de usuario administrador del panel:${NC}"
    echo -e "  Deja en blanco para generar uno aleatorio (recomendado por seguridad)"
    printf "  Usuario admin (Enter = aleatorio): "; read _ADMIN_USER_INPUT </dev/tty
fi
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
    # Home a 711 (igual que UserManager): el dueño entra, otros NO listan su
    # contenido, pero www-data SÍ puede atravesarlo para servir la web. useradd
    # -m lo crea en 755 por defecto, que dejaría el home listable por otros.
    chmod 711 "/home/${ADMIN_USER}"
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

# Fijar php_default_version a la versión instalada más reciente (no hardcodear 8.2,
# que podría no estar instalada). Recomendamos la más nueva que el usuario eligió.
SVQPANEL_PHP_VERSIONS="${PHP_ARRAY[*]}" python3 << 'PYTHONEOF'
import sys, os
sys.path.insert(0, '/opt/svqpanel')
from api.models.database import SessionLocal, load_all_models
load_all_models()
from api.models.models_settings import Settings

versions = (os.environ.get('SVQPANEL_PHP_VERSIONS', '') or '').split()
if not versions:
    sys.exit(0)

# Más reciente por valor numérico (8.5 > 8.3 > 7.4)
def vkey(v):
    try:
        return tuple(int(x) for x in v.split('.'))
    except Exception:
        return (0,)
default_php = sorted(versions, key=vkey, reverse=True)[0]

session = SessionLocal()
try:
    s = session.query(Settings).first()
    if s is None:
        s = Settings(id=1)
        session.add(s)
    s.php_default_version = default_php
    session.commit()
    print(f"php_default_version set to {default_php}")
except Exception as e:
    print(f"Error setting default PHP: {e}")
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

# Proteger el Redis global (backend de Rspamd) con contraseña. Sin esto, el
# PHP de cualquier cliente puede conectar a 127.0.0.1:6379 (disable_functions
# no bloquea sockets) y hacer FLUSHALL al Bayes/greylist/ratelimit de correo.
echo -e "${YELLOW}Protegiendo el Redis de Rspamd (requirepass)...${NC}"
/opt/svqpanel/venv/bin/python -m api.cli secure_rspamd_redis && \
    echo -e "${GREEN}✓ Redis de Rspamd protegido con contraseña${NC}" || \
    echo -e "${YELLOW}⚠ secure_rspamd_redis tuvo incidencias (revisar logs)${NC}"
echo ""

# Aprendizaje de spam: IMAPSieve (rspamc learn al mover a/desde Junk) + autolearn
# + Bayes global. Requiere dovecot-sieve (instalado arriba) y Rspamd.
echo -e "${YELLOW}Configurando el aprendizaje de spam (Bayes + IMAPSieve)...${NC}"
/opt/svqpanel/venv/bin/python -m api.cli setup_spam_learning && \
    echo -e "${GREEN}✓ Aprendizaje de spam configurado${NC}" || \
    echo -e "${YELLOW}⚠ setup_spam_learning tuvo incidencias (revisar logs)${NC}"
echo ""

# Mover el spam marcado por Rspamd (X-Spam: Yes) a la carpeta Junk del buzón,
# vía Sieve global "before" de Dovecot. Sin esto, el spam intermedio (score>=6)
# llega a la bandeja de entrada en vez de a Junk.
echo -e "${YELLOW}Configurando 'mover spam a Junk' (Sieve global)...${NC}"
/opt/svqpanel/venv/bin/python -m api.cli setup_spam_to_junk && \
    echo -e "${GREEN}✓ Spam → carpeta Junk configurado${NC}" || \
    echo -e "${YELLOW}⚠ setup_spam_to_junk tuvo incidencias (revisar logs)${NC}"
echo ""

# Actualizaciones automáticas de SEGURIDAD del SO (unattended-upgrades, solo
# parches de seguridad, sin reinicio automático). Cierra vulnerabilidades del SO
# sin intervención. Gestionable desde Seguridad → Auto-actualizaciones.
echo -e "${YELLOW}Activando actualizaciones automáticas de seguridad...${NC}"
/opt/svqpanel/venv/bin/python -m api.cli setup_auto_updates && \
    echo -e "${GREEN}✓ Auto-actualizaciones de seguridad activadas${NC}" || \
    echo -e "${YELLOW}⚠ setup_auto_updates tuvo incidencias (revisar logs)${NC}"
echo ""

# Endurecer servicios: banner SMTP genérico + VRFY off (Postfix), version none
# (BIND). No revelar versiones/OS ni permitir enumeración de buzones.
echo -e "${YELLOW}Endureciendo servicios (ocultar versiones, anti-enumeración)...${NC}"
/opt/svqpanel/venv/bin/python -m api.cli harden_services && \
    echo -e "${GREEN}✓ Servicios endurecidos${NC}" || \
    echo -e "${YELLOW}⚠ harden_services tuvo incidencias (revisar logs)${NC}"
echo ""

# Protección anti zip-bomb del antispam (Rspamd): sube el peso de los símbolos
# de archivo para frenar adjuntos comprimidos maliciosos (ratio de bomba o exe).
echo -e "${YELLOW}Aplicando protección anti zip-bomb del antispam...${NC}"
/opt/svqpanel/venv/bin/python -m api.cli setup_archive_protection && \
    echo -e "${GREEN}✓ Protección anti zip-bomb aplicada${NC}" || \
    echo -e "${YELLOW}⚠ setup_archive_protection tuvo incidencias (revisar logs)${NC}"
echo ""

# Penalización de correo en cirílico (spam de formularios web ES y spam ruso).
echo -e "${YELLOW}Aplicando penalización de correo en cirílico...${NC}"
/opt/svqpanel/venv/bin/python -m api.cli setup_cyrillic_protection && \
    echo -e "${GREEN}✓ Penalización de cirílico aplicada${NC}" || \
    echo -e "${YELLOW}⚠ setup_cyrillic_protection tuvo incidencias (revisar logs)${NC}"
echo ""

# Persistencia de IPv6 vía systemd-networkd + ruta default IPv6 persistente.
# (Las IPv6 de dominios NO se gestionan con netplan: redefinir eth0 en netplan
# rompe la red al reiniciar. Ver scripts/ipv6_manager.py y ipv6_route_service.py)
echo -e "${YELLOW}Configurando persistencia de IPv6 (systemd-networkd)...${NC}"
/opt/svqpanel/venv/bin/python -m api.cli setup_ipv6_persistence && \
    echo -e "${GREEN}✓ Persistencia de IPv6 configurada${NC}" || \
    echo -e "${YELLOW}⚠ setup_ipv6_persistence tuvo incidencias (revisar logs)${NC}"
echo ""

###############################################################################
# 14b. SSL AUTOMÁTICO DEL PANEL (si el hostname apunta a este servidor)
###############################################################################
if [[ "$PANEL_SSL_READY" == true && -n "$PANEL_HOSTNAME" ]]; then
    echo -e "${YELLOW}Emitiendo certificado SSL del panel para $PANEL_HOSTNAME...${NC}"
    # El backend debe estar arrancado para que nginx sirva el ACME challenge.
    systemctl start svqpanel 2>/dev/null || true
    sleep 3
    # Email para Let's Encrypt: el del admin si parece real, si no uno del hostname.
    _LE_EMAIL="admin@${PANEL_HOSTNAME#*.}"
    PANEL_SSL_HOSTNAME="$PANEL_HOSTNAME" PANEL_SSL_EMAIL="$_LE_EMAIL" \
    /opt/svqpanel/venv/bin/python << 'PANELSSLEOF'
import os, sys
sys.path.insert(0, "/opt/svqpanel")
hostname = os.environ["PANEL_SSL_HOSTNAME"]
email    = os.environ["PANEL_SSL_EMAIL"]
try:
    from api.models.database import SessionLocal, load_all_models
    load_all_models()
    from api.routes.settings import get_or_create_settings
    from scripts.panel_ssl_manager import PanelSSLManager

    # Guardar el hostname en Settings antes de emitir
    db = SessionLocal()
    s = get_or_create_settings(db)
    s.panel_hostname = hostname
    db.commit()
    db.close()

    PanelSSLManager().issue_ssl(hostname, email, force_https=True)
    print("OK")
except Exception as e:
    print(f"FAIL: {e}", file=sys.stderr)
    sys.exit(1)
PANELSSLEOF
    if [[ $? -eq 0 ]]; then
        # Cinturón y tirantes: el manager ya persiste el estado, pero forzamos
        # una sincronización por si acaso (deja ssl_panel_enabled + fecha en la BD
        # → la UI muestra "SSL activo" en vez de "Sin SSL").
        /opt/svqpanel/venv/bin/python -m api.cli sync_panel_ssl >/dev/null 2>&1 || true
        echo -e "${GREEN}✓ SSL del panel emitido. Accede por https://$PANEL_HOSTNAME:$PANEL_WEB_PORT${NC}\n"
        PANEL_ACCESS_URL="https://$PANEL_HOSTNAME:$PANEL_WEB_PORT"
    else
        echo -e "${YELLOW}⚠ No se pudo emitir el SSL automáticamente. El panel queda en HTTP;${NC}"
        echo -e "${YELLOW}    emítelo después desde Configuración → SSL del Panel.${NC}\n"
        PANEL_ACCESS_URL="http://${_INSTALL_SERVER_IP}:$PANEL_WEB_PORT"
    fi
else
    PANEL_ACCESS_URL="http://${_INSTALL_SERVER_IP}:$PANEL_WEB_PORT"
fi

###############################################################################
# CRON DE ACTUALIZACIONES AUTOMÁTICAS — 3:00am diario
###############################################################################
echo -e "${YELLOW}Configurando actualización automática diaria...${NC}"
CRON_LINE="0 3 * * * root bash /opt/svqpanel/update.sh >> /var/log/svqpanel-update.log 2>&1"
CRON_FILE="/etc/cron.d/svqpanel-update"
echo "$CRON_LINE" > "$CRON_FILE"
chmod 644 "$CRON_FILE"

# Marcar todos los updates actuales como ya aplicados (están incluidos en el install)
mkdir -p /etc/svqpanel
find /opt/svqpanel/updates -maxdepth 1 -name '[0-9][0-9][0-9][0-9]-*.sh' | sort | while IFS= read -r f; do
    ID=$(basename "$f" .sh)
    if ! grep -qF "$ID" /etc/svqpanel/applied_updates 2>/dev/null; then
        echo "$ID" >> /etc/svqpanel/applied_updates
    fi
done
echo -e "${GREEN}✓ Cron configurado: actualización automática cada día a las 3:00am${NC}\n"

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
if [[ "$PANEL_SSL_READY" == true && -n "$PANEL_HOSTNAME" ]]; then
    echo -e "  • Panel Web:    ${GREEN}https://${PANEL_HOSTNAME}:${PANEL_WEB_PORT}${NC}  (SSL activo)"
    echo "  • Seguridad:    https://${PANEL_HOSTNAME}:${PANEL_WEB_PORT}/security"
    echo "  • API Docs:     https://${PANEL_HOSTNAME}:${PANEL_WEB_PORT}/docs"
    echo "  • (también por IP: http://${SERVER_IP}:${PANEL_WEB_PORT})"
else
    echo "  • Panel Web:    http://${SERVER_IP}:${PANEL_WEB_PORT}"
    echo "  • Seguridad:    http://${SERVER_IP}:${PANEL_WEB_PORT}/security  (firewall, fail2ban, listas IP)"
    echo "  • API Docs:     http://${SERVER_IP}:${PANEL_WEB_PORT}/docs"
    if [[ -n "$PANEL_HOSTNAME" ]]; then
        echo -e "  ${YELLOW}↳ Para HTTPS: configura el DNS de ${PANEL_HOSTNAME} → ${SERVER_IP} y emite${NC}"
        echo -e "  ${YELLOW}  el SSL desde Configuración → SSL del Panel.${NC}"
    fi
fi
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
    echo "  • SMTP envío:    puerto 465 (SSL/TLS) / 587 (STARTTLS) + auth"
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
echo -e "\n${YELLOW}¿Perdiste el acceso de administrador?${NC} (ejecutar como root)"
echo "  • Listar admins:    /opt/svqpanel/venv/bin/python -m api.cli admin_recover --list"
echo "  • Resetear clave:   /opt/svqpanel/venv/bin/python -m api.cli admin_recover --username USUARIO --password NUEVA"
if [[ "$INSTALL_MAIL" == true ]]; then
    echo "  • Correo: sustituye el certificado snakeoil por uno real (Let's Encrypt)"
fi
if [[ "$INSTALL_ROUNDCUBE" == true ]]; then
    echo "  • Roundcube: los tokens de autologin caducan en 60 segundos (uso único)"
fi
