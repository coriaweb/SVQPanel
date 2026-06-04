#!/bin/bash

###############################################################################
# SVQPanel — Update Script
#
# ARQUITECTURA DE ACTUALIZACIONES
# ─────────────────────────────────────────────────────────────────────────────
# Cada cambio al sistema (nginx, PHP, seguridad, BD, etc.) se convierte en un
# archivo numerado en updates/NNNN-descripcion.sh. Este script:
#
#   1. Descarga el repo (git pull)
#   2. Lee /etc/svqpanel/applied_updates (lista de IDs ya aplicados)
#   3. Ejecuta en orden los updates que faltan
#   4. Registra cada ID aplicado en /etc/svqpanel/applied_updates
#   5. Loguea todo en /var/log/svqpanel-update.log
#
# CÓMO AÑADIR UN NUEVO UPDATE
# ─────────────────────────────────────────────────────────────────────────────
# 1. Crea updates/NNNN-descripcion.sh (NNNN = siguiente número libre, 4 dígitos)
# 2. El script debe ser idempotente (seguro de re-ejecutar si falla a mitad)
# 3. Usa exit 0 al final si todo fue bien; cualquier otro exit code = fallo
# 4. El sistema NO aplica el siguiente update si uno falla (se detiene)
# 5. Haz commit + push — los servidores lo descargan en la próxima ejecución
#
# USO MANUAL
# ─────────────────────────────────────────────────────────────────────────────
#   curl -fsSL https://raw.githubusercontent.com/coriaweb/SVQPanel/main/update.sh | bash
#   — o —
#   bash /opt/svqpanel/update.sh
#
# CRON AUTOMÁTICO (instalado por install.sh)
# ─────────────────────────────────────────────────────────────────────────────
#   0 3 * * * root bash /opt/svqpanel/update.sh >> /var/log/svqpanel-update.log 2>&1
###############################################################################

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PANEL_DIR="/opt/svqpanel"
VENV_DIR="$PANEL_DIR/venv"
UPDATES_DIR="$PANEL_DIR/updates"
APPLIED_FILE="/etc/svqpanel/applied_updates"
LOG_FILE="/var/log/svqpanel-update.log"
LOCK_FILE="/var/run/svqpanel-update.lock"

log() { echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

###############################################################################
# Guardia: solo root
###############################################################################
if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}Este script debe ejecutarse como root${NC}"
    exit 1
fi

###############################################################################
# Guardia: evitar ejecuciones simultáneas
###############################################################################
if [[ -f "$LOCK_FILE" ]]; then
    log "${YELLOW}⚠ Otra instancia ya está corriendo (lock: $LOCK_FILE). Saliendo.${NC}"
    exit 0
fi
trap 'rm -f "$LOCK_FILE"' EXIT
echo $$ > "$LOCK_FILE"

###############################################################################
# Verificar instalación existente
###############################################################################
if [[ ! -d "$PANEL_DIR" ]]; then
    log "${RED}✗ SVQPanel no encontrado en $PANEL_DIR. Instala primero con install.sh${NC}"
    exit 1
fi

log "${BLUE}=== SVQPanel Update — $(date '+%Y-%m-%d %H:%M:%S') ===${NC}"

###############################################################################
# 1. Descargar últimos cambios del repo
###############################################################################
log "${YELLOW}→ Descargando cambios del repositorio...${NC}"
cd "$PANEL_DIR"
git fetch origin main --quiet
BEFORE=$(git rev-parse HEAD)
git pull origin main --quiet
AFTER=$(git rev-parse HEAD)

if [[ "$BEFORE" == "$AFTER" ]]; then
    log "  Sin cambios en el repo."
else
    log "${GREEN}  ✓ Repo actualizado: ${BEFORE:0:7} → ${AFTER:0:7}${NC}"
    git log --oneline "${BEFORE}..${AFTER}" | while read -r line; do
        log "    • $line"
    done
