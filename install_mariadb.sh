#!/bin/bash

###############################################################################
# SVQPanel — Instalador independiente de MariaDB 11.4 LTS
#
# Para servidores con SVQPanel ya instalado que quieran añadir MariaDB.
# Ejecutar como root:
#   curl -O https://raw.githubusercontent.com/coriaweb/SVQPanel/main/install_mariadb.sh
#   chmod +x install_mariadb.sh && bash install_mariadb.sh
###############################################################################

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SVQPANEL_DIR="/opt/svqpanel"
ENV_FILE="$SVQPANEL_DIR/.env"
CREDS_DIR="$SVQPANEL_DIR/.credentials"

echo -e "${YELLOW}══════════════════════════════════════════${NC}"
echo -e "${YELLOW}  SVQPanel — Instalador MariaDB 11.4 LTS  ${NC}"
echo -e "${YELLOW}══════════════════════════════════════════${NC}\n"

###############################################################################
# 1. VERIFICACIONES PREVIAS
###############################################################################
echo -e "${BLUE}[1/6] Verificaciones previas...${NC}"

# Debe ser root
if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}Error: Este script debe ejecutarse como root.${NC}"
    exit 1
fi

# Debe ser Debian 12 o 13
if [[ ! -f /etc/os-release ]]; then
    echo -e "${RED}Error: No se puede detectar el SO.${NC}"
    exit 1
fi
# shellcheck disable=SC1091
source /etc/os-release
if [[ "$ID" != "debian" ]] || [[ "$VERSION_ID" != "12" && "$VERSION_ID" != "13" ]]; then
    echo -e "${RED}Error: Solo Debian 12/13. Detectado: $ID $VERSION_ID${NC}"
    exit 1
fi
echo -e "  ✓ Debian $VERSION_ID detectado"

# SVQPanel debe estar instalado
if [[ ! -d "$SVQPANEL_DIR" ]]; then
    echo -e "${RED}Error: SVQPanel no encontrado en $SVQPANEL_DIR${NC}"
    echo "  Instala SVQPanel primero con install.sh"
    exit 1
fi
echo -e "  ✓ SVQPanel encontrado en $SVQPANEL_DIR"

# Comprobar si MariaDB ya está instalado
if command -v mysql &>/dev/null && systemctl is-active --quiet mariadb 2>/dev/null; then
    echo -e "  ${YELLOW}⚠ MariaDB ya está instalado y activo.${NC}"
    read -rp "  ¿Continuar igualmente? (solo reconfigura el usuario del panel) (s/N): " _CONT
    if [[ ! "${_CONT,,}" =~ ^(s|si|y|yes)$ ]]; then
        echo "Abortado."
        exit 0
    fi
fi

echo -e "${GREEN}✓ Verificaciones OK${NC}\n"

###############################################################################
# 2. INSTALAR MARIADB 11.4 LTS
###############################################################################
echo -e "${BLUE}[2/6] Instalando MariaDB 11.4 LTS desde repositorio oficial...${NC}"

# Repositorio oficial de MariaDB (siempre la versión más reciente del LTS)
curl -LsS https://r.mariadb.com/downloads/mariadb_repo_setup \
    | bash -s -- --mariadb-server-version="mariadb-11.4" > /dev/null 2>&1

apt-get update -qq
apt-get install -y mariadb-server mariadb-client

systemctl enable mariadb
systemctl start mariadb

# Verificar que el binario cliente está disponible
MARIADB_BIN=""
for BIN in /usr/bin/mariadb /usr/bin/mysql; do
    if [[ -x "$BIN" ]]; then
        MARIADB_BIN="$BIN"
        break
    fi
done

if [[ -z "$MARIADB_BIN" ]]; then
    echo -e "${RED}Error: binario cliente mariadb no encontrado tras instalar mariadb-client${NC}"
    exit 1
fi

echo -e "${GREEN}✓ MariaDB instalado — cliente: $MARIADB_BIN${NC}\n"

###############################################################################
# 3. GENERAR CONTRASEÑAS ALEATORIAS
###############################################################################
echo -e "${BLUE}[3/6] Generando credenciales seguras...${NC}"

# Contraseña del usuario administrador del panel (root mantiene unix_socket auth)
MARIADB_PANEL_PASS=$(python3 -c \
    "import secrets,string; \
     chars=string.ascii_letters+string.digits; \
     print(''.join(secrets.choice(chars) for _ in range(24)))")

