# Configuración Apache + Nginx en SVQPanel

## Instalación limpia con Apache + Nginx

### 1. Ejecutar install.sh
```bash
curl https://raw.githubusercontent.com/coriaweb/SVQPanel/main/install.sh | bash
```

En la primera pregunta, elegir:
```
¿Qué webserver necesitas?
1) Nginx solo
2) Apache + Nginx (Apache para legacy, Nginx para velocidad)

Elige (1 o 2): 2
```

Esto guardará `apache+nginx` en `/etc/svqpanel/webserver.conf`.

### 2. Instalar Apache (si no lo hizo el script)
Si la instalación no incluye Apache automáticamente, añadir manualmente:
```bash
apt-get install apache2 libapache2-mod-proxy-fcgi
a2enmod proxy proxy_fcgi rewrite headers ssl
systemctl enable apache2
systemctl start apache2
```

### 3. Crear dominios
Ahora al crear dominios via API o panel, los vhosts se crearán en **Apache** automáticamente:
```bash
POST /api/domains
{
  "domain_name": "ejemplo.com",
  "php_version": "8.2"
}
```

Esto creará:
- `/etc/apache2/sites-available/ejemplo.com.conf` (vhost Apache)
- `/home/usuario/web/ejemplo.com/public_html/`
- Pool PHP-FPM dedicado

### 4. Verificar configuración
```bash
# Ver webserver detectado:
cat /etc/svqpanel/webserver.conf
# Output: apache+nginx

# Ver sitios Apache habilitados:
ls /etc/apache2/sites-enabled/

# Verificar sintaxis Apache:
apache2ctl configtest
# Output: Syntax OK
```

## Migración: cambiar dominio de webserver

Actualmente NO hay migración automática. Si necesitas cambiar un dominio de Apache a Nginx (o viceversa):

1. **Eliminar el dominio** via panel (borra vhost y configs)
2. **Recrearlo** — se creará en el webserver actual

Alternativa manual (sin eliminar datos):
```bash
# Backup
cp -r /home/usuario/web/ejemplo.com /home/usuario/web/ejemplo.com.backup

# Borrar vhost Apache viejo
rm /etc/apache2/sites-available/ejemplo.com.conf
a2dissite ejemplo.com
systemctl reload apache2

# Crear vhost Nginx nuevo
# (llamar a domain_manager.regenerate_vhost con webserver="nginx")

systemctl reload nginx
```

## Features compatibles en ambos

- ✅ SSL/TLS (certbot, SNI)
- ✅ IPv6 con netplan
- ✅ IPv4 dedicada
- ✅ Bad bots blocker
- ✅ Headers HTTP de seguridad
- ✅ Modo readonly (PUT/DELETE/POST)
- ✅ Redireccionamiento (301)
- ✅ FastCGI cache (Nginx solo, Apache usa mod_cache si se implementa)
- ✅ Rate limiting (Nginx via límites, Apache via mod_ratelimit si se implementa)

## Debugging

### Apache no arranca
```bash
apache2ctl configtest
# Ver errores
systemctl status apache2
journalctl -xe | grep apache2
```

### PHP no funciona
```bash
# Verificar socket PHP-FPM existe
ls /run/php/php8.2-fpm-svqpanel-ejemplo.com.sock

# Verificar permisos
stat /run/php/php8.2-fpm-svqpanel-ejemplo.com.sock

# Ver logs PHP
tail -f /var/log/php8.2-fpm.log
```

### Bad bots no bloquean
```bash
# Nginx: ver si /etc/nginx/conf.d/bad-bots.conf existe
cat /etc/nginx/conf.d/bad-bots.conf

# Apache: verificar que RewriteCond está en el vhost
grep -A2 "Bad Bots Blocker" /etc/apache2/sites-available/ejemplo.com.conf
```

## Notas futuras

- **FastCGI cache en Apache**: Implementar con `mod_cache` + `mod_cache_disk`
- **Rate limiting en Apache**: Implementar con `mod_ratelimit`
- **Sincronización de bots**: Cuando se actualiza la lista global de bad bots, regenerar todos los vhosts Apache si la instalación es "apache+nginx"