fi

###############################################################################
# 2. Aplicar migraciones pendientes
###############################################################################
mkdir -p /etc/svqpanel
touch "$APPLIED_FILE"

if [[ ! -d "$UPDATES_DIR" ]]; then
    log "  Sin directorio updates/ — nada que migrar."
else
    PENDING=0
    APPLIED=0
    FAILED=0

    # Iterar en orden numérico
    while IFS= read -r UPDATE_FILE; do
        UPDATE_ID=$(basename "$UPDATE_FILE" .sh)

        # Saltar si ya está aplicado
        if grep -qF "$UPDATE_ID" "$APPLIED_FILE" 2>/dev/null; then
            continue
        fi

        PENDING=$((PENDING + 1))
        log "${YELLOW}→ Aplicando update: $UPDATE_ID${NC}"

        # Ejecutar en subshell para aislar errores
        if bash "$UPDATE_FILE" 2>&1; then
            echo "$UPDATE_ID" >> "$APPLIED_FILE"
            log "${GREEN}  ✓ $UPDATE_ID aplicado${NC}"
            APPLIED=$((APPLIED + 1))
        else
            log "${RED}  ✗ $UPDATE_ID FALLÓ — deteniendo. Revisa: $LOG_FILE${NC}"
            FAILED=$((FAILED + 1))
            # No seguir con el siguiente update si uno falla
            break
        fi
    done < <(find "$UPDATES_DIR" -maxdepth 1 -name '[0-9][0-9][0-9][0-9]-*.sh' | sort)

    if [[ $PENDING -eq 0 ]]; then
        log "  Sin updates pendientes."
    else
        log "  Updates pendientes: $PENDING | Aplicados: $APPLIED | Fallidos: $FAILED"
    fi
fi

###############################################################################
# 3. Actualizar dependencias Python (solo si requirements.txt cambió)
###############################################################################
REQS_CHANGED=$(git diff "${BEFORE}..${AFTER}" --name-only 2>/dev/null | grep -c "requirements.txt" || true)
if [[ "$REQS_CHANGED" -gt 0 ]]; then
    log "${YELLOW}→ requirements.txt cambió — actualizando dependencias Python...${NC}"
    # shellcheck source=/dev/null
    source "$VENV_DIR/bin/activate"
    pip install -q -r requirements.txt
    deactivate
    log "${GREEN}  ✓ Dependencias Python actualizadas${NC}"
fi

###############################################################################
# 4. Rebuild frontend (solo si frontend/ cambió)
###############################################################################
FRONTEND_CHANGED=$(git diff "${BEFORE}..${AFTER}" --name-only 2>/dev/null | grep -c "^frontend/" || true)
if [[ "$FRONTEND_CHANGED" -gt 0 ]]; then
    log "${YELLOW}→ Frontend cambió — reconstruyendo...${NC}"
    cd "$PANEL_DIR/frontend"
    npm install --silent
    npm run build --silent
    log "${GREEN}  ✓ Frontend reconstruido${NC}"
    cd "$PANEL_DIR"
fi

###############################################################################
# 5. Reiniciar panel si hubo cambios en Python o en migraciones
###############################################################################
BACKEND_CHANGED=$(git diff "${BEFORE}..${AFTER}" --name-only 2>/dev/null | grep -cE "^(api/|scripts/|config/)" || true)
if [[ "$BACKEND_CHANGED" -gt 0 || "$APPLIED" -gt 0 ]]; then
    log "${YELLOW}→ Reiniciando servicio svqpanel...${NC}"
    systemctl restart svqpanel
    sleep 2
    if systemctl is-active --quiet svqpanel; then
        log "${GREEN}  ✓ Servicio reiniciado correctamente${NC}"
    else
        log "${RED}  ✗ El servicio no arrancó — revisa: journalctl -u svqpanel -n 50${NC}"
    fi
fi

log "${GREEN}=== Update completado ===${NC}"