echo -e "  ✓ Contraseña svqpanel_admin generada (24 chars, aleatoria)"
echo -e "${GREEN}✓ Credenciales listas${NC}\n"

###############################################################################
# 4. ASEGURAR MARIADB + CREAR USUARIO DEL PANEL
###############################################################################
echo -e "${BLUE}[4/6] Asegurando MariaDB y creando usuario svqpanel_admin...${NC}"

# Verificar que podemos conectar como root (usa unix_socket auth por defecto en Debian)
if ! mariadb --user=root -e "SELECT 1;" > /dev/null 2>&1; then
    echo -e "${RED}Error: No se puede conectar a MariaDB como root.${NC}"
    echo "  Si root tiene contraseña, ejecúta manualmente:"
    echo "    systemctl stop mariadb"
    echo "    mysqld_safe --skip-grant-tables &"
    echo "    sleep 3"
    echo "    mariadb -e \"ALTER USER 'root'@'localhost' IDENTIFIED VIA unix_socket;\""
    echo "    systemctl restart mariadb"
    exit 1
fi

mariadb --user=root << MARIADBEOF
-- ── Hardening básico ──────────────────────────────────────────────────────
-- Eliminar cuentas anónimas
DELETE FROM mysql.user WHERE User='';
-- Deshabilitar acceso root remoto (seguridad; root solo local via unix_socket)
DELETE FROM mysql.user WHERE User='root' AND Host NOT IN ('localhost', '127.0.0.1', '::1');
-- Eliminar BD de prueba
DROP DATABASE IF EXISTS test;
DELETE FROM mysql.db WHERE Db='test' OR Db='test\\_%';

-- ── Usuario administrador del panel ───────────────────────────────────────
-- Eliminar si existe (idempotente — permite re-ejecutar el script)
DROP USER IF EXISTS 'svqpanel_admin'@'localhost';

-- Crear con permisos necesarios para gestionar BDs de clientes:
--   Privilegios de datos (SELECT..TRIGGER) → puede otorgarlos a usuarios cliente
--   CREATE USER / DROP    → crear/eliminar usuarios y BDs
--   RELOAD                → FLUSH PRIVILEGES
--   WITH GRANT OPTION     → imprescindible para "GRANT ALL ON db.* TO cliente"
--   Solo acceso local (localhost) — no expuesto a red
-- NOTA: information_schema NO necesita GRANT — acceso automático a todos los usuarios.
CREATE USER 'svqpanel_admin'@'localhost'
    IDENTIFIED BY '${MARIADB_PANEL_PASS}';

GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, INDEX, ALTER,
      CREATE TEMPORARY TABLES, LOCK TABLES, EXECUTE,
      CREATE VIEW, SHOW VIEW, CREATE ROUTINE, ALTER ROUTINE,
      EVENT, TRIGGER, CREATE USER, RELOAD
      ON *.* TO 'svqpanel_admin'@'localhost' WITH GRANT OPTION;

FLUSH PRIVILEGES;
MARIADBEOF

echo -e "  ✓ root → mantiene autenticación unix_socket (sin contraseña de red)"
echo -e "  ✓ svqpanel_admin → creado con permisos mínimos"
echo -e "${GREEN}✓ MariaDB asegurado${NC}\n"

###############################################################################
# 5. ACTUALIZAR .ENV DEL PANEL
###############################################################################
echo -e "${BLUE}[5/6] Actualizando $ENV_FILE...${NC}"

if [[ ! -f "$ENV_FILE" ]]; then
    echo -e "${RED}Error: No se encontró $ENV_FILE${NC}"
    echo "  Crea el archivo .env en $SVQPANEL_DIR manualmente."
    exit 1
fi

# Eliminar líneas anteriores de MariaDB si existieran (idempotente)
sed -i '/^MARIADB_/d' "$ENV_FILE"
sed -i '/^# MariaDB/d' "$ENV_FILE"

# Añadir configuración MariaDB al final
cat >> "$ENV_FILE" << ENVEOF

# MariaDB — bases de datos para clientes (añadido por install_mariadb.sh)
MARIADB_ENABLED=true
MARIADB_HOST=localhost
MARIADB_PANEL_USER=svqpanel_admin
MARIADB_PANEL_PASSWORD=${MARIADB_PANEL_PASS}
ENVEOF

echo -e "  ✓ Variables MARIADB_* escritas en .env"
echo -e "${GREEN}✓ .env actualizado${NC}\n"

