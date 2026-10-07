#!/bin/bash
# 0161-mariadb-repo-obsoleto.sh
#
# Quita el repositorio de mariadb.org (dlm.mariadb.com) y su pin de prioridad
# 1000 cuando MariaDB ya viene de los paquetes de Debian.
#
# Por qué: install.sh instalaba MariaDB 11.4 con mariadb_repo_setup. Tras el
# paso a Debian 13 el servidor corre el 11.8 de Debian, pero el repo seguía ahí:
#   - En servidores migrados desde Debian 12 quedaba apuntando a bookworm. apt
#     ofrecía "actualizar" mysql-common a su 11.4, y hacerlo desde el panel
#     arrastraba bajar de versión el cliente y DESINSTALAR mariadb-server
#     (visto en producción; apt solo se paró por la bajada de versión).
#   - En instalaciones nuevas (trixie) solo traía MaxScale, pero el pin 1000
#     haría preferir cualquier 11.4 que publiquen para trixie al 11.8 instalado.
#
# Seguro: solo actúa si mariadb-server, su core, el cliente y libmariadb3
# vienen de Debian (versión sin "maria~"). Si el servidor usa de verdad los
# paquetes de mariadb.org, no toca nada. Copia los ficheros a /var/backups.
# install.sh ya no añade el repo (servidores nuevos nacen sin él).
#
# Idempotente y no interactivo.

set -euo pipefail

echo "→ 0161: repositorio de mariadb.org obsoleto…"

shopt -s nullglob
REPO_FILES=()
for f in /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
    grep -q 'dlm\.mariadb\.com' "$f" 2>/dev/null && REPO_FILES+=("$f")
done
PIN_FILES=()
for f in /etc/apt/preferences.d/*; do
    grep -q 'dlm\.mariadb\.com' "$f" 2>/dev/null && PIN_FILES+=("$f")
done

if [[ ${#REPO_FILES[@]} -eq 0 && ${#PIN_FILES[@]} -eq 0 ]]; then
    echo "  Sin repo de mariadb.org — nada que hacer."
    exit 0
fi

# ¿Algún paquete esencial viene de mariadb.org? Entonces el repo se usa de verdad.
for p in mariadb-server mariadb-server-core mariadb-client libmariadb3; do
    v=$(dpkg-query -W -f='${Status} ${Version}' "$p" 2>/dev/null || true)
    case "$v" in
        "install ok installed "*maria~*)
            echo "  ⚠ $p viene de mariadb.org (${v##* }) — se respeta el repo, no se toca nada."
            exit 0 ;;
    esac
done

BK="/var/backups/svqpanel/apt-mariadb-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BK"
for f in "${REPO_FILES[@]}" "${PIN_FILES[@]}"; do
    mv "$f" "$BK/"
    echo "  ✓ retirado $f (copia en $BK)"
done

apt-get update -qq >/dev/null 2>&1 || echo "  ⚠ apt-get update con avisos (no crítico)."

echo "✓ 0161: repo de mariadb.org retirado; MariaDB sigue con los paquetes de Debian"
exit 0
