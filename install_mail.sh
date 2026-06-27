#!/usr/bin/env bash
# =============================================================================
#  SVQPanel — Instalador del módulo de correo electrónico
#  Ejecutar SOLO si SVQPanel ya está instalado en /opt/svqpanel
#  Uso: bash install_mail.sh
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
SVQPANEL_DIR="/opt/svqpanel"
ENV_FILE="$SVQPANEL_DIR/.env"

# ── Comprobaciones previas ────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}✗ Este script debe ejecutarse como root${NC}"
    exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
    echo -e "${RED}✗ No se encontró $ENV_FILE — ¿está SVQPanel instalado?${NC}"
    exit 1
fi

# Comprobar si el correo ya está activado
if grep -q "^MAIL_ENABLED=true" "$ENV_FILE"; then
    echo -e "${YELLOW}⚠ El módulo de correo ya está activado en .env${NC}"
    read -p "¿Reconfigurar de todas formas? (s/N): " _RECONF
    [[ "${_RECONF,,}" =~ ^(s|si|y|yes)$ ]] || exit 0
fi

# ── Detectar Debian ───────────────────────────────────────────────────────────
if ! command -v lsb_release &>/dev/null; then
    apt-get install -y -qq lsb-release
fi
OS_ID=$(lsb_release -si)
if [[ "$OS_ID" != "Debian" ]]; then
    echo -e "${YELLOW}⚠ Este script está pensado para Debian. Continuar bajo tu responsabilidad.${NC}"
fi

# ── Detectar soporte SSSE3 (necesario para Rspamd/hyperscan) ─────────────────
# IMPORTANTE: Rspamd 4.x necesita SSSE3 no solo para hyperscan, sino para su
# parser MIME: sin SSSE3, Rspamd 4.x NO descompone los mensajes multipart
# (no ve los adjuntos) y se rompe el antivirus, el escaneo de adjuntos y parte
# del antispam. En VMs KVM/Proxmox con CPU genérica ("Common KVM processor")
# las flags SSSE3/SSE4/AVX no se exponen aunque el CPU físico las tenga: hay
# que poner el tipo de CPU = "host" en la VM para heredar las instrucciones
# reales del procesador. Tras cambiarlo, apagar/arrancar la VM (no basta un
# reboot del SO) para que el hipervisor presente la nueva CPU.
if grep -q "ssse3" /proc/cpuinfo; then
    INSTALL_RSPAMD=true
else
    INSTALL_RSPAMD=false
    echo -e "${YELLOW}⚠ CPU sin instrucciones SSSE3 — Rspamd no es compatible con este procesador${NC}"
    echo -e "  ${YELLOW}Se instalará Postfix + Dovecot sin antispam (DKIM/antivirus requieren Rspamd)${NC}"
    if grep -qiE 'kvm|qemu|hypervisor' /proc/cpuinfo 2>/dev/null || \
       systemd-detect-virt -q 2>/dev/null; then
        echo -e "  ${YELLOW}Detectada virtualización: si es Proxmox/KVM, pon el tipo de CPU = 'host'${NC}"
        echo -e "  ${YELLOW}en la VM y apágala/arráncala para exponer SSSE3 y poder usar Rspamd.${NC}"
    fi
    echo ""
fi

echo ""
echo "=== SVQPanel — Instalación del servidor de correo ==="
echo ""
echo -e "  Stack: ${GREEN}Postfix${NC} (SMTP) + ${GREEN}Dovecot${NC} (IMAP/POP3)"
echo -e "       + ${GREEN}Rspamd${NC} (antispam/DKIM) + ${GREEN}Redis${NC}"
echo ""
echo -e "  ${YELLOW}Requisitos previos:${NC}"
echo "   • Puerto 25 desbloqueado en tu proveedor/firewall"
echo "   • rDNS (PTR) configurado en la IP del servidor"
echo "   • Registro MX apuntando a este servidor en los dominios que uses"
echo ""
read -p "¿Continuar con la instalación? (s/N): " _CONFIRM
[[ "${_CONFIRM,,}" =~ ^(s|si|y|yes)$ ]] || { echo "Cancelado."; exit 0; }
echo ""

