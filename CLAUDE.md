# SVQPanel - Guía de Desarrollo

**Proyecto**: Panel de control de servidores web en Python + FastAPI + PostgreSQL  
**Repositorio**: https://github.com/coriaweb/SVQPanel  
**Desarrollador**: coriaweb

## 🧪 Servidor de pruebas

Hay un **servidor de test real** para probar cambios. Sus credenciales (SSH, BD,
admin del panel, rutas, comandos de despliegue) están en **`SERVER_CREDENTIALS.md`**
(en la raíz del repo, en `.gitignore`, nunca se sube). Si necesitas probar algo en
un servidor real, usa ese archivo. Flujo: subir archivos por scp/sshpass →
`systemctl restart svqpanel` (backend) y/o `npm run build` en `frontend/` (UI).

## 🔢 REGLA IMPORTANTE: actualizar VERSION en cada cambio

El archivo `VERSION` (raíz del repo) es la fuente de verdad de la versión del panel.
**Cada vez que hagas cualquier cambio al código, debes actualizar VERSION siguiendo semver:**

- **PATCH** (`0.2.0 → 0.2.1`): fix de bug, corrección en install, parche de seguridad
- **MINOR** (`0.2.0 → 0.3.0`): nueva feature, update de componente (nginx, PostgreSQL, PHP...)
- **MAJOR** (`0.2.0 → 1.0.0`): cambio que rompe compatibilidad o rediseño importante

Esto es obligatorio en **cada commit**, sin excepciones. Si el cambio es trivial (typo, comentario), sube PATCH.

## ⚠️ REGLA IMPORTANTE: install.sh es la fuente de verdad del sistema

Todo cambio que afecte a la configuración del servidor (pools PHP-FPM, nginx,
permisos, hardening, paquetes, servicios, políticas de seguridad) **DEBE quedar
reflejado en `install.sh`**, para que una instalación o reinstalación limpia
nazca ya con ese estado. No basta con cambiar el código del panel: si el install
no lo aplica, un servidor nuevo quedaría con la configuración antigua.

Patrón recomendado: el install **no hardcodea** la lógica, sino que invoca el
mismo código del panel (p. ej. `python -m api.cli migrate_php_pools --force`),
de modo que un único cambio en el código se propaga a runtime y a install.

## 🌐 Soporte Dual Apache + Nginx (Fase 15)

El panel soporta dos configuraciones de instalación:
1. **Nginx solo** — recomendado, mejor rendimiento
2. **Apache + Nginx** — Apache para dominios legacy, Nginx para velocidad

**Arquitectura:**
- `scripts/webserver_config.py` — detecta/guarda la opción elegida en `/etc/svqpanel/webserver.conf`
- `scripts/apache_vhost_generator.py` — genera vhosts Apache con feature parity a Nginx
  - Headers HTTP de seguridad (X-Frame-Options, X-Content-Type-Options, HSTS, CSP, etc.)
  - Bloqueo de bots maliciosos (RewriteCond)
  - SSL/TLS, IPv6, IPv4, redireccionamiento
  - Modo readonly (PUT/DELETE/POST bloqueados)
- `scripts/domain_manager.py` — auto-detecta webserver y crea vhost Apache o Nginx
- `install.sh` — guarda la opción elegida en `/etc/svqpanel/webserver.conf` tras la instalación

**Flujo:**
1. Durante `install.sh`, user elige "1) Nginx" o "2) Apache+Nginx" → se guarda en `/etc/svqpanel/webserver.conf`
2. Al crear un dominio, `domain_manager.create_domain()` detecta la opción y crea vhost Apache o Nginx
3. Features (bad bots, SSL, IPv6, etc.) funcionan igual en ambos
4. Para Apache+Nginx: nuevos dominios van a Apache; dominios previos quedan donde estén

**Notas técnicas:**
- Apache usa `ProxyPassMatch` con socket PHP-FPM (mismo que Nginx)
- Bad bots: Nginx usa `map $http_user_agent` global; Apache usa `RewriteCond` por vhost
- Headers: inyectados via `Header always set ...` en Apache, directamente en vhost Nginx

## ⚙️ Tuning de recursos por dominio y de la BD (Fase 21)

**PHP-FPM por dominio** — además del php.ini por dominio, se puede ajustar el
*process manager* del pool (consumo de RAM/CPU de la cuenta):
- `scripts/php_ini_manager.py` — `FPM_PRESETS` (low/medium/high), `resolve_fpm_tuning()`
  (aplica caps del servidor `FPM_MAX_*` y coherencia de directivas según `pm`),
  `validate_fpm_tuning()`. `_pool_content` ya no hardcodea `pm.*`: los toma del tuning.
