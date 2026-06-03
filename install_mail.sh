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
if grep -q "ssse3" /proc/cpuinfo; then
    INSTALL_RSPAMD=true
else
    INSTALL_RSPAMD=false
    echo -e "${YELLOW}⚠ CPU sin instrucciones SSSE3 — Rspamd no es compatible con este procesador${NC}"
    echo -e "  ${YELLOW}Se instalará Postfix + Dovecot sin antispam (DKIM requiere Rspamd)${NC}"
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
sed -i 's/^#\?disable_plaintext_auth = yes/disable_plaintext_auth = no/' \
    /etc/dovecot/conf.d/10-auth.conf

# Mecanismos compatibles con todos los clientes
grep -q "^auth_mechanisms" /etc/dovecot/conf.d/10-auth.conf || \
    sed -i 's/^#auth_mechanisms = plain/auth_mechanisms = plain login/' \
        /etc/dovecot/conf.d/10-auth.conf

# Maildir: el home del passwd-file es la raíz del buzón
grep -q "^mail_location = maildir" /etc/dovecot/conf.d/10-mail.conf || \
    echo "mail_location = maildir:~/" >> /etc/dovecot/conf.d/10-mail.conf

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

    systemctl enable rspamd
    systemctl restart rspamd
    echo -e "${GREEN}✓ Rspamd configurado (antispam + DKIM + greylisting + Bayes)${NC}"
else
    echo -e "${YELLOW}⚠ Rspamd y Redis omitidos (CPU sin SSSE3)${NC}"
    echo -e "  ${YELLOW}El servidor de correo funcionará sin antispam ni firma DKIM automática${NC}"
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