# ── 1. PAQUETE ssl-cert (snakeoil) ────────────────────────────────────────────
apt-get install -y -qq ssl-cert

# ── 2. POSTFIX ────────────────────────────────────────────────────────────────
echo -e "${YELLOW}→ Instalando Postfix...${NC}"

debconf-set-selections <<< "postfix postfix/mailname string $(hostname -f)"
debconf-set-selections <<< "postfix postfix/main_mailer_type string 'Internet Site'"
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postfix

# Ficheros de maps (no sobreescribir si ya existen con datos)
touch /etc/postfix/virtual_domains \
      /etc/postfix/virtual_mailbox \
      /etc/postfix/virtual_alias
postmap /etc/postfix/virtual_domains
postmap /etc/postfix/virtual_mailbox
postmap /etc/postfix/virtual_alias

# Configuración virtual mailboxes (buzones bajo /home/{usuario}/mail/…)
postconf -e "virtual_mailbox_domains = hash:/etc/postfix/virtual_domains"
postconf -e "virtual_mailbox_base = /home"
postconf -e "virtual_mailbox_maps = hash:/etc/postfix/virtual_mailbox"
postconf -e "virtual_alias_maps = hash:/etc/postfix/virtual_alias"
postconf -e "virtual_minimum_uid = 100"
postconf -e "virtual_uid_maps = static:5000"
postconf -e "virtual_gid_maps = static:5000"

# SASL auth vía Dovecot
postconf -e "smtpd_sasl_auth_enable = yes"
postconf -e "smtpd_sasl_type = dovecot"
postconf -e "smtpd_sasl_path = private/auth"
postconf -e "smtpd_sasl_security_options = noanonymous"

# TLS — usar cert del panel si existe; si no, snakeoil como fallback temporal
# El cert real se aplica por dominio vía SNI map (mail_tls_manager.py).
# El cert por defecto global cubre el hostname del servidor (FQDN del panel).
PANEL_CERT="/etc/letsencrypt/live/$(hostname -f)/fullchain.pem"
PANEL_KEY="/etc/letsencrypt/live/$(hostname -f)/privkey.pem"
if [[ -f "$PANEL_CERT" ]]; then
    postconf -e "smtpd_tls_cert_file = $PANEL_CERT"
    postconf -e "smtpd_tls_key_file = $PANEL_KEY"
else
    postconf -e "smtpd_tls_cert_file = /etc/ssl/certs/ssl-cert-snakeoil.pem"
    postconf -e "smtpd_tls_key_file = /etc/ssl/private/ssl-cert-snakeoil.key"
fi
postconf -e "smtpd_tls_security_level = may"
postconf -e "smtp_tls_security_level = may"
postconf -e "smtpd_tls_protocols = !SSLv2,!SSLv3"

# Rspamd milter (solo si el CPU soporta SSSE3)
if [[ "$INSTALL_RSPAMD" == true ]]; then
    postconf -e "smtpd_milters = inet:localhost:11332"
    postconf -e "non_smtpd_milters = inet:localhost:11332"
    postconf -e "milter_default_action = accept"
    postconf -e "milter_protocol = 6"
else
    # Sin Rspamd: limpiar cualquier milter anterior
    postconf -e "smtpd_milters ="
    postconf -e "non_smtpd_milters ="
fi

# Hostname y origen
hostname -f > /etc/mailname
postconf -e "myhostname = $(hostname -f)"
postconf -e "myorigin = /etc/mailname"

