# SVQPanel - Guía de Desarrollo

**Proyecto**: Panel de control de servidores web en Python + FastAPI + PostgreSQL  
**Repositorio**: https://github.com/coriaweb/SVQPanel  
**Desarrollador**: coriaweb

## 📋 Estado del Proyecto

### Fase 1 ✅ COMPLETA
- `install.sh`: Script instalación para Debian 12/13
- Estructura base Python/FastAPI
- Modelos SQLAlchemy (User, Domain)
- Documentación

### Fase 2 ✅ COMPLETA

- Rutas API FastAPI: usuarios, dominios, PHP, SSL, IPv6, DNS, correo
- Autenticación JWT (Bearer token)
- Validaciones Pydantic

### Fase 3 ✅ COMPLETA

- Scripts Python para operaciones reales del SO
- Nginx, PHP-FPM, certbot, BIND9, Postfix/Dovecot/Rspamd

### Fase 10 ✅ COMPLETA — MariaDB para clientes

- Doble BD: PostgreSQL (panel) + MariaDB (clientes)
- `api/models/models_client_db.py` — modelo ClientDatabase
- `api/schemas/database_schemas.py` — schemas Pydantic
- `api/routes/databases.py` — CRUD + operaciones MariaDB reales
- `install.sh` — sección MariaDB 11.4 LTS (instalación opcional)

### Fase 4 ✅ COMPLETA — Frontend Vue 3 (Gestión de Bases de Datos)

- `frontend/src/views/Databases.vue` — vista principal con tabla de BDs
- `frontend/src/components/DatabaseForm.vue` — formulario para crear/editar
- `frontend/src/services/databaseService.js` — llamadas a API `/api/databases`
- Componentes Modal, tabla con acciones (editar, cambiar password, eliminar)
- Integración con router y menú principal
- Soporte para admin/reseller y usuarios finales

## 🔧 Tecnología Stack

- **Backend**: Python 3.14.5 + FastAPI
- **BD**: PostgreSQL
- **ORM**: SQLAlchemy
- **SO Soportado**: Debian 12, 13
- **Webservers**: Nginx y/o Apache
- **PHP**: 7.4, 8.0, 8.1, 8.2, 8.3

## 📁 Estructura de Archivos

```
SVQPanel/
├── api/
│   ├── main.py                  # App FastAPI principal
│   ├── models/
│   │   ├── models_database.py   # Configuración PostgreSQL
│   │   ├── models_user.py       # Modelo User (SQLAlchemy)
│   │   └── models_domain.py     # Modelo Domain (SQLAlchemy)
│   ├── routes/                  # (A CREAR)
│   │   ├── users.py             # CRUD usuarios
│   │   ├── domains.py           # CRUD dominios
│   │   ├── php.py               # Gestión versiones PHP
│   │   ├── ssl.py               # Certificados SSL
│   │   └── ipv6.py              # Asignación IPv6
│   └── schemas/                 # (A CREAR)
│       ├── user_schemas.py      # Pydantic models
│       ├── domain_schemas.py    # Pydantic models
│       └── ...
├── config/
│   └── config.py                # Variables globales (PANEL_NAME, VERSION)
├── install.sh                   # Script instalación
├── .env                         # Variables entorno (DATABASE_URL, etc)
├── requirements.txt             # Dependencias Python
└── CLAUDE.md                    # Esta guía

```

## 🔑 Configuración

### Variables de Entorno (.env)
```
DATABASE_URL=postgresql://panel_user:panel_password_123@localhost/panel_db
PANEL_NAME=SVQPanel
PANEL_VERSION=0.1.0
PANEL_HOST=127.0.0.1
PANEL_PORT=8001
DEBUG=False
SECRET_KEY=tu_secreto_aqui
```

### Modelos de BD

**User** (usuarios del panel)
- id, username, email, password_hash
- first_name, last_name
- is_admin, is_active
- domains_limit (max dominios)
- shell_path, home_dir
- timestamps (created_at, updated_at, last_login)
- Relación: many domains

