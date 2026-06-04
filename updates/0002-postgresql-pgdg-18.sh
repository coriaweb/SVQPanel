#!/bin/bash
# 0002-postgresql-pgdg-18.sh
#
# Migra PostgreSQL del paquete de Debian (15.x) al repo oficial PGDG (18.x).
# Probado en servidor de test 2026-06-04: PG15 → PG18 con datos migrados OK.
#
# Qué hace:
#   1. Añade el repo PGDG (postgresql.org)
#   2. Instala postgresql (metapaquete → versión más reciente estable)
#   3. Elimina el cluster nuevo vacío que crea la instalación automática
#   4. Hace pg_upgradecluster del cluster existente al nuevo binario
#   5. Elimina el cluster antiguo y sus paquetes
#   6. Reinicia svqpanel para reconectar
#
# Idempotente: si el cluster activo ya viene del PGDG (versión >= 16), no hace nada.

set -euo pipefail

echo "→ 0002: Comprobando versión de PostgreSQL..."

# Detectar versión del cluster activo en puerto 5432
ACTIVE_VER=$(pg_lsclusters | awk '$3==5432 && $4=="online" {print $1}' | head -1)

if [[ -z "$ACTIVE_VER" ]]; then
    echo "  ✗ No se encontró cluster PostgreSQL activo en puerto 5432"
    exit 1
fi

# Si ya es versión >= 16 (PGDG), nada que hacer
if [[ "$ACTIVE_VER" -ge 16 ]]; then
    echo "  Ya está en PGDG (PostgreSQL $ACTIVE_VER). Nada que hacer."
    exit 0
fi

echo "  Versión activa: PostgreSQL $ACTIVE_VER → migrando a PGDG..."

# Detectar Debian version
OS_VERSION=$(grep -oP '(?<=^VERSION_ID=")[^"]+' /etc/os-release)
case "$OS_VERSION" in
    12) PG_CODENAME="bookworm-pgdg" ;;
    13) PG_CODENAME="trixie-pgdg" ;;
    *)  echo "  ✗ OS no soportado: $OS_VERSION"; exit 1 ;;
esac

# Backup de seguridad antes de tocar nada
echo "  → Haciendo backup previo..."
BACKUP_FILE="/root/pgbackup_pre_pgdg_$(date +%Y%m%d_%H%M%S).sql"
sudo -u postgres pg_dumpall > "$BACKUP_FILE"
echo "  ✓ Backup en $BACKUP_FILE ($(du -sh "$BACKUP_FILE" | cut -f1))"

# Paso 1: Añadir repo PGDG
echo "  → Añadiendo repo PGDG..."
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    | gpg --yes --dearmor -o /usr/share/keyrings/postgresql-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/postgresql-archive-keyring.gpg] \
https://apt.postgresql.org/pub/repos/apt ${PG_CODENAME} main" \
    > /etc/apt/sources.list.d/pgdg.list
DEBIAN_FRONTEND=noninteractive apt-get update -qq
echo "  ✓ Repo PGDG añadido"

# Paso 2: Instalar postgresql (metapaquete → versión más reciente)
echo "  → Instalando PostgreSQL PGDG..."
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    -o Dpkg::Options::="--force-confold" postgresql
NEW_VER=$(pg_lsclusters | awk '$4=="online" && $1!="'"$ACTIVE_VER"'" {print $1}' | sort -rn | head -1)
echo "  ✓ PostgreSQL $NEW_VER instalado"

# Paso 3: Eliminar el cluster vacío recién creado por la instalación
# (pg_upgradecluster necesita el puerto libre)
if pg_lsclusters | grep -q "^${NEW_VER}.*main"; then
    pg_dropcluster --stop "$NEW_VER" main 2>/dev/null || true
    echo "  ✓ Cluster $NEW_VER vacío eliminado"
fi

# Paso 4: Migrar datos → nuevo cluster
echo "  → Migrando datos $ACTIVE_VER → $NEW_VER (esto puede tardar unos minutos)..."
pg_upgradecluster "$ACTIVE_VER" main
echo "  ✓ Datos migrados a PostgreSQL $NEW_VER"

# Verificar que el nuevo cluster está online en puerto 5432
if ! pg_lsclusters | awk '$3==5432 && $4=="online"' | grep -q "$NEW_VER"; then
    echo "  ✗ El cluster $NEW_VER no está online en puerto 5432 — abortando limpieza"
    echo "    Revisa con: pg_lsclusters"
    exit 1
fi

# Verificar que panel_db existe y es accesible
if ! sudo -u postgres psql -lqt | cut -d'|' -f1 | grep -qw panel_db; then
    echo "  ✗ panel_db no encontrada en el nuevo cluster — abortando limpieza"
    exit 1
fi
echo "  ✓ panel_db verificada en PostgreSQL $NEW_VER"

# Paso 5: Eliminar cluster antiguo y paquetes
echo "  → Eliminando cluster y paquetes de PostgreSQL $ACTIVE_VER..."
pg_dropcluster "$ACTIVE_VER" main
DEBIAN_FRONTEND=noninteractive apt-get remove -y -qq \
    "postgresql-${ACTIVE_VER}" "postgresql-client-${ACTIVE_VER}" 2>/dev/null || true
DEBIAN_FRONTEND=noninteractive apt-get autoremove -y -qq 2>/dev/null || true
echo "  ✓ PostgreSQL $ACTIVE_VER eliminado"

# Paso 6: Reiniciar panel
echo "  → Reiniciando svqpanel..."
systemctl restart svqpanel
sleep 3
if systemctl is-active --quiet svqpanel; then
    echo "  ✓ svqpanel reiniciado correctamente"
else
    echo "  ✗ svqpanel no arrancó — revisa: journalctl -u svqpanel -n 50"
    exit 1
fi

echo "✓ 0002: PostgreSQL migrado a PGDG $NEW_VER correctamente"
exit 0