# ── SRS (Sender Rewriting Scheme) ──────────────────────────────────────────────
# Cuando un alias/reenvío reenvía correo a Gmail/Outlook/etc., el envelope-from
# original (de OTRO dominio) hace que el destino compruebe SPF contra NUESTRA IP
# → SPF fail → reenviamos la mala reputación ajena y acabamos en listas negras.
# postsrsd reescribe el envelope-from al reenviar a "...@<nuestro dominio>" (que
# SÍ tiene nuestra IP en su SPF) y descodifica los rebotes de vuelta al original.
# Estándar de la industria (cPanel/Plesk/Hestia lo hacen igual).
echo -e "${YELLOW}→ Instalando SRS (postsrsd) para reenvíos seguros...${NC}"
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postsrsd 2>/dev/null || true
if command -v postsrsd >/dev/null 2>&1 || dpkg -l postsrsd 2>/dev/null | grep -q '^ii'; then
    # Dominio de reescritura: el dominio del servidor (su SPF incluye esta IP).
    SRS_DOM="$(postconf -h mydomain 2>/dev/null || hostname -d)"
    # postsrsd 1.x (Debian 12/13) usa /etc/default/postsrsd (formato shell).
    if [ -f /etc/default/postsrsd ]; then
        sed -i "s/^#*SRS_DOMAIN=.*/SRS_DOMAIN=${SRS_DOM}/" /etc/default/postsrsd
        grep -q '^SRS_DOMAIN=' /etc/default/postsrsd || echo "SRS_DOMAIN=${SRS_DOM}" >> /etc/default/postsrsd
    fi
    systemctl enable postsrsd 2>/dev/null || true
    systemctl restart postsrsd 2>/dev/null || true
    # Enchufar a Postfix (forward=10001, reverse=10002; loopback).
    postconf -e "sender_canonical_maps = tcp:127.0.0.1:10001"
    postconf -e "sender_canonical_classes = envelope_sender"
    postconf -e "recipient_canonical_maps = tcp:127.0.0.1:10002"
    postconf -e "recipient_canonical_classes = envelope_recipient,header_recipient"
    echo -e "${GREEN}✓ SRS activo (reenvíos reescritos a @${SRS_DOM})${NC}"
else
    echo -e "${YELLOW}⚠ postsrsd no disponible; reenvíos sin SRS (riesgo de blacklist)${NC}"
fi

# Puerto 587 (submission / STARTTLS) — solo añadir si no está ya
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

# Puerto 465 (smtps / implicit TLS) — RFC 8314, compatible con todos los clientes
if ! grep -q "^smtps" /etc/postfix/master.cf; then
    cat >> /etc/postfix/master.cf << 'MASTEREOF'

smtps     inet  n       -       y       -       -       smtpd
  -o syslog_name=postfix/smtps
  -o smtpd_tls_wrappermode=yes
  -o smtpd_sasl_auth_enable=yes
  -o smtpd_reject_unlisted_recipient=no
  -o smtpd_recipient_restrictions=permit_sasl_authenticated,reject
  -o milter_macro_daemon_name=ORIGINATING
MASTEREOF
fi

systemctl enable postfix
systemctl restart postfix
echo -e "${GREEN}✓ Postfix configurado (SMTP 25 + submission 587 + smtps 465)${NC}"

# ── 3. DOVECOT ────────────────────────────────────────────────────────────────
echo -e "${YELLOW}→ Instalando Dovecot...${NC}"
apt-get install -y -qq dovecot-core dovecot-imapd dovecot-pop3d dovecot-lmtpd

# Dovecot 2.4 (Debian 13/trixie) cambió la sintaxis de config respecto a 2.3
# (Debian 12/bookworm). Detectamos la major para emitir la sintaxis correcta.
DOVECOT_MAJOR=$(dovecot --version 2>/dev/null | grep -oE '^[0-9]+\.[0-9]+' | head -1)
# >= 2.4 si al ordenar (2.4, version) queda 2.4 primero (2.4 <= version).
if printf '2.4\n%s\n' "$DOVECOT_MAJOR" | sort -V -C; then
    DOVECOT_24=true    # versión >= 2.4
else
    DOVECOT_24=false   # versión < 2.4
