#!/bin/bash
###############################################################################
# SVQPanel — Dist-upgrade Debian 12 (bookworm) → Debian 13 (trixie)
# ─────────────────────────────────────────────────────────────────────────────
#
# ⚠️  ESTO ACTUALIZA EL SISTEMA OPERATIVO COMPLETO. ES UNA OPERACIÓN DELICADA Y
#     POTENCIALMENTE IRREVERSIBLE. NO se ejecuta por cron ni desde el panel:
#     SOLO a mano, por SSH, con consola/rescate del proveedor disponible.
#
# REQUISITO INNEGOCIABLE: haz un SNAPSHOT del VPS desde el panel de tu proveedor
# ANTES de ejecutarlo. Si el dist-upgrade falla a mitad, el snapshot es el único
# "deshacer" real. Este script lo exige por confirmación explícita.
#
# QUÉ HACE (por fases, reanudable):
#   0. Pre-flight: comprueba Debian 12, espacio en disco, panel sano.
#   1. Backup completo: dump de PostgreSQL + MariaDB + tar de /etc/svqpanel y configs.
#   2. Actualiza Debian 12 al día (apt full-upgrade dentro de bookworm).
#   3. Reapunta TODOS los repos propios bookworm → trixie
#      (Debian base, PGDG, Sury PHP, nginx.org, MariaDB, Rspamd).
#   4. apt update + full-upgrade a trixie (--force-confold: no pisa configs).
#   5. Recrea el venv de Python de /opt/svqpanel contra el Python de trixie.
#   6. Reinstala pools PHP-FPM y reinicia servicios vía el código del panel.
#   7. Post-flight: valida que cada servicio arranca y que el panel responde.
#
# REANUDABLE: cada fase deja una marca en /var/lib/svqpanel/distupgrade.state.
# Si el script se corta (o reinicias el server a mitad), vuelve a lanzarlo y
# retoma desde la última fase completada. Para forzar una fase: --from N.
#
# USO:
#   bash /opt/svqpanel/scripts/dist_upgrade_debian13.sh
#   bash /opt/svqpanel/scripts/dist_upgrade_debian13.sh --from 4   # reanudar
#   bash /opt/svqpanel/scripts/dist_upgrade_debian13.sh --yes      # menos pausas
###############################################################################

set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

PANEL_DIR="/opt/svqpanel"
VENV_DIR="$PANEL_DIR/venv"
STATE_DIR="/var/lib/svqpanel"
STATE_FILE="$STATE_DIR/distupgrade.state"
LOG_FILE="/var/log/svqpanel-distupgrade.log"
BACKUP_DIR="/root/svqpanel-distupgrade-backup"

ASSUME_YES=0
FORCE_FROM=""
UNTIL_PHASE=""        # si se fija, no ejecuta fases con N > UNTIL_PHASE (control fase a fase)
_EXPECT=""
for arg in "$@"; do
    case "$arg" in
        --yes|-y)     ASSUME_YES=1 ;;
        --from)       _EXPECT="from" ;;
        --until)      _EXPECT="until" ;;
        [0-9]*)       case "$_EXPECT" in
                          from)  FORCE_FROM="$arg" ;;
                          until) UNTIL_PHASE="$arg" ;;
                      esac; _EXPECT="" ;;
        --from=*)     FORCE_FROM="${arg#--from=}" ;;
        --until=*)    UNTIL_PHASE="${arg#--until=}" ;;
    esac
done

# Loguear todo a fichero además de a pantalla
mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1

