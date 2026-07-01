#!/bin/bash
# 0098-redis-por-dominio.sh
#
# Prepara el servidor para el Redis dedicado por dominio (caché de objetos):
#   - instala la extensión phpredis (php{VER}-redis) en todas las versiones
#     PHP presentes, para que WordPress/Laravel/Magento puedan usarlo
#   - garantiza que redis-server (el binario) está instalado; si no hay stack
#     de correo, la instancia global se deja desactivada (solo se usan las
#     instancias por dominio, que gestiona scripts/redis_manager.py)
#   - crea /etc/svqpanel/redis (configs de las instancias)
#
# Las instancias en sí se crean bajo demanda desde el panel (toggle en la
# pestaña PHP del dominio): unidad systemd propia, corre como el usuario del
# dominio, socket unix en private/ (0700) y maxmemory acotado.
#
# Idempotente y no interactivo.

set -u

echo "→ 0098: soporte de Redis por dominio (phpredis + binario)…"

export DEBIAN_FRONTEND=noninteractive

# 1. Binario redis-server (solo el paquete; sin abrir nada)
if ! command -v redis-server >/dev/null 2>&1; then
    if apt-get install -y -qq redis-server >/dev/null 2>&1; then
        # Sin Rspamd la instancia global no se usa: apagarla (las instancias
        # por dominio tienen su propia unidad; solo necesitamos el binario).
        if [ ! -d /etc/rspamd ]; then
            systemctl disable --now redis-server >/dev/null 2>&1 || true
            echo "  ✓ redis-server instalado (instancia global desactivada)"
        else
            echo "  ✓ redis-server instalado"
        fi
    else
        echo "  ⚠ no se pudo instalar redis-server (se podrá reintentar al activar la feature)"
    fi
else
    echo "  · redis-server ya presente"
fi

# 2. Extensión phpredis para cada versión PHP instalada
for PHPDIR in /etc/php/*/fpm; do
    [ -d "$PHPDIR" ] || continue
    VER="$(basename "$(dirname "$PHPDIR")")"
    if [ -x "/usr/bin/php${VER}" ] && \
       "/usr/bin/php${VER}" -m 2>/dev/null | grep -qi '^redis$'; then
        echo "  · php${VER}-redis ya activo"
        continue
    fi
    if apt-get install -y -qq "php${VER}-redis" >/dev/null 2>&1; then
        echo "  ✓ php${VER}-redis instalado"
        systemctl reload "php${VER}-fpm" >/dev/null 2>&1 || \
            systemctl restart "php${VER}-fpm" >/dev/null 2>&1 || true
    else
        echo "  ⚠ php${VER}-redis no disponible (ignorado)"
    fi
done

# 3. Directorio de configs de las instancias por dominio
mkdir -p /etc/svqpanel/redis

echo "✓ 0098: servidor listo para Redis por dominio"
exit 0