fi
echo -e "  Dovecot ${DOVECOT_MAJOR:-?} (sintaxis $([ "$DOVECOT_24" = true ] && echo 2.4 || echo 2.3))"

# Usuario vmail (uid/gid 5000) — propietario de todos los Maildir
groupadd -g 5000 vmail 2>/dev/null || true
useradd -u 5000 -g vmail -d /var/mail -s /usr/sbin/nologin vmail 2>/dev/null || true

# Fichero de usuarios virtual (gestionado por el panel)
touch /etc/dovecot/users
chmod 640 /etc/dovecot/users
chown root:dovecot /etc/dovecot/users

# Auth: passwd-file con ruta de buzón explícita por usuario
# OJO: en userdb el username_format va DENTRO de args (no como setting suelto,
# que Dovecot rechaza con "Unknown setting: userdb { username_format").
if [ "$DOVECOT_24" = true ]; then
  # Dovecot 2.4: passdb/userdb requieren nombre de sección y claves propias.
  cat > /etc/dovecot/conf.d/auth-passwdfile.conf.ext << 'DOVEAUTHEOF'
passdb passwd-file {
  passwd_file_path = /etc/dovecot/users
  default_password_scheme = SHA512-CRYPT
}
userdb passwd-file {
  passwd_file_path = /etc/dovecot/users
}
DOVEAUTHEOF
else
  cat > /etc/dovecot/conf.d/auth-passwdfile.conf.ext << 'DOVEAUTHEOF'
passdb {
  driver = passwd-file
  args = scheme=SHA512-CRYPT username_format=%u /etc/dovecot/users
}
userdb {
  driver = passwd-file
  args = username_format=%u /etc/dovecot/users
}
DOVEAUTHEOF
fi

# Desactivar auth del sistema, activar passwd-file
sed -i 's/^!include auth-system.conf.ext/#!include auth-system.conf.ext/' \
    /etc/dovecot/conf.d/10-auth.conf
# El 10-auth.conf por defecto trae la línea COMENTADA (#!include auth-passwdfile…),
# así que primero la descomentamos si existe; y si no existe en absoluto, la añadimos.
# (Un grep ingenuo de "auth-passwdfile.conf.ext" encontraría la comentada y nunca
#  activaría el include → "No passdbs specified" y todo el correo caído.)
if grep -q '^#!include auth-passwdfile.conf.ext' /etc/dovecot/conf.d/10-auth.conf; then
    sed -i 's/^#!include auth-passwdfile.conf.ext/!include auth-passwdfile.conf.ext/' \
        /etc/dovecot/conf.d/10-auth.conf
elif ! grep -q '^!include auth-passwdfile.conf.ext' /etc/dovecot/conf.d/10-auth.conf; then
    echo "!include auth-passwdfile.conf.ext" >> /etc/dovecot/conf.d/10-auth.conf
fi

# Permitir auth plaintext (los clientes deben usar STARTTLS/TLS en producción)
if [ "$DOVECOT_24" = true ]; then
    # Dovecot 2.4: disable_plaintext_auth → auth_allow_cleartext (lógica invertida)
    sed -i 's/^#\?disable_plaintext_auth = .*/auth_allow_cleartext = yes/' \
        /etc/dovecot/conf.d/10-auth.conf
    grep -q '^auth_allow_cleartext' /etc/dovecot/conf.d/10-auth.conf || \
        echo "auth_allow_cleartext = yes" >> /etc/dovecot/conf.d/10-auth.conf
else
    sed -i 's/^#\?disable_plaintext_auth = yes/disable_plaintext_auth = no/' \
        /etc/dovecot/conf.d/10-auth.conf
fi

# Mecanismos compatibles con todos los clientes
grep -q "^auth_mechanisms" /etc/dovecot/conf.d/10-auth.conf || \
    sed -i 's/^#auth_mechanisms = plain/auth_mechanisms = plain login/' \
        /etc/dovecot/conf.d/10-auth.conf