log()  { echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
ok()   { log "${GREEN}  ✓ $*${NC}"; }
warn() { log "${YELLOW}  ⚠ $*${NC}"; }
err()  { log "${RED}  ✗ $*${NC}"; }
die()  { err "$*"; exit 1; }

confirm() {
    # confirm "pregunta" — devuelve 0 si el usuario acepta
    [[ "$ASSUME_YES" -eq 1 ]] && return 0
    local ans
    read -r -p "$(echo -e "${YELLOW}$1 [escribe 'si' para continuar]: ${NC}")" ans
    [[ "$ans" == "si" || "$ans" == "SI" || "$ans" == "yes" ]]
}

phase_done()    { echo "$1" >> "$STATE_FILE"; }
phase_is_done() { grep -qxF "$1" "$STATE_FILE" 2>/dev/null; }

# ¿Debo correr la fase N? (no, si ya está hecha y no se fuerza desde antes/igual)
should_run() {
    local n="$1"
    # --until N: no pasar de la fase N (control fase a fase)
    if [[ -n "$UNTIL_PHASE" && "$n" -gt "$UNTIL_PHASE" ]]; then
        return 1
    fi
    if [[ -n "$FORCE_FROM" ]]; then
        [[ "$n" -ge "$FORCE_FROM" ]] && return 0 || return 1
    fi
    phase_is_done "phase-$n" && return 1 || return 0
}

###############################################################################
# Guardias
###############################################################################
[[ $EUID -ne 0 ]] && die "Este script debe ejecutarse como root."
[[ ! -d "$PANEL_DIR" ]] && die "SVQPanel no encontrado en $PANEL_DIR."
mkdir -p "$STATE_DIR"
touch "$STATE_FILE"

log "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
log "${BLUE}║  SVQPanel — Upgrade Debian 12 → 13   ($(date '+%Y-%m-%d %H:%M')) ║${NC}"
log "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
log "  Log completo: $LOG_FILE"
[[ -n "$FORCE_FROM" ]] && warn "Reanudando forzado desde la fase $FORCE_FROM"

###############################################################################
# FASE 0 — Pre-flight
###############################################################################
if should_run 0; then
    log "${BLUE}── FASE 0: Comprobaciones previas ──${NC}"

    OS_NAME=$(grep -oP '(?<=^ID=)\w+' /etc/os-release || echo "")
    OS_VERSION=$(grep -oP '(?<=^VERSION_ID=")[^"]+' /etc/os-release || echo "")
    [[ "$OS_NAME" != "debian" ]] && die "Solo Debian. Detectado: $OS_NAME"
    if [[ "$OS_VERSION" == "13" ]]; then
        ok "Ya estás en Debian 13. Nada que hacer."
        exit 0
    fi
    [[ "$OS_VERSION" != "12" ]] && die "Se esperaba Debian 12. Tienes: $OS_VERSION"
    ok "Debian 12 (bookworm) detectado."

    # Espacio en disco (al menos 5 GB libres en / para el upgrade)
    FREE_GB=$(df --output=avail -BG / | tail -1 | tr -dc '0-9')
    if [[ "${FREE_GB:-0}" -lt 5 ]]; then
        die "Solo ${FREE_GB}GB libres en /. Necesitas ≥5GB para el dist-upgrade."
    fi
    ok "Espacio libre en /: ${FREE_GB}GB"

    # Panel sano antes de empezar
    if systemctl is-active --quiet svqpanel; then
        ok "Servicio svqpanel activo."
    else
        warn "svqpanel no está activo. Revisa antes de continuar."
    fi

    log ""
    log "${YELLOW}╭──────────────────────────────────────────────────────────────╮${NC}"
    log "${YELLOW}│ ANTES DE CONTINUAR:                                          │${NC}"
    log "${YELLOW}│  1. Haz un SNAPSHOT del VPS en el panel de tu proveedor.     │${NC}"
    log "${YELLOW}│  2. Asegúrate de tener acceso a la CONSOLA/RESCATE del VPS.  │${NC}"
    log "${YELLOW}│  3. Avisa a los clientes: habrá unos minutos de corte.       │${NC}"
    log "${YELLOW}│  Si algo falla a mitad, el snapshot es tu única vuelta atrás.│${NC}"
    log "${YELLOW}╰──────────────────────────────────────────────────────────────╯${NC}"
    confirm "¿Has hecho el snapshot y tienes consola de rescate?" \
        || die "Operación cancelada. Haz el snapshot primero."

    phase_done "phase-0"
    ok "Fase 0 completada."
fi

###############################################################################
# FASE 1 — Backup completo
###############################################################################
if should_run 1; then
    log "${BLUE}── FASE 1: Backup completo ──${NC}"
    STAMP=$(date +%Y%m%d_%H%M%S)
    DEST="$BACKUP_DIR/$STAMP"
    mkdir -p "$DEST"

    # PostgreSQL (panel)
    if command -v pg_dumpall >/dev/null 2>&1; then
        log "  → Volcando PostgreSQL..."
        sudo -u postgres pg_dumpall > "$DEST/postgresql_all.sql" \
            && ok "PostgreSQL → $DEST/postgresql_all.sql ($(du -sh "$DEST/postgresql_all.sql" | cut -f1))" \
            || die "Falló el dump de PostgreSQL."
    fi

    # MariaDB (clientes) — root usa unix_socket
    if command -v mariadb-dump >/dev/null 2>&1 || command -v mysqldump >/dev/null 2>&1; then
        log "  → Volcando MariaDB..."
        DUMP_BIN=$(command -v mariadb-dump || command -v mysqldump)
        "$DUMP_BIN" --all-databases --single-transaction --events --routines > "$DEST/mariadb_all.sql" 2>/dev/null \
            && ok "MariaDB → $DEST/mariadb_all.sql ($(du -sh "$DEST/mariadb_all.sql" | cut -f1))" \
            || warn "No se pudo volcar MariaDB (¿no instalada?). Continúo."
    fi

    # Configs críticas del sistema y del panel
    log "  → Empaquetando configuraciones..."
    # Empaquetar solo las rutas que existan (evita avisos de tar por rutas ausentes).
    CFG_PATHS=()
    for p in /etc/svqpanel /etc/nginx /etc/apache2 /etc/php /etc/postfix \
             /etc/dovecot /etc/bind /etc/nftables.conf /etc/fail2ban \
             /etc/apt/sources.list /etc/apt/sources.list.d /etc/apt/mirrors; do
        [[ -e "$p" ]] && CFG_PATHS+=("$p")
    done
    tar czf "$DEST/configs.tar.gz" "${CFG_PATHS[@]}" 2>/dev/null || true
    ok "Configs → $DEST/configs.tar.gz"

    # Lista de paquetes instalados (por si hay que reconstruir algo)
    dpkg --get-selections > "$DEST/dpkg-selections.txt"
    pg_lsclusters > "$DEST/pg_lsclusters.txt" 2>/dev/null || true
    ok "Inventario de paquetes guardado."

    echo "$DEST" > "$STATE_DIR/distupgrade.lastbackup"
    log "${GREEN}  Backup completo en: $DEST${NC}"
    phase_done "phase-1"
    ok "Fase 1 completada."
fi

###############################################################################
# FASE 2 — Poner Debian 12 al día antes de saltar
###############################################################################
if should_run 2; then
    log "${BLUE}── FASE 2: Actualizando Debian 12 al día ──${NC}"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq || die "apt update falló."
    apt-get -y -o Dpkg::Options::="--force-confold" full-upgrade \
        || die "full-upgrade dentro de bookworm falló."
    apt-get -y autoremove -qq || true
    ok "Debian 12 al día."
    phase_done "phase-2"
    ok "Fase 2 completada."
fi

###############################################################################
# FASE 3 — Reapuntar repos bookworm → trixie
###############################################################################
if should_run 3; then
    log "${BLUE}── FASE 3: Reapuntando repos a trixie ──${NC}"

    # 3a. Debian base — soporta sources.list clásico Y formato deb822 (.sources).
    #     IMPORTANTE: 'bookworm-backports' NO debe convertirse en 'trixie-backports'
    #     (no existe al liberarse trixie y rompería apt update). Se ELIMINA antes.
    log "  → Debian base (bookworm → trixie)..."

    # Backup de los ficheros de repos por si hay que revisarlos
    BK="$BACKUP_DIR/apt-sources-$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BK"
    cp -a /etc/apt/sources.list "$BK/" 2>/dev/null || true
    cp -a /etc/apt/sources.list.d "$BK/" 2>/dev/null || true

    # sources.list clásico (formato de una línea)
    if [[ -f /etc/apt/sources.list ]]; then
        # Quitar líneas de backports (deb/deb-src ... bookworm-backports ...)
        sed -i -E '/\bbookworm-backports\b/d' /etc/apt/sources.list
        sed -i -E 's/\bbookworm\b/trixie/g' /etc/apt/sources.list
    fi

    # deb822 (.sources): en 'Suites:' puede haber varios codenames en una línea
    # (p.ej. "bookworm bookworm-updates bookworm-backports"). Quitamos el token
    # *-backports de esa línea y luego reapuntamos bookworm → trixie.
    for f in /etc/apt/sources.list.d/*.sources; do
        [[ -e "$f" ]] || continue
        # Eliminar SOLO el token bookworm-backports de las líneas Suites:
        sed -i -E '/^Suites:/ s/\bbookworm-backports\b//g; /^Suites:/ s/  +/ /g; /^Suites:/ s/ +$//' "$f"
        sed -i -E 's/\bbookworm\b/trixie/g' "$f"
    done
    ok "Debian base reapuntado (backports retirado)."

    # 3b. PGDG (PostgreSQL)
    if [[ -f /etc/apt/sources.list.d/pgdg.list ]]; then
        sed -i 's/bookworm-pgdg/trixie-pgdg/g' /etc/apt/sources.list.d/pgdg.list
        ok "PGDG → trixie-pgdg"
    fi

    # 3c. Sury PHP
    if [[ -f /etc/apt/sources.list.d/sury-php.list ]]; then
        sed -i 's#/php/ bookworm #/php/ trixie #g; s/\bbookworm\b/trixie/g' \
            /etc/apt/sources.list.d/sury-php.list
        ok "Sury PHP → trixie"
    fi

    # 3d. nginx.org
    if [[ -f /etc/apt/sources.list.d/nginx.list ]]; then
        sed -i 's/\bbookworm\b/trixie/g' /etc/apt/sources.list.d/nginx.list
        ok "nginx.org → trixie"
    fi

    # 3e. MariaDB (r.mariadb.com) — el setup script escribe codename o deb822
    for f in /etc/apt/sources.list.d/mariadb*.list /etc/apt/sources.list.d/mariadb*.sources; do
        [[ -e "$f" ]] || continue
        sed -i 's/\bbookworm\b/trixie/g' "$f"
        ok "MariaDB ($f) → trixie"
    done

    # 3f. Rspamd — stable puede no tener trixie todavía: dejar en bookworm
    #     (mismo criterio que install.sh).
    if [[ -f /etc/apt/sources.list.d/rspamd.list ]]; then
        if grep -q 'trixie' /etc/apt/sources.list.d/rspamd.list; then
            warn "Rspamd apunta a trixie; se revertirá a bookworm si no tiene Release."
        else
            ok "Rspamd se mantiene en bookworm (compatible)."
        fi
    fi

    # Validación con auto-reversión genérica.
    # Algunos repos de TERCEROS (Rspamd, MariaDB...) aún no publican paquetes para
    # trixie. Sus paquetes de bookworm funcionan en trixie igualmente. Por eso, si
    # 'apt update' marca un repo de sources.list.d/*.list (NO Debian base) sin
    # Release file para trixie, lo revertimos a bookworm y reintentamos. Iteramos
    # hasta que apt update quede limpio o no haya más repos de terceros que revertir.
    APT_LOG=/tmp/svq-aptupdate.log
    APT_ERR_RE='^E:|^Err:|does not have a Release file|failed to fetch|no se pudo|could not'

    for _try in 1 2 3 4 5; do
        apt-get update >"$APT_LOG" 2>&1 || true
        if ! grep -qiE "$APT_ERR_RE" "$APT_LOG"; then
            ok "Repos de trixie validados (apt update OK)."
            break
        fi

        # Extraer las URLs SOLO de las líneas de ERROR (no de las 'Hit:' exitosas)
        # y mapearlas a su .list para revertir SOLO ese fichero (de sources.list.d,
        # nunca Debian base deb822). Apt emite el fallo en líneas 'Err:' / 'Ign:' /
        # 'does not have a Release file', que es de donde sacamos la URL culpable.
        REVERTED=0
        while IFS= read -r badurl; do
            [[ -z "$badurl" ]] && continue
            base="${badurl%%/dists/*}"          # recortar a la base del repo
            base="${base%% *}"                  # quedarnos solo con la URL
            for lf in /etc/apt/sources.list.d/*.list; do
                [[ -e "$lf" ]] || continue
                if grep -qF "$base" "$lf" && grep -q '\btrixie\b' "$lf"; then
                    warn "$(basename "$lf"): trixie no disponible → revierto a bookworm."
                    sed -i 's/\btrixie\b/bookworm/g' "$lf"
                    REVERTED=1
                fi
            done
        done < <(grep -iE "$APT_ERR_RE" "$APT_LOG" | grep -oE 'https?://[^ ]+' | sort -u)

        if [[ "$REVERTED" -eq 0 ]]; then
            err "apt update falla y no hay repo de terceros que revertir. Revisa $APT_LOG"
            grep -iE "$APT_ERR_RE" "$APT_LOG" | head -10
            die "No continúo: hay un repo roto que no sé arreglar."
        fi
    done

    # Comprobación final defensiva
    apt-get update >"$APT_LOG" 2>&1 || true
    if grep -qiE "$APT_ERR_RE" "$APT_LOG"; then
        err "apt update sigue con errores tras las reversiones. Revisa $APT_LOG"
        grep -iE "$APT_ERR_RE" "$APT_LOG" | head -10
        die "No continúo."
    fi
    phase_done "phase-3"
    ok "Fase 3 completada."
fi

###############################################################################
# FASE 4 — El salto: full-upgrade a trixie
###############################################################################
if should_run 4; then
    log "${BLUE}── FASE 4: Dist-upgrade a Debian 13 (trixie) ──${NC}"
    warn "Esta fase puede tardar bastante y reiniciar servicios."
    confirm "¿Ejecutar el full-upgrade a trixie AHORA?" \
        || die "Cancelado en la fase 4. Reanuda con: --from 4"

    export DEBIAN_FRONTEND=noninteractive
    # --force-confold: ante un .conf modificado por el panel, conservar el nuestro.
    # 'minimal' primero reduce el riesgo de conflictos; luego el full.
    apt-get -y -o Dpkg::Options::="--force-confold" -o Dpkg::Options::="--force-confdef" \
        full-upgrade || die "full-upgrade a trixie falló. Revisa $LOG_FILE y usa la consola de rescate."
    apt-get -y autoremove -qq || true

    NEW_OS=$(grep -oP '(?<=^VERSION_ID=")[^"]+' /etc/os-release || echo "?")
    [[ "$NEW_OS" == "13" ]] && ok "Sistema ahora en Debian $NEW_OS." \
        || warn "VERSION_ID=$NEW_OS (esperaba 13). Revisa antes de seguir."
    phase_done "phase-4"
    ok "Fase 4 completada."
fi

###############################################################################
# FASE 5 — Recrear el venv de Python contra el Python de trixie
###############################################################################
if should_run 5; then
    log "${BLUE}── FASE 5: Recreando el venv de Python ──${NC}"
    # trixie trae un Python más nuevo; el venv apunta a un intérprete que ya no existe.
    SYS_PY=$(command -v python3)
    log "  → Python del sistema: $($SYS_PY --version 2>&1)"

    if [[ -d "$VENV_DIR" ]]; then
        mv "$VENV_DIR" "${VENV_DIR}.old-$(date +%s)" || true
        ok "venv anterior apartado."
    fi
    "$SYS_PY" -m venv "$VENV_DIR" || die "No se pudo crear el venv."
    # shellcheck source=/dev/null
    source "$VENV_DIR/bin/activate"
    pip install -q --upgrade pip
    pip install -q -r "$PANEL_DIR/requirements.txt" \
        || die "pip install -r requirements.txt falló en el nuevo venv."
    deactivate
    ok "venv recreado e instaladas las dependencias."
    phase_done "phase-5"
    ok "Fase 5 completada."
fi

###############################################################################
# FASE 6 — Reinstalar pools PHP y reiniciar servicios vía el código del panel
###############################################################################
if should_run 6; then
    log "${BLUE}── FASE 6: Reinstalando pools PHP y reiniciando servicios ──${NC}"
    cd "$PANEL_DIR"

    # Reescribe los pools FPM con la política actual (igual que hace install.sh).
    if [[ -x "$VENV_DIR/bin/python" ]]; then
        "$VENV_DIR/bin/python" -m api.cli migrate_php_pools --force \
            && ok "Pools PHP-FPM regenerados." \
            || warn "migrate_php_pools devolvió error. Revisa manualmente."
    fi

    # Reiniciar la pila de servicios en orden.
    for svc in postgresql mariadb php8.2-fpm php8.3-fpm php8.4-fpm \
               nginx apache2 postfix dovecot bind9 named rspamd unbound \
               fail2ban nftables svqpanel; do
        if systemctl list-unit-files | grep -q "^${svc}\b" 2>/dev/null \
           || systemctl cat "$svc" >/dev/null 2>&1; then
            systemctl restart "$svc" 2>/dev/null \
                && ok "$svc reiniciado" \
                || warn "$svc no se pudo reiniciar (puede no aplicar)."
        fi
    done
    phase_done "phase-6"
    ok "Fase 6 completada."
fi

###############################################################################
# FASE 7 — Post-flight: validar
###############################################################################
if should_run 7; then
    log "${BLUE}── FASE 7: Validación final ──${NC}"
    PROBLEMS=0

    NEW_OS=$(grep -oP '(?<=^VERSION_ID=")[^"]+' /etc/os-release || echo "?")
    [[ "$NEW_OS" == "13" ]] && ok "SO: Debian 13" || { err "SO no es 13 (=$NEW_OS)"; PROBLEMS=$((PROBLEMS+1)); }

    # PostgreSQL accesible y panel_db presente
    if sudo -u postgres psql -lqt 2>/dev/null | cut -d'|' -f1 | grep -qw panel_db; then
        ok "PostgreSQL: panel_db accesible"
    else
        err "PostgreSQL: panel_db NO accesible"; PROBLEMS=$((PROBLEMS+1))
    fi

    # Servicios clave activos
    for svc in svqpanel nginx postgresql; do
        if systemctl is-active --quiet "$svc"; then
            ok "$svc activo"
        else
            err "$svc NO activo"; PROBLEMS=$((PROBLEMS+1))
        fi
    done

    # El panel responde por HTTP local
    if curl -fsS -o /dev/null --max-time 10 http://127.0.0.1:8001/ 2>/dev/null \
       || curl -fsS -o /dev/null --max-time 10 http://127.0.0.1:8001/docs 2>/dev/null; then
        ok "API del panel responde en :8001"
    else
        warn "La API no respondió en :8001 (revisa: journalctl -u svqpanel -n 50)"
        PROBLEMS=$((PROBLEMS+1))
    fi

    # PHP-FPM: al menos un pool corriendo
    if pgrep -f 'php-fpm' >/dev/null 2>&1; then
        ok "PHP-FPM en ejecución"
    else
        warn "No veo procesos php-fpm"; PROBLEMS=$((PROBLEMS+1))
    fi

    phase_done "phase-7"
    log ""
    if [[ "$PROBLEMS" -eq 0 ]]; then
        log "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
        log "${GREEN}║  ✓ UPGRADE A DEBIAN 13 COMPLETADO SIN INCIDENCIAS            ║${NC}"
        log "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
        log "  Recomendado: reinicia el servidor para cargar el kernel nuevo:"
        log "      ${YELLOW}reboot${NC}"
        log "  Backup de seguridad en: $(cat "$STATE_DIR/distupgrade.lastbackup" 2>/dev/null)"
    else
        log "${YELLOW}╔══════════════════════════════════════════════════════════════╗${NC}"
        log "${YELLOW}║  ⚠ UPGRADE COMPLETADO CON $PROBLEMS AVISO(S) — revisa arriba    ║${NC}"
        log "${YELLOW}╚══════════════════════════════════════════════════════════════╝${NC}"
        log "  Backup: $(cat "$STATE_DIR/distupgrade.lastbackup" 2>/dev/null)"
        log "  Si algo está roto y no se arregla, restaura el snapshot del proveedor."
        exit 1
    fi
fi

exit 0
