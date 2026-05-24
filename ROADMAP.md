PANEL CONTROL - GUÍA DE IMPLEMENTACIÓN
=====================================

## COMPATIBILIDAD
- Debian 12, 13

## FASE 1: ESTRUCTURA BASE ✓ (COMPLETADA)

Archivos creados:
✓ install.sh - Script instalación servidor
✓ requirements.txt - Dependencias Python
✓ api/models/database.py - Conexión PostgreSQL
✓ api/models/user.py - Modelo Usuario
✓ api/models/domain.py - Modelo Dominio
✓ api/main.py - App FastAPI principal

## FASE 2: RUTAS API (PRÓXIMO)

Necesitamos crear los endpoints REST:

### 2.1 - api/routes/users.py
```
POST   /api/users              - Crear usuario
GET    /api/users              - Listar usuarios
GET    /api/users/{user_id}    - Obtener usuario
PUT    /api/users/{user_id}    - Actualizar usuario
DELETE /api/users/{user_id}    - Eliminar usuario
POST   /api/users/login        - Login (obtener token)
```

### 2.2 - api/routes/domains.py
```
POST   /api/domains             - Crear dominio
GET    /api/domains             - Listar dominios del usuario
GET    /api/domains/{domain_id} - Obtener dominio
PUT    /api/domains/{domain_id} - Actualizar dominio
DELETE /api/domains/{domain_id} - Eliminar dominio
```

### 2.3 - api/routes/php.py
```
GET    /api/php/versions        - Listar versiones PHP instaladas
PUT    /api/domains/{id}/php    - Cambiar PHP de dominio
```

### 2.4 - api/routes/ssl.py
```
POST   /api/domains/{id}/ssl    - Crear certificado SSL
GET    /api/domains/{id}/ssl    - Ver detalles SSL
DELETE /api/domains/{id}/ssl    - Revocar SSL
```

### 2.5 - api/routes/ipv6.py
```
POST   /api/domains/{id}/ipv6   - Asignar IPv6
GET    /api/domains/{id}/ipv6   - Ver IPv6
```

## FASE 3: SCRIPTS PYTHON (FUNCIONES REALES)

Los scripts harán el trabajo real en el servidor:

### 3.1 - scripts/user_manager.py
Crear/eliminar usuarios del sistema con:
- adduser (crear)
- userdel (eliminar)
- passwd (cambiar contraseña)
- Crear carpeta /home/usuario/public_html

### 3.2 - scripts/domain_manager.py
Crear/eliminar dominios:
- Crear carpeta /home/user/public_html/domain.com
- Configurar Nginx vhost
- Configurar permisos (chown, chmod)
- Activar/desactivar en Nginx

### 3.3 - scripts/php_manager.py
Cambiar versión PHP:
- Detener PHP-FPM actual
- Cambiar socket en Nginx config
- Iniciar nuevo PHP-FPM
- Reload Nginx

### 3.4 - scripts/ssl_manager.py
Gestionar certificados SSL:
- Ejecutar certbot
- Copiar certificados a carpeta segura
- Configurar Nginx con SSL
- Auto-renewal con cronjob

### 3.5 - scripts/ipv6_manager.py
Gestionar IPv6:
- Asignar IPv6 a vhost Nginx
- Configurar DNS si procede
- Verificar conectividad

### 3.6 - scripts/nginx_manager.py
Configurar Nginx:
- Generar templates de vhost
- Reload/restart Nginx
- Validar configuración

## FLUJO DE UN USUARIO USANDO EL PANEL

1. POST /api/users (crear usuario "juan")
   → Script crea usuario del SO
   → Usuario existe en BD
   
2. POST /api/domains (crear "juanblog.com" para "juan")
   → Script crea carpeta /home/juan/public_html/juanblog.com
   → Script genera config Nginx
   → Dominio existe en BD
   
3. PUT /api/domains/juanblog/php (cambiar a PHP 8.3)
   → Script cambia configuración Nginx
   → Reload Nginx
   → BD actualiza versión
   
4. POST /api/domains/juanblog/ssl (crear certificado)
   → Script ejecuta certbot
   → Copia certificados
   → Configura HTTPS en Nginx
   → BD guarda info SSL

## ESTRUCTURA DE CARPETAS EN EL SERVIDOR

Después de crear usuario "juan" con dominio "juanblog.com":

```
/home/juan/
├── public_html/
│   └── juanblog.com/
│       ├── index.php
│       ├── wp-config.php (etc)
│       └── .htaccess
├── .ssh/
│   └── authorized_keys
└── .bashrc

/etc/nginx/sites-available/
├── juanblog.com (config del vhost)
└── default

/etc/ssl/certs/panel/
├── juanblog.com.crt
└── juanblog.com.key

/opt/panel/
└── logs/
    └── panel.log (registro de acciones)
```

## FLUJO DE DESARROLLO

Fase 1 ✓ Estructura base (hecho)
Fase 2 → Rutas API (2-3 días)
Fase 3 → Scripts Python (3-4 días)
Fase 4 → Frontend básico HTML (2-3 días)
Fase 5 → Testing y fixes (1 semana)

Total: ~3-4 semanas para MVP funcional

## CÓMO EJECUTAR AHORA MISMO (en tu máquina)

1. Copiar los archivos a /opt/panel/
2. cd /opt/panel
3. python3 -m venv venv
4. source venv/bin/activate
5. pip install -r requirements.txt
6. # Crear variables de entorno
7. export DATABASE_URL="postgresql://panel_user:panel_password_123@localhost/panel_db"
8. python api/main.py

Irás a: http://localhost:8001/docs y verás Swagger con los endpoints.

## SIGUIENTES PASOS

¿Quieres que haga:
A) Las rutas API (usuarios, dominios, etc)?
B) Los scripts Python (crear usuarios, dominios, etc)?
C) El frontend HTML (interfaz gráfica básica)?

¿Por dónde empezamos?
