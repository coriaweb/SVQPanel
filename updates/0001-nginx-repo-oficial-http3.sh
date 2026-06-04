#!/bin/bash
# 0001-nginx-repo-oficial-http3.sh
#
# Migra nginx del paquete de Debian (1.22, sin HTTP/3) al repo oficial de
# nginx.org (stable, 1.30+, con HTTP/3/QUIC). Preserva toda la configuración
# existente en /etc/nginx/. Idempotente: si ya está en el repo oficial, no hace nada.

set -euo pipefail

echo "→ 0001: Comprobando versión de nginx..."

CURRENT_SOURCE=$(apt-cache policy nginx 2>/dev/null | grep "Installed:" | awk '{print $2}')

# Si ya viene del repo oficial (versión >= 1.26 o contiene "nginx.org"), nada que hacer
if nginx -v 2>&1 | grep -qE "nginx/1\.(2[6-9]|[3-9][0-9])"; then
    echo "  Ya está en repo oficial ($(nginx -v 2>&1)). Nada que hacer."
    exit 0
fi

echo "  Versión actual: $(nginx -v 2>&1) — migrando al repo oficial..."

# Detectar Debian version
OS_VERSION=$(grep -oP '(?<=^VERSION_ID=")[^"]+' /etc/os-release)
case "$OS_VERSION" in
    12) NGINX_CODENAME="bookworm" ;;
    13) NGINX_CODENAME="trixie" ;;
    *)  echo "  OS no soportado: $OS_VERSION"; exit 1 ;;
esac

# Añadir repo oficial nginx.org
curl -fsSL https://nginx.org/keys/nginx_signing.key \
    | gpg --yes --dearmor -o /usr/share/keyrings/nginx-archive-keyring.gpg

echo "deb [signed-by=/usr/share/keyrings/nginx-archive-keyring.gpg] \
http://nginx.org/packages/debian $NGINX_CODENAME nginx" \
    > /etc/apt/sources.list.d/nginx.list

# Dar prioridad al repo oficial sobre el de Debian
cat > /etc/apt/preferences.d/99nginx << 'EOF'
Package: nginx
Pin: origin nginx.org
Pin-Priority: 900
EOF

DEBIAN_FRONTEND=noninteractive apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    -o Dpkg::Options::="--force-confold" nginx

# Asegurar que sites-enabled esté en nginx.conf
if ! grep -q "sites-enabled" /etc/nginx/nginx.conf; then
    sed -i 's|include /etc/nginx/conf.d/\*.conf;|include /etc/nginx/conf.d/*.conf;\n    include /etc/nginx/sites-enabled/*;|' \
        /etc/nginx/nginx.conf
fi

# Worker como www-data
sed -i 's/^user  nginx;/user www-data;/' /etc/nginx/nginx.conf

mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled /etc/nginx/snippets

# Crear fastcgi-php.conf si no existe o está desactualizado
cat > /etc/nginx/snippets/fastcgi-php.conf << 'FCGIEOF'
fastcgi_split_path_info ^(.+?\.php)(/.*)$;
try_files $fastcgi_script_name =404;
set $path_info $fastcgi_path_info;
fastcgi_param PATH_INFO $path_info;
fastcgi_index index.php;
include fastcgi_params;
fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
FCGIEOF

nginx -t && systemctl reload nginx

echo "✓ 0001: nginx migrado a repo oficial — $(nginx -v 2>&1)"
exit 0