**Domain** (dominios alojados)
- id, user_id, domain_name
- public_html (ruta física)
- php_version (7.4-8.3)
- ssl_enabled, ssl_certificate, ssl_key, ssl_expires
- ipv4, ipv6
- is_active, disk_usage
- timestamps

## 🛣️ Rutas API - Fase 2

### Usuarios (api/routes/users.py)
```
POST   /api/users              → Crear usuario
GET    /api/users              → Listar usuarios
GET    /api/users/{user_id}    → Obtener usuario
PUT    /api/users/{user_id}    → Actualizar usuario
DELETE /api/users/{user_id}    → Eliminar usuario
```

### Dominios (api/routes/domains.py)
```
POST   /api/domains            → Crear dominio
GET    /api/domains            → Listar dominios
GET    /api/domains/{domain_id} → Obtener dominio
PUT    /api/domains/{domain_id} → Actualizar dominio
DELETE /api/domains/{domain_id} → Eliminar dominio
```

### PHP (api/routes/php.py)
```
GET    /api/php/versions       → Listar versiones instaladas
PUT    /api/domains/{id}/php   → Cambiar versión PHP
```

### SSL (api/routes/ssl.py)
```
POST   /api/domains/{id}/ssl   → Crear certificado
GET    /api/domains/{id}/ssl   → Ver detalles SSL
DELETE /api/domains/{id}/ssl   → Revocar SSL
```

### IPv6 (api/routes/ipv6.py)
```
POST   /api/domains/{id}/ipv6  → Asignar IPv6
GET    /api/domains/{id}/ipv6  → Ver IPv6
```

## 📝 Convenciones de Código

### Rutas
- Usar `APIRouter` de FastAPI
- Prefix en `main.py`: `/api/users`, `/api/domains`, etc
- Tags para documentación automática

### Validaciones
- Usar Pydantic para request/response schemas
- Validar en el nivel de schema
- Lanzar `HTTPException` con status codes apropiados

### BD
- Usar `Session` dependency injection
- Commits automáticos con context managers
- Manejo de errores con try/except

### Respuestas JSON
```json
{
  "status": "success|error",
  "data": {},
  "message": "Operación completada"
}
```

## 🔐 Autenticación (Phase 2)

- Token simple (header: Authorization: Bearer <token>)
- Validación en endpoints protegidos
- A mejorar en futuras fases

## 🧪 Testing (Próximo)

- Tests unitarios para rutas
- Tests de integración con BD
- Coverage mínimo 80%

## 📦 Dependencias

```
fastapi==0.104.1
uvicorn==0.24.0
sqlalchemy==2.0.23
psycopg2-binary==2.9.9
pydantic==2.5.0
python-dotenv==1.0.0
```

## 🚀 Cómo ejecutar

```bash
# Instalar dependencias
pip install -r requirements.txt

# O con uv (recomendado)
uv sync

# Ejecutar servidor
python api/main.py

# O con uvicorn directamente
uvicorn api.main:app --reload --host 0.0.0.0 --port 8001
```

La documentación interactiva (Swagger) estará en:
`http://localhost:8001/docs`

## 📖 Notas Importantes

1. **Sin ejecutar comandos SO aún**: Las rutas devuelven JSON, sin ejecutar `adduser`, `nginx`, etc
2. **Modelos de BD listos**: Ya existen User y Domain en SQLAlchemy
3. **Importar modelos correctamente**: `from api.models.models_user import User`
4. **main.py comentado**: Las rutas importadas están comentadas, descomenta al crear

## 🔗 Links Útiles

- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [SQLAlchemy Docs](https://docs.sqlalchemy.org/)
- [Pydantic Docs](https://docs.pydantic.dev/)

---

**Última actualización**: 2026-05-24  
**Fase actual**: 2 (Rutas API)