- Persistencia: `Domain.fpm_pool_overrides` (JSON `{"preset":..,"manual":{..}}`; NULL = medium).
  Todos los callers de `write_pool()` pasan `fpm_tuning` (incl. `template_manager`).
- API: `GET/PUT /api/domains/{id}/fpm-config`. UI: tab PHP de DomainDetail (presets + manual).

**Tuner de MariaDB/MySQL** (solo admin, config GLOBAL del servidor):
- `scripts/mysql_tuner.py` — lee `SHOW GLOBAL STATUS/VARIABLES` vía CLI (sin deps),
  `analyze()` genera recomendaciones tipo mysqltuner (buffer pool hit, conexiones,
  tmp en disco, query cache…), `write_dropin()` escribe SOLO un drop-in propio
  (`/etc/mysql/mariadb.conf.d/99-svqpanel-tuner.cnf`) con una **allowlist** de
  directivas (`TUNABLE_DIRECTIVES`) — reversible borrando ese archivo.
- API: `api/routes/db_tuner.py` (`GET /db-tuner/status`, `PUT /db-tuner/config`,
  `POST /db-tuner/restart`). UI: `views/DbTuner.vue` (menú Administración → Optimizar BD).
- Reutiliza la config MariaDB de `databases.py` (env MARIADB_*).

## 🔒 Seguridad — Aislamiento PHP por dominio

Cada dominio tiene un **pool PHP-FPM dedicado** (`/etc/php/{ver}/fpm/pool.d/
svqpanel-{dominio}.conf`, socket propio) con bloque de seguridad inyectado
SIEMPRE como `php_admin_value` (el cliente no puede sobreescribirlo):

- `open_basedir = public_html : private : tmp_del_dominio` (**sin `/tmp` global**:
  un sitio no puede leer los archivos ni temporales de otro).
- `disable_functions` (exec/system/… salvo dominios con hardening relajado).
- `upload_tmp_dir`, `session.save_path` y `sys_temp_dir` → todos al tmp propio
  del dominio: `/home/{usuario}/web/{dominio}/tmp` (aislado, owner www-data 0700).

Definido en `scripts/php_ini_manager.py` (`_security_block` / `write_pool`).

- Auditoría/reparación: `scripts/security_audit.py` + endpoints
  `GET/POST /api/security/php-isolation` + tarjeta en la vista Seguridad.
- Reparar en bloque por CLI: `python -m api.cli migrate_php_pools --force`
  (lo usa `install.sh`; `--force` reescribe pools existentes con la política nueva).

## 🎨 Sistema de Diseño (UI 2026)

Rediseño premium del frontend (Vue 3 + Vite). Estética tipo Linear/Vercel/Stripe,
modo claro/oscuro. **No usa Bootstrap para componentes nuevos**: CSS con tokens.

- `frontend/src/assets/tokens.css` — design tokens (color índigo, light/dark,
  radios, sombras, tipografía Inter/JetBrains Mono, espaciado, motion). Cargado
  en `main.js`; el tema se aplica vía `document.documentElement.dataset.theme`.
- `frontend/src/assets/bootstrap-bridge.css` — reestiliza las clases tipo Bootstrap
  (.card, .btn, .table, .form-control, .badge, .alert…) con los tokens, para las
  vistas que aún usan ese markup.
- `frontend/src/assets/bootstrap-compat.css` — replica las utilidades de Bootstrap
  (grid row/col, flex, spacing, display, text, sizing, spinner, form-check/switch).
  **Bootstrap ya NO se carga** (ni CSS ni JS): el estilo lo dan tokens + compat +
  bridge. Solo se mantiene Bootstrap Icons (clases bi-*) por CDN.
- `frontend/src/components/ui/` — componentes propios: BaseCard, BaseButton,
  BaseTabs, StatusBadge, MetricCard, ResourceGauge, EmptyState.
- Tema y sidebar colapsable en el store Pinia (`useMainStore`: `theme`,
  `toggleTheme`, `sidebarCollapsed`, `toggleSidebar`).
- `App.vue` — shell con sidebar agrupado por categorías (Hosting/Archivos/
  Administración/Sistema), topbar con breadcrumb + toggle tema + menú usuario.
- Vistas reescritas a fondo: Dashboard, Domains (tarjetas+tabla), DomainDetail
  (`/domains/:id` con tabs), Login. Resto: look vía bridge + cabeceras.
- Router con **code-splitting** (lazy `import()`); solo Dashboard+Login en el
  bundle inicial.

Convención al migrar una vista: cabecera con patrón `page-head` (título 2xl +
subtítulo), usar componentes de `components/ui/`, estilos con variables de tokens.

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
