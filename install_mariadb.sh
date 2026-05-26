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

-- Crear con permisos mínimos necesarios:
--   CREATE/DROP     → gestionar BDs de clientes
--   CREATE USER     → crear/eliminar usuarios por BD
--   GRANT OPTION    → asignar privilegios a esos usuarios
--   RELOAD          → FLUSH PRIVILEGES
-- NOTA: information_schema NO necesita GRANT explícito — MariaDB da acceso
--       automático a todos los usuarios autenticados (BD virtual, no real).
CREATE USER 'svqpanel_admin'@'localhost'
    IDENTIFIED BY '${MARIADB_PANEL_PASS}';

GRANT CREATE, DROP, RELOAD, GRANT OPTION, CREATE USER
    ON *.* TO 'svqpanel_admin'@'localhost';

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
echo "  POST   /api/databases              → crear BD de cliente"
echo "  GET    /api/databases              → listar BDs"
echo "  PUT    /api/databases/{id}/password → cambiar contraseña"
echo "  DELETE /api/databases/{id}          → eliminar BD"
echo "  GET    /api/databases/charsets      → ver charsets disponibles"
echo ""
echo -e "${RED}⚠ IMPORTANTE:${NC}"
echo "  • root usa unix_socket (solo accesible como root del SO — no hay contraseña de red)"
echo "  • El panel usa solo svqpanel_admin — root no es necesario para el panel"
echo "  • Las BDs de clientes son locales (localhost:3306) — no exponer a internet"