# Maildir: el home del passwd-file es la raíz del buzón
if [ "$DOVECOT_24" = true ]; then
    # Dovecot 2.4: mail_location → mail_driver + mail_path
    if ! grep -q "^mail_driver = maildir" /etc/dovecot/conf.d/10-mail.conf; then
        # Comentar cualquier mail_location heredado del default (mbox) y fijar maildir
        sed -i 's/^mail_location = .*/# (migrado a mail_driver\/mail_path)/' \
            /etc/dovecot/conf.d/10-mail.conf
        printf 'mail_driver = maildir\nmail_path = ~/\n' >> /etc/dovecot/conf.d/10-mail.conf
    fi
else
    grep -q "^mail_location = maildir" /etc/dovecot/conf.d/10-mail.conf || \
        echo "mail_location = maildir:~/" >> /etc/dovecot/conf.d/10-mail.conf
fi

# Socket SASL para que Postfix autentique via Dovecot
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

# Plugin de cuota: sin esto Dovecot NI aplica las cuotas por buzón NI permite
# consultarlas (doveadm quota get). El backend escribe quota_rule en
# /etc/dovecot/users; aquí activamos el plugin que lo hace efectivo y expone el
# uso real para mostrarlo en el panel.
if [ "$DOVECOT_24" = true ]; then
  # Dovecot 2.4: mail_plugins en bloque + bloque quota con driver count.
  cat > /etc/dovecot/conf.d/90-svqpanel-quota.conf << 'DOVEQUOTAEOF'
# SVQPanel: cuotas por buzón (Dovecot 2.4)
mail_plugins {
  quota = yes
}
protocol imap {
  mail_plugins {
    imap_quota = yes
  }
}
quota "User quota" {
  driver = count
}
quota_exceeded_message = Buzon lleno: el usuario %{user} ha superado su cuota de almacenamiento.
DOVEQUOTAEOF
else
  cat > /etc/dovecot/conf.d/90-svqpanel-quota.conf << 'DOVEQUOTAEOF'
# SVQPanel: cuotas por buzón (backend maildir, por usuario vía userdb quota_rule)
mail_plugins = $mail_plugins quota
plugin {
  quota = maildir:User quota
}
DOVEQUOTAEOF
fi

# LMTP: el passwd-file indexa por email COMPLETO (user@dominio). El paquete de
# Dovecot 2.4 mete en 20-lmtp.conf 'auth_username_format = %{user | username |
# lower}', que recorta el dominio y rompe la entrega ('User doesn't exist' en
# RCPT TO). Forzamos %{user} (email completo) en un dropin 99- que carga después.
cat > /etc/dovecot/conf.d/99-svqpanel-lmtp.conf << 'DOVELMTPEOF'
# SVQPanel: el LMTP debe buscar el buzón por email COMPLETO (no recortar dominio).
protocol lmtp {
  auth_username_format = %{user}
}
DOVELMTPEOF

# Carpetas especiales (Enviados/Borradores/Spam/Papelera) con auto-creación y
# auto-suscripción. Por defecto Dovecot las trae con `auto = no`: existen como
# definición pero NO se crean ni se suscriben en buzones nuevos, así que clientes
# como Thunderbird solo muestran Bandeja de Entrada y Papelera (Roundcube las ve
# porque las crea al vuelo). Con `auto = subscribe` Dovecot las crea y suscribe,
# y al llevar special_use el cliente las reconoce por su rol (Sent/Drafts/Junk/
# Trash) y las coloca bien. Este drop-in (99-) sobreescribe al 15-mailboxes.conf.
cat > /etc/dovecot/conf.d/99-svqpanel-mailboxes.conf << 'DOVEMBOXEOF'
# SVQPanel: carpetas especiales auto-creadas y auto-suscritas (Thunderbird et al)
namespace inbox {
  mailbox Drafts {
    auto = subscribe
    special_use = \Drafts
  }
  mailbox Sent {
    auto = subscribe
    special_use = \Sent
  }
  mailbox Junk {
    auto = subscribe
    special_use = \Junk
  }
  mailbox Trash {
    auto = subscribe
    special_use = \Trash
  }
}
DOVEMBOXEOF

