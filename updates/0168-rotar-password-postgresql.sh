#!/bin/bash
# 0168-rotar-password-postgresql.sh
#
# Rota la contraseña del usuario PostgreSQL del panel (panel_user) si sigue
# siendo la fija de fábrica 'panel_password_123'.
#
# Por qué: install.sh la creaba igual en TODAS las instalaciones y además está
# publicada en el repositorio. Cualquier PHP de un cliente podía conectar por
# 127.0.0.1 a panel_db (open_basedir no limita sockets) y leer hashes de admin,
# tokens y secretos. install.sh ya genera una aleatoria (servidores nuevos).
#
# Cómo: genera una nueva, la aplica con ALTER ROLE, comprueba que conecta,
# reescribe DATABASE_URL en /opt/svqpanel/.env (copia en .env.bak-0168) y
# reinicia svqpanel. El panel abre una conexión nueva por petición (NullPool)
# con la URL que cargó al arrancar, así que el reinicio va pegado al ALTER para
# que el corte dure segundos. Si algo falla, deja la contraseña y el .env como
# estaban. Un fallo NO detiene la cadena (exit 0 con aviso).
#
# OJO: un backup del panel anterior a esta rotación lleva un .env con la
# contraseña vieja; al restaurarlo hay que conservar la DATABASE_URL actual.
#
# Idempotente y no interactivo.

set -uo pipefail

PANEL_DIR="/opt/svqpanel"
ENV_FILE="$PANEL_DIR/.env"
OLD_PASS="panel_password_123"

echo "→ 0168: contraseña de PostgreSQL del panel…"

if [[ ! -f "$ENV_FILE" ]] || ! grep -q "^DATABASE_URL=postgresql://panel_user:${OLD_PASS}@" "$ENV_FILE"; then
    echo "  Ya no usa la contraseña de fábrica — nada que hacer."
    exit 0
fi

NEW_PASS=$(python3 -c "import secrets; print(secrets.token_hex(24))")

_set_role_pass() {
    # Por stdin para que la contraseña no aparezca en la lista de procesos.
    printf "ALTER ROLE panel_user WITH PASSWORD '%s';\n" "$1" \
        | sudo -u postgres psql -q -v ON_ERROR_STOP=1 >/dev/null
}

_can_connect() {
    PGPASSWORD="$1" PGCONNECT_TIMEOUT=10 psql -h localhost -U panel_user -d panel_db \
        -tAc "SELECT 1" 2>/dev/null | grep -qx 1
}

if ! _set_role_pass "$NEW_PASS"; then
    echo "  ⚠ ALTER ROLE falló — se mantiene la contraseña actual."
    exit 0
fi

if ! _can_connect "$NEW_PASS"; then
    echo "  ⚠ No conecta con la contraseña nueva — se revierte."
    _set_role_pass "$OLD_PASS" || true
    exit 0
fi

cp -p "$ENV_FILE" "$ENV_FILE.bak-0168"
chmod 600 "$ENV_FILE.bak-0168"
sed -i "s|^DATABASE_URL=postgresql://panel_user:${OLD_PASS}@|DATABASE_URL=postgresql://panel_user:${NEW_PASS}@|" "$ENV_FILE"

systemctl restart svqpanel
sleep 3
if systemctl is-active --quiet svqpanel; then
    echo "✓ 0168: contraseña de panel_user rotada y svqpanel reiniciado"
    exit 0
fi

echo "  ⚠ svqpanel no arrancó con la contraseña nueva — se revierte."
cp -p "$ENV_FILE.bak-0168" "$ENV_FILE"
_set_role_pass "$OLD_PASS" || true
systemctl restart svqpanel || true
exit 0
