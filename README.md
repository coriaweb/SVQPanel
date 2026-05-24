# Panel Control - Servidor Web

Panel de control de servidores web desarrollado en **Python + FastAPI + PostgreSQL**.

Similar a Hestia, pero con arquitectura moderna, mantenido por tu empresa y sin dependencias externas.

## 🎯 Características

- ✅ Gestión de usuarios del sistema
- ✅ Gestión de dominios web
- ✅ Múltiples versiones de PHP
- ✅ Certificados SSL automáticos (Let's Encrypt)
- ✅ Soporte IPv4 e IPv6
- ✅ Webserver: Nginx y/o Apache
- ✅ API REST completamente documentada
- ✅ Base de datos PostgreSQL

## 📋 Requisitos

### Sistema Operativo
- Debian 12, 13

### Requisitos mínimos
- 2GB RAM
- 10GB disco
- Conexión a internet (para Let's Encrypt)

## 🚀 Instalación rápida

### Paso 1: Crear repositorio público en GitHub

1. Ve a https://github.com/new
2. Nombre: `panel`
3. **Visibilidad: PUBLIC** ✓
4. Crea el repo

### Paso 2: Sube los archivos a GitHub

```bash
git clone https://github.com/tu-usuario/panel.git
cd panel
# Copia aquí todos los archivos (install.sh, requirements.txt, etc)
git add .
git commit -m "Fase 1: Estructura base del panel"
git push origin main
```

### Paso 3: Ejecuta en el servidor

En un servidor **Debian 12/13 limpio como root**:

```bash
# Primero, edita la URL si tu repo no es "tu-usuario/panel":
curl https://raw.githubusercontent.com/tu-usuario/panel/main/install.sh | sed 's|tu-usuario/panel|tu-usuario/tu-repo|g' | bash

# O descarga, edita y ejecuta:
curl -o install.sh https://raw.githubusercontent.com/tu-usuario/panel/main/install.sh
# Edita la línea: REPO_URL="..." con tu URL correcta
bash install.sh
```

El script te preguntará:
1. **Webserver**: Nginx solo o Apache + Nginx
2. **Versiones PHP**: 7.4, 8.0, 8.1, 8.2, 8.3 (elige las que necesites)

## 📁 Estructura del proyecto

```
/opt/panel/
├── api/                    # FastAPI application
│   ├── main.py            # App principal
│   ├── models/            # BD models (Usuario, Dominio)
│   ├── routes/            # Endpoints REST
│   └── utils/             # Utilidades
├── scripts/               # Scripts de gestión
│   ├── user_manager.py    # Crear/eliminar usuarios
│   ├── domain_manager.py  # Crear/eliminar dominios
│   ├── php_manager.py     # Cambiar versión PHP
│   └── ...
├── config/                # Configuración
├── logs/                  # Archivos de log
├── venv/                  # Entorno virtual Python
└── requirements.txt       # Dependencias
```

## ⚙️ Configuración

### 1. Clonar repositorio (Después de instalar)
```bash
cd /opt/panel
# Aquí va tu repo privado de GitHub
```

### 2. Variables de entorno
```bash
cp .env.example .env
# Editar .env con tus valores
nano .env
```

### 3. Instalar dependencias Python
```bash
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Iniciar el panel
```bash
python api/main.py
```

El panel estará disponible en: **http://localhost:8001**

Documentación API: **http://localhost:8001/docs**

## 📚 API Documentation

### Usuarios
```
POST   /api/users              # Crear usuario
GET    /api/users              # Listar usuarios
GET    /api/users/{id}         # Obtener usuario
PUT    /api/users/{id}         # Actualizar usuario
DELETE /api/users/{id}         # Eliminar usuario
```

### Dominios
```
POST   /api/domains            # Crear dominio
GET    /api/domains            # Listar dominios
GET    /api/domains/{id}       # Obtener dominio
PUT    /api/domains/{id}       # Actualizar dominio
DELETE /api/domains/{id}       # Eliminar dominio
```

### PHP
```
GET    /api/php/versions       # Versiones instaladas
PUT    /api/domains/{id}/php   # Cambiar PHP
```

### SSL
```
POST   /api/domains/{id}/ssl   # Crear certificado
GET    /api/domains/{id}/ssl   # Ver SSL
DELETE /api/domains/{id}/ssl   # Revocar SSL
```

### IPv6
```
POST   /api/domains/{id}/ipv6  # Asignar IPv6
GET    /api/domains/{id}/ipv6  # Ver IPv6
```

## 🔐 Seguridad

- Cambiar `SECRET_KEY` en `.env`
- Generar nuevo `API_TOKEN`
- Usar HTTPS en producción
- Limitar acceso a API (firewall)
- Mantener PostgreSQL seguro

## 📝 Logs

Los logs se guardan en: `/opt/panel/logs/panel.log`

```bash
# Ver logs en tiempo real
tail -f /opt/panel/logs/panel.log

# Ver últimas líneas
tail -20 /opt/panel/logs/panel.log
```

## 🐛 Troubleshooting

### Error: "Database connection refused"
```bash
# Verificar PostgreSQL está corriendo
sudo systemctl status postgresql

# Reiniciar PostgreSQL
sudo systemctl restart postgresql
```

### Error: "Port 8001 already in use"
```bash
# Cambiar puerto en .env
PANEL_PORT=8002
```

### Error: "Permission denied" al crear usuario
```bash
# El script necesita permisos de root
sudo python api/main.py
```

## 🤝 Contribuir

Este es un proyecto interno de la empresa. Para cambios:
1. Crear rama: `git checkout -b feature/mi-cambio`
2. Commit: `git commit -m "Descripción del cambio"`
3. Push: `git push origin feature/mi-cambio`
4. Pull Request

## 📞 Soporte

Para reportar bugs o sugerencias:
- Issues: GitHub
- Email: soporte@tu-empresa.com

## 📄 Licencia

Privada - Solo para uso interno de la empresa.

---

**Última actualización**: Mayo 2026
**Versión**: 1.0.0-beta
**Estado**: En desarrollo