# Asegurar que el servicio imap también carga el plugin quota.
# (En Dovecot 2.4 esto ya se declara en 90-svqpanel-quota.conf con el bloque
#  protocol imap { mail_plugins { imap_quota } }, así que solo aplica a 2.3.)
if [ "$DOVECOT_24" != true ]; then
  if ! grep -q 'mail_plugins.*quota' /etc/dovecot/conf.d/20-imap.conf 2>/dev/null; then
    cat >> /etc/dovecot/conf.d/20-imap.conf << 'DOVEIMAPQUOTAEOF'
protocol imap {
  mail_plugins = $mail_plugins quota imap_quota
}
DOVEIMAPQUOTAEOF
  fi
fi

systemctl enable dovecot
systemctl restart dovecot
echo -e "${GREEN}✓ Dovecot configurado (IMAP 143/993, POP3 110/995)${NC}"

# ── 4. REDIS + RSPAMD (requieren SSSE3) ──────────────────────────────────────
if [[ "$INSTALL_RSPAMD" == true ]]; then
    echo -e "${YELLOW}→ Instalando Redis...${NC}"
    apt-get install -y -qq redis-server
    systemctl enable redis-server
    systemctl start redis-server
    echo -e "${GREEN}✓ Redis instalado (backend de Rspamd)${NC}"

    echo -e "${YELLOW}→ Instalando Rspamd...${NC}"

    RSPAMD_CODENAME="$(lsb_release -cs)"
    # Rspamd stable puede no tener trixie → fallback a bookworm
    if [[ "$RSPAMD_CODENAME" == "trixie" ]]; then
        RSPAMD_CODENAME="bookworm"
        echo -e "  ${YELLOW}(usando repositorio bookworm para Rspamd en Debian 13)${NC}"
    fi

    curl -fsSL https://rspamd.com/apt-stable/gpg.key 2>/dev/null \
        | gpg --dearmor > /usr/share/keyrings/rspamd-archive-keyring.gpg
    echo "deb [signed-by=/usr/share/keyrings/rspamd-archive-keyring.gpg] https://rspamd.com/apt-stable/ ${RSPAMD_CODENAME} main" \
        > /etc/apt/sources.list.d/rspamd.list
    apt-get update -qq
    apt-get install -y -qq rspamd

    # Directorio para claves DKIM
    mkdir -p /etc/rspamd/dkim
    chown -R _rspamd:_rspamd /etc/rspamd/dkim 2>/dev/null || \
        chown -R rspamd:rspamd /etc/rspamd/dkim 2>/dev/null || true
    chmod 700 /etc/rspamd/dkim

    # Backend Redis
    cat > /etc/rspamd/local.d/redis.conf << 'RSPAMDREDISEOF'
servers = "127.0.0.1";
RSPAMDREDISEOF

    # DKIM signing dinámico por dominio
    cat > /etc/rspamd/local.d/dkim_signing.conf << 'RSPAMDKIMEOF'
path = "/etc/rspamd/dkim/$domain.$selector.key";
selector_map = "/etc/rspamd/dkim/selectors.map";
use_domain = "header";
allow_username_mismatch = true;
sign_local = true;
sign_authenticated = true;
RSPAMDKIMEOF

    touch /etc/rspamd/dkim/selectors.map

    # Cabeceras de autenticación en mensajes entrantes
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

    # ── Antivirus por dominio vía Rspamd (requiere SSSE3, ya garantizado aquí) ─
    # El escaneo ClamAV es global; el RECHAZO se aplica por dominio (lo decide
    # svqpanel_antivirus.lua según el mapa que gestiona el panel).
    cat > /etc/rspamd/local.d/antivirus.conf << 'RSPAMDAVEOF'
