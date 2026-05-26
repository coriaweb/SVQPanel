#!/bin/bash

###############################################################################
# SVQPanel - Update Script
# Actualiza SVQPanel en un servidor existente
# Uso: sudo bash update.sh
###############################################################################

set -e  # Salir si hay error

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Verificar que somos root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}Este script debe ser ejecutado como root (usa sudo)${NC}"
   exit 1
fi

echo -e "${BLUE}╔════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  SVQPanel - Script de Actualización║${NC}"
echo -e "${BLUE}╚════════════════════════════════════╝${NC}\n"

PANEL_DIR="/opt/svqpanel"
VENV_DIR="$PANEL_DIR/venv"

# Verificar que existe la instalación
if [[ ! -d "$PANEL_DIR" ]]; then
    echo -e "${RED}✗ SVQPanel no encontrado en $PANEL_DIR${NC}"
    echo "Por favor, instala primero con: sudo bash install.sh"
    exit 1
fi

echo -e "${YELLOW}1. Deteniendo servicio...${NC}"
systemctl stop svqpanel || true
echo -e "${GREEN}✓ Servicio detenido${NC}\n"

echo -e "${YELLOW}2. Hacer backup de configuración...${NC}"
mkdir -p "$PANEL_DIR/backups"
BACKUP_DATE=$(date +%Y%m%d_%H%M%S)
cp "$PANEL_DIR/.env" "$PANEL_DIR/backups/.env.$BACKUP_DATE" 2>/dev/null || true
echo -e "${GREEN}✓ Backup en backups/.env.$BACKUP_DATE${NC}\n"

echo -e "${YELLOW}3. Descargando cambios...${NC}"
cd "$PANEL_DIR"
git fetch origin
git pull origin main
echo -e "${GREEN}✓ Cambios descargados${NC}\n"

echo -e "${YELLOW}4. Actualizando dependencias Python...${NC}"
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r requirements.txt
deactivate
echo -e "${GREEN}✓ Dependencias actualizadas${NC}\n"

echo -e "${YELLOW}5. Actualizando frontend...${NC}"
if [[ -f "$PANEL_DIR/frontend/package.json" ]]; then
    cd "$PANEL_DIR/frontend"
    npm install
    npm run build
    echo -e "${GREEN}✓ Frontend compilado${NC}\n"
else
    echo -e "${YELLOW}⚠ Frontend no encontrado (opcional)${NC}\n"
fi

echo -e "${YELLOW}6. Ejecutando migraciones de BD...${NC}"
cd "$PANEL_DIR"
source "$VENV_DIR/bin/activate"

# Crear/actualizar todas las tablas (SQLAlchemy + migraciones incrementales)
python3 << 'PYEOF'
import sys
sys.path.insert(0, '/opt/svqpanel')
from api.models.database import Base, engine
# Importar todos los modelos para que SQLAlchemy los registre
from api.models.models_user import User
from api.models.models_domain import Domain
from api.models.models_settings import Settings
from api.models.models_dns import DnsZone, DnsRecord
from api.models.models_mail import MailDomain, Mailbox, MailAlias
from api.models.models_client_db import ClientDatabase   # ← Fase 10 MariaDB
Base.metadata.create_all(bind=engine)
print("✓ Tablas de BD verificadas/creadas")

# Migraciones incrementales (ADD COLUMN IF NOT EXISTS)
from sqlalchemy import text
migrations = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS databases_limit INTEGER DEFAULT 5",
    "ALTER TABLE settings ADD COLUMN IF NOT EXISTS network_interface VARCHAR(20) DEFAULT 'eth0'",
    # Fase 10: tabla client_databases (ya la crea create_all, pero por si acaso)
    """CREATE TABLE IF NOT EXISTS client_databases (
        id               SERIAL PRIMARY KEY,
        user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        domain_id        INTEGER REFERENCES domains(id) ON DELETE SET NULL,
        db_name          VARCHAR(64)  UNIQUE NOT NULL,
        db_name_suffix   VARCHAR(48)  NOT NULL,
        db_user          VARCHAR(64)  UNIQUE NOT NULL,
        db_user_suffix   VARCHAR(48)  NOT NULL,
        db_password_hash VARCHAR(255) NOT NULL,
        db_charset       VARCHAR(20)  DEFAULT 'utf8mb4',
        db_collation     VARCHAR(50)  DEFAULT 'utf8mb4_unicode_ci',
        quota_mb         INTEGER      DEFAULT 1024,
        size_mb          INTEGER      DEFAULT 0,
        is_active        BOOLEAN      DEFAULT TRUE,
        created_at       TIMESTAMP    DEFAULT NOW(),
        updated_at       TIMESTAMP    DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_client_databases_user_id  ON client_databases(user_id)",
    "CREATE INDEX IF NOT EXISTS ix_client_databases_domain_id ON client_databases(domain_id)",
]
with engine.connect() as conn:
    for sql in migrations:
        try:
            conn.execute(text(sql))
            conn.commit()
        except Exception as e:
            print(f"  (migración omitida: {e})")
print("✓ Migraciones completadas")
PYEOF

deactivate
echo -e "${GREEN}✓ Base de datos actualizada${NC}\n"

echo -e "${YELLOW}7. Reiniciando servicio...${NC}"
systemctl start svqpanel
sleep 2

# Verificar que el servicio está corriendo
if systemctl is-active --quiet svqpanel; then
    echo -e "${GREEN}✓ Servicio iniciado correctamente${NC}\n"
else
    echo -e "${RED}✗ Error al iniciar el servicio${NC}"
    echo "Verifica con: sudo journalctl -u svqpanel -f"
    exit 1
fi

echo -e "${YELLOW}8. Verificando salud de la API...${NC}"
sleep 1
HEALTH=$(curl -s http://localhost:8001/api/health || echo "error")
if [[ "$HEALTH" == *"ok"* ]]; then
    echo -e "${GREEN}✓ API respondiendo correctamente${NC}\n"
else
    echo -e "${YELLOW}⚠ API no responde, espera unos segundos y prueba${NC}\n"
fi

echo -e "${GREEN}╔═══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Actualización Completada ✓           ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════╝${NC}\n"

echo -e "${BLUE}Resumen de cambios:${NC}"
cd "$PANEL_DIR"
git log --oneline -5

echo -e "\n${BLUE}Próximos pasos:${NC}"
echo "1. Verifica los cambios: curl http://localhost:8001/api/health"
echo "2. Revisa logs si hay problemas: sudo journalctl -u svqpanel -f"
echo "3. Frontend (si aplica): http://localhost:5173"

echo -e "\n${YELLOW}Cambios importantes:${NC}"
echo "- Frontend: Nuevo en Fase 4 (Vue 3, componentes de formularios)"
echo "- Backend: Sistema de managers integrado (user, domain, ssl, ipv6)"
echo "- API: 17 endpoints ahora ejecutan comandos del SO"
echo "- Archivos: TESTING.md, COMPLETION_SUMMARY.md documentan todo"

echo -e "\n${GREEN}¡Actualización lista!${NC}\n"