###############################################################################
# 6. GUARDAR CREDENCIALES Y REINICIAR PANEL
###############################################################################
echo -e "${BLUE}[6/6] Guardando credenciales y reiniciando SVQPanel...${NC}"

mkdir -p "$CREDS_DIR"
cat > "$CREDS_DIR/mariadb.txt" << CREDEOF
# Credenciales MariaDB — SVQPanel
# Generado: $(date '+%Y-%m-%d %H:%M:%S')
# NO compartas este archivo

MariaDB root:
  autenticación: unix_socket (sin contraseña de red — más seguro)
  conexión local (como root del sistema): mariadb --user=root
  acceso remoto: DESACTIVADO por seguridad

Panel admin (usado internamente por SVQPanel):
  usuario: svqpanel_admin
  password: ${MARIADB_PANEL_PASS}
  conexión: mariadb -u svqpanel_admin -p

Conexión desde app de cliente (ejemplo):
  host: 127.0.0.1
  puerto: 3306
  usuario: {username}_{sufijo}   (creado via /api/databases)
  password: (la que el cliente elige al crear la BD)
CREDEOF
chmod 600 "$CREDS_DIR/mariadb.txt"
echo -e "  ✓ Credenciales guardadas en $CREDS_DIR/mariadb.txt"

# Reiniciar SVQPanel para que cargue el nuevo .env
if systemctl is-active --quiet svqpanel; then
    systemctl restart svqpanel
    sleep 2
    if systemctl is-active --quiet svqpanel; then
        echo -e "  ✓ SVQPanel reiniciado correctamente"
    else
        echo -e "  ${YELLOW}⚠ SVQPanel no arrancó — revisa: journalctl -u svqpanel -n 30${NC}"
    fi
else
    echo -e "  ${YELLOW}⚠ SVQPanel no estaba activo — inicia con: systemctl start svqpanel${NC}"
fi

###############################################################################
# 7. INSTALAR PHPMYADMIN CON AUTOLOGIN
###############################################################################
echo -e "${BLUE}[7/7] Instalando phpMyAdmin con autologin...${NC}"

PMA_VERSION="5.2.2"
PMA_DIR="/var/www/pma"
PMA_URL="https://files.phpmyadmin.net/phpMyAdmin/${PMA_VERSION}/phpMyAdmin-${PMA_VERSION}-all-languages.tar.gz"
PMA_TMP="/tmp/phpmyadmin.tar.gz"

# ── Dependencias PHP ──────────────────────────────────────────────────────────
# phpMyAdmin necesita php-mbstring, php-xml, php-curl y php-session (incluido en php-common)
apt-get install -y php-mbstring php-xml php-curl php-zip > /dev/null 2>&1
echo -e "  ✓ Dependencias PHP instaladas"

# ── Descargar phpMyAdmin ──────────────────────────────────────────────────────
echo -e "  Descargando phpMyAdmin ${PMA_VERSION}..."
curl -Lo "$PMA_TMP" "$PMA_URL" 2>/dev/null || wget -qO "$PMA_TMP" "$PMA_URL"
if [[ ! -f "$PMA_TMP" || ! -s "$PMA_TMP" ]]; then
    echo -e "  ${RED}Error: no se pudo descargar phpMyAdmin. Saltando...${NC}"