# SVQPanel — escaneo antivirus con ClamAV. El rechazo selectivo por dominio lo
# decide svqpanel_antivirus.lua (lee el mapa de dominios con antivirus activado).
clamav {
  type = "clamav";
  symbol = "CLAM_VIRUS";
  servers = "/var/run/clamav/clamd.ctl";
  scan_mime_parts = true;
}
RSPAMDAVEOF

    # ── Resolver DNS para Rspamd ──────────────────────────────────────────────
    # Las DNSBL (Spamhaus/URIBL/dnswl…) BLOQUEAN las consultas desde resolvers
    # públicos (8.8.8.8, 1.1.1.1) devolviendo 127.0.0.1 o respuestas falsas, lo
    # que tira las listas y empeora el antispam. Hay que usar un resolver propio:
    # aquí el BIND local (127.0.0.1) que el panel ya instala para el DNS de los
    # dominios. Así las listas vuelven a responder correctamente.
    cat > /etc/rspamd/local.d/options.inc << 'RSPAMDDNSEOF'
dns {
  nameserver = ["127.0.0.1"];
  timeout = 1s;
  sockets = 16;
  retransmits = 5;
}
RSPAMDDNSEOF

    systemctl enable rspamd
    systemctl restart rspamd
    echo -e "${GREEN}✓ Rspamd configurado (antispam + DKIM + greylisting + Bayes + ClamAV)${NC}"
else
    echo -e "${YELLOW}⚠ Rspamd y Redis omitidos (CPU sin SSSE3)${NC}"
    echo -e "  ${YELLOW}El correo funcionará sin antispam ni DKIM automático;${NC}"
    echo -e "  ${YELLOW}el antivirus se aplicará de forma GLOBAL vía clamav-milter.${NC}"
fi

# ── 5b. ANTIVIRUS CLAMAV (siempre, con o sin Rspamd) ──────────────────────────
# ClamAV se instala SIEMPRE para tener antivirus de correo. Hay dos modos:
#   • Con SSSE3 (Rspamd)  → escaneo por Rspamd, rechazo POR DOMINIO (lo gestiona
#                           el panel con su mapa+Lua). antivirus.conf ya escrito.
#   • Sin SSSE3 (milter)  → clamav-milter enganchado a Postfix, GLOBAL. No depende
#                           de Rspamd ni de SSSE3, así que funciona en cualquier CPU.
echo -e "${YELLOW}→ Instalando ClamAV (antivirus de correo)...${NC}"
apt-get install -y -qq clamav clamav-daemon 2>/dev/null || true

# Auto-actualización de firmas: el servicio freshclam (24×/día, sobrevive
# reinicios). Lo habilitamos en background tras una primera descarga de firmas
# (freshclam tarda; no bloquear el install).
systemctl stop clamav-freshclam 2>/dev/null || true
(freshclam >/dev/null 2>&1
 systemctl enable --now clamav-daemon 2>/dev/null
 systemctl enable --now clamav-freshclam 2>/dev/null) &

if [[ "$INSTALL_RSPAMD" != true ]]; then
    # Modo milter global (CPU sin SSSE3). El panel puede activarlo/desactivarlo
    # luego desde Administración → Seguridad; aquí lo dejamos instalado y listo.
    echo -e "${YELLOW}→ Configurando clamav-milter (antivirus global)...${NC}"
    apt-get install -y -qq clamav-milter 2>/dev/null || true
    cat > /etc/clamav/clamav-milter.conf << 'MILTEREOF'