else
    rm -rf "${PMA_DIR:?}"
    mkdir -p "$PMA_DIR"
    tar xzf "$PMA_TMP" -C "$PMA_DIR" --strip-components=1
    rm -f "$PMA_TMP"
    chown -R www-data:www-data "$PMA_DIR"
    chmod -R 755 "$PMA_DIR"
    echo -e "  ✓ phpMyAdmin ${PMA_VERSION} extraído en $PMA_DIR"

    # ── Directorio temporal phpMyAdmin ────────────────────────────────────────
    mkdir -p /tmp/phpmyadmin
    chmod 777 /tmp/phpmyadmin

    # ── Generar clave de cifrado Fernet ───────────────────────────────────────
    PANEL_ENCRYPTION_KEY=$(python3 -c \
        "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    echo -e "  ✓ Clave de cifrado Fernet generada"

    # ── Generar secret para phpMyAdmin (blowfish) ─────────────────────────────
    PMA_BLOWFISH_SECRET=$(python3 -c \
        "import secrets, string; \
         chars = string.ascii_letters + string.digits; \
         print(''.join(secrets.choice(chars) for _ in range(56)))")

    # ── config.inc.php — signon auth (solo via panel, sin login directo) ─────
    cat > "${PMA_DIR}/config.inc.php" << PMACFGEOF
<?php
/**
 * phpMyAdmin — configuración SVQPanel
 * Autenticación exclusivamente via panel (token de un solo uso).
 * Acceso directo sin token → redirigido a login del panel.
 */

\$cfg['blowfish_secret'] = '${PMA_BLOWFISH_SECRET}';

\$i = 0;
\$i++;
\$cfg['Servers'][\$i]['host']          = '127.0.0.1';
\$cfg['Servers'][\$i]['port']          = '3306';
\$cfg['Servers'][\$i]['socket']        = '';
\$cfg['Servers'][\$i]['connect_type']  = 'tcp';
\$cfg['Servers'][\$i]['compress']      = false;
\$cfg['Servers'][\$i]['auth_type']     = 'signon';
\$cfg['Servers'][\$i]['SignonSession'] = 'SignonSession';
\$cfg['Servers'][\$i]['SignonURL']     = '/pma/signon.php';
\$cfg['Servers'][\$i]['LogoutURL']     = '/databases';
\$cfg['Servers'][\$i]['AllowRoot']     = false;   // root no puede entrar por phpMyAdmin

// Directorios
\$cfg['TempDir']    = '/tmp/phpmyadmin/';
\$cfg['UploadDir']  = '';
\$cfg['SaveDir']    = '';

// UI
\$cfg['ServerDefault']        = 1;
\$cfg['ShowChgPassword']      = true;
\$cfg['LoginCookieValidity']  = 1440;
\$cfg['SendErrorReports']     = 'never';
\$cfg['CheckConfigurationPermissions'] = false;
PMACFGEOF
    chmod 640 "${PMA_DIR}/config.inc.php"
    chown root:www-data "${PMA_DIR}/config.inc.php"
    echo -e "  ✓ config.inc.php creado (autenticación signon)"

    # ── signon.php — valida el token y arranca la sesión phpMyAdmin ───────────
    cat > "${PMA_DIR}/signon.php" << 'SIGNONEOF'
<?php
/**
 * SVQPanel — phpMyAdmin Single Sign-On
 *
 * Recibe ?token=<hex32> generado por la API del panel.
 * Lee /tmp/pma_tokens/{token}.json (uso único, expira en 5 min),
 * inicia la sesión de phpMyAdmin y redirige a la interfaz.
 */

$token = isset($_GET['token']) ? preg_replace('/[^a-f0-9]/', '', $_GET['token']) : '';

if (empty($token)) {
    header('Location: /');
    exit;
}

$token_file = '/tmp/pma_tokens/' . $token . '.json';

if (!file_exists($token_file)) {
    http_response_code(403);
    die('<p>Token inválido o expirado. <a href="/">Volver al panel</a></p>');
}

$raw  = file_get_contents($token_file);
$data = json_decode($raw, true);

// Eliminar inmediatamente — un solo uso
@unlink($token_file);

if (!$data || !isset($data['exp']) || time() > $data['exp']) {
    http_response_code(403);
    die('<p>Token expirado. <a href="/databases">Volver al panel</a></p>');
}

// Iniciar sesión phpMyAdmin (signon auth)
session_name('SignonSession');
session_start();
$_SESSION['PMA_single_signon_user']     = $data['user'];
$_SESSION['PMA_single_signon_password'] = $data['password'];
$_SESSION['PMA_single_signon_host']     = '127.0.0.1';
$_SESSION['PMA_single_signon_port']     = '';
session_write_close();

// Redirigir a phpMyAdmin — el usuario verá solo su BD
header('Location: /pma/index.php');
exit;
SIGNONEOF
    chmod 644 "${PMA_DIR}/signon.php"
    chown www-data:www-data "${PMA_DIR}/signon.php"
    echo -e "  ✓ signon.php creado"

    # Directorio de tokens (lo crea la API al primer uso, pero lo pre-creamos aquí)
    # 711: root crea/borra tokens; PHP-FPM (www-data) puede leerlos si conoce el nombre
    mkdir -p /tmp/pma_tokens
    chmod 711 /tmp/pma_tokens
    chown root:root /tmp/pma_tokens

    # ── Añadir PANEL_ENCRYPTION_KEY al .env ───────────────────────────────────
    sed -i '/^PANEL_ENCRYPTION_KEY/d' "$ENV_FILE"
    {
        echo ""
        echo "# Clave Fernet para phpMyAdmin autologin (generada por install_mariadb.sh)"
        echo "PANEL_ENCRYPTION_KEY=${PANEL_ENCRYPTION_KEY}"
    } >> "$ENV_FILE"
    echo -e "  ✓ PANEL_ENCRYPTION_KEY añadida a .env"

    # ── Detectar socket PHP-FPM disponible ───────────────────────────────────
    PHP_FPM_SOCK=$(find /run/php /var/run/php -name 'php*-fpm.sock' 2>/dev/null \
                   | sort -rV | head -1)
    if [[ -z "$PHP_FPM_SOCK" ]]; then
        echo -e "  ${YELLOW}⚠ No se encontró socket PHP-FPM. Instala php-fpm y ajusta nginx manualmente.${NC}"
    else
        echo -e "  ✓ PHP-FPM socket: $PHP_FPM_SOCK"

        # ── Inyectar bloque /pma en nginx (antes del catch-all location /) ────
        NGINX_CONF="/etc/nginx/sites-available/svqpanel"
        if [[ -f "$NGINX_CONF" ]]; then
            # Comprobar si ya existe el bloque /pma
            if grep -q "location /pma" "$NGINX_CONF"; then
                echo -e "  ${YELLOW}⚠ Bloque /pma ya existe en nginx — no se modifica${NC}"
            else
                # \$document_root y \$fastcgi_script_name: el \$ impide que bash los
                # expanda aquí; Python recibe el $ literal que nginx necesita.
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
    print("OK")
else:
    print("SKIP")
PYEOF
                echo -e "  ✓ Bloque /pma añadido a nginx"
                nginx -t && systemctl reload nginx && echo -e "  ✓ nginx recargado"
            fi
        else
            echo -e "  ${YELLOW}⚠ No se encontró $NGINX_CONF — configura nginx manualmente${NC}"
        fi
    fi

    echo -e "${GREEN}✓ phpMyAdmin instalado${NC}\n"
fi

# Reiniciar SVQPanel para que cargue PANEL_ENCRYPTION_KEY del .env
if systemctl is-active --quiet svqpanel; then
    systemctl restart svqpanel
    sleep 2
    if systemctl is-active --quiet svqpanel; then
        echo -e "  ✓ SVQPanel reiniciado correctamente"
    else
        echo -e "  ${YELLOW}⚠ SVQPanel no arrancó — revisa: journalctl -u svqpanel -n 30${NC}"
    fi
fi

###############################################################################
# RESUMEN
###############################################################################
echo ""
echo -e "${GREEN}════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ MariaDB 11.4 LTS instalado correctamente  ${NC}"
echo -e "${GREEN}════════════════════════════════════════════${NC}"
echo ""
echo -e "Estado de servicios:"
for SVC in mariadb svqpanel; do
    if systemctl is-active --quiet "$SVC" 2>/dev/null; then
        echo -e "  ${GREEN}✓ $SVC — activo${NC}"
    else
        echo -e "  ${RED}✗ $SVC — NO activo${NC}"
    fi
done
echo ""
echo -e "${YELLOW}Credenciales guardadas en:${NC}"
echo "  $CREDS_DIR/mariadb.txt  (chmod 600)"
echo ""
echo -e "${YELLOW}API disponible:${NC}"
echo "  POST   /api/databases                  → crear BD de cliente"
echo "  GET    /api/databases                  → listar BDs"
echo "  GET    /api/databases/{id}/pma-token   → token autologin phpMyAdmin"
echo "  PUT    /api/databases/{id}/password    → cambiar contraseña"
echo "  DELETE /api/databases/{id}             → eliminar BD"
echo "  GET    /api/databases/charsets         → ver charsets disponibles"
echo ""
if [[ -d /var/www/pma ]]; then
    echo -e "${YELLOW}phpMyAdmin:${NC}"
    echo "  URL:  http://TU_IP/pma/"
    echo "  Auth: Solo via panel (botón phpMyAdmin en /databases)"
    echo "  Cada usuario accede únicamente a su propia BD"
    echo ""
fi
echo -e "${RED}⚠ IMPORTANTE:${NC}"
echo "  • root usa unix_socket (solo accesible como root del SO — no hay contraseña de red)"
echo "  • El panel usa solo svqpanel_admin — root no es necesario para el panel"
echo "  • Las BDs de clientes son locales (localhost:3306) — no exponer a internet"
echo "  • phpMyAdmin solo acepta acceso via token del panel (no login directo)"