# SVQPanel — clamav-milter (antivirus global). Generado automáticamente.
PidFile /var/run/clamav/clamav-milter.pid
MilterSocket inet:7357@127.0.0.1
FixStaleSocket true
User clamav
ClamdSocket unix:/var/run/clamav/clamd.ctl
OnInfected Reject
OnClean Accept
OnFail Defer
AddHeader Replace
LogSyslog true
LogInfected Full
MaxFileSize 50M
RejectMsg Mensaje rechazado: virus detectado (%v)
MILTEREOF
    systemctl enable clamav-milter 2>/dev/null || true
    systemctl restart clamav-milter 2>/dev/null || true
    # Enganchar a Postfix (TCP porque Postfix corre chrooted y no ve el socket unix)
    EXISTING_MILTERS="$(postconf -h smtpd_milters 2>/dev/null)"
    if ! echo "$EXISTING_MILTERS" | grep -q '7357'; then
        postconf -e "smtpd_milters = ${EXISTING_MILTERS} inet:localhost:7357"
        postconf -e "non_smtpd_milters = $(postconf -h non_smtpd_milters 2>/dev/null) inet:localhost:7357"
        systemctl reload postfix 2>/dev/null || true
    fi
    echo -e "${GREEN}✓ Antivirus global (clamav-milter) configurado${NC}"
fi

# ── 6. ACTIVAR EN .env ────────────────────────────────────────────────────────
echo -e "${YELLOW}→ Actualizando .env...${NC}"

# Reemplazar si ya existe, añadir si no
if grep -q "^MAIL_ENABLED=" "$ENV_FILE"; then
    sed -i 's/^MAIL_ENABLED=.*/MAIL_ENABLED=true/' "$ENV_FILE"
else
    echo "MAIL_ENABLED=true" >> "$ENV_FILE"
fi
echo -e "${GREEN}✓ MAIL_ENABLED=true en .env${NC}"

# ── 7. REINICIAR SVQPANEL ─────────────────────────────────────────────────────
echo -e "${YELLOW}→ Reiniciando SVQPanel...${NC}"
systemctl restart svqpanel
sleep 2
if systemctl is-active --quiet svqpanel; then
    echo -e "${GREEN}✓ SVQPanel reiniciado correctamente${NC}"
else
    echo -e "${RED}✗ SVQPanel no arrancó — revisa: journalctl -u svqpanel -n 50${NC}"
fi

# ── 8. RESUMEN ────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║       Módulo de correo instalado correctamente           ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  Estado de servicios:"
for SVC in postfix dovecot; do
    if systemctl is-active --quiet "$SVC"; then
        echo -e "    ${GREEN}✓ $SVC${NC}"
    else
        echo -e "    ${RED}✗ $SVC  ← revisar: journalctl -u $SVC${NC}"
    fi
done
if [[ "$INSTALL_RSPAMD" == true ]]; then
    for SVC in rspamd redis-server; do
        if systemctl is-active --quiet "$SVC"; then
            echo -e "    ${GREEN}✓ $SVC${NC}"
        else
            echo -e "    ${RED}✗ $SVC  ← revisar: journalctl -u $SVC${NC}"
        fi
    done
else
    echo -e "    ${YELLOW}⚠ rspamd — no instalado (CPU sin SSSE3, sin antispam/DKIM)${NC}"
fi
echo ""
echo "  Puertos:"
echo "    • 25   — SMTP entrada (necesita rDNS + MX)"
echo "    • 587  — SMTP envío con STARTTLS (clientes de correo)"
echo "    • 143  — IMAP (Dovecot)"
echo "    • 993  — IMAPS (Dovecot TLS)"
echo "    • 110  — POP3 (Dovecot)"
echo "    • 995  — POP3S (Dovecot TLS)"
echo ""
echo -e "  ${YELLOW}Próximos pasos:${NC}"
echo "    1. En el panel → Correo → añade un dominio de correo"
echo "    2. En ese dominio → pestaña DKIM → genera la clave"
echo "    3. Añade el registro TXT en tu DNS externo (si no usas el DNS del panel)"
echo "    4. Cuando tengas cert SSL real (Let's Encrypt), sustituye el snakeoil:"
echo "       postconf -e 'smtpd_tls_cert_file = /ruta/fullchain.pem'"
echo "       postconf -e 'smtpd_tls_key_file  = /ruta/privkey.pem'"
echo "       systemctl restart postfix"
echo ""
