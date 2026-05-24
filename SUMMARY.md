PANEL CONTROL - RESUMEN EJECUTIVO
=================================

## ¿Qué es?

Un panel de control de servidores web moderno, desarrollado en **Python + FastAPI + PostgreSQL**.

Similar a Hestia, pero:
- ✅ Código tuyo, mantenido por tu empresa
- ✅ Arquitectura moderna y escalable
- ✅ Fácil de customizar y extender
- ✅ Sin dependencias de terceros complicadas
- ✅ Compatible con Debian 12/13 y Ubuntu 20.04+

---

## ¿Qué TIENES ahora mismo?

Tras ejecutar `install.sh` en un servidor limpio:

```
✓ Sistema operativo detectado (Debian/Ubuntu)
✓ Nginx y/o Apache instalado (tú eliges)
✓ PHP 7.4, 8.0, 8.1, 8.2, 8.3 (tú eliges)
✓ PostgreSQL funcionando
✓ Estructura de carpetas /opt/panel
✓ Entorno virtual Python configurado
```

Luego haces:
```bash
cd /opt/panel
source venv/bin/activate
pip install -r requirements.txt
python api/main.py
```

Y el panel está en: **http://localhost:8001**

---

## ¿Qué viene DESPUÉS?

### Fase 2: Rutas API (próxima, ~1 semana)
Crear los endpoints REST que el frontend llama:

```
POST   /api/users              → Crear usuario
POST   /api/domains            → Crear dominio
PUT    /api/domains/ID/php     → Cambiar PHP
POST   /api/domains/ID/ssl     → Certificado SSL
POST   /api/domains/ID/ipv6    → Asignar IPv6
(... más endpoints)
```

### Fase 3: Scripts Python (~1.5 semanas)
Hacer que esos endpoints REALMENTE funcionen:

```
user_manager.py      → adduser, userdel, mkdir
domain_manager.py    → crear vhost, carpetas, permisos
php_manager.py       → cambiar versión PHP
ssl_manager.py       → certbot, certificados
ipv6_manager.py      → asignar IPv6
```

### Fase 4: Frontend (~1 semana)
Interfaz simple HTML/CSS/JS para:
- Login
- Crear usuarios
- Crear dominios
- Cambiar PHP
- Ver SSL status

### Fase 5: Testing (~1 semana)
Asegurar que todo funciona en producción.

**Total estimado: 4-5 semanas para MVP completamente funcional**

---

## Flujo de uso (ejemplo)

```
1. Ejecutas install.sh en servidor nuevo
   → El script instala TODO automáticamente

2. Haces git push en tu repo
   → Los servidores hacen auto-pull (cronjob)

3. Usuario accede a http://tuservidor.com:8001
   → Login en el panel
   
4. Crea usuario "juan"
   → Script crea /home/juan/
   → BD registra usuario
   
5. Crea dominio "juanblog.com"
   → Script crea /home/juan/public_html/juanblog.com
   → Script genera config Nginx
   → Dominio está LIVE en 10 segundos
   
6. Cambia a PHP 8.3
   → Script reloader Nginx
   → Dominio ahora usa PHP 8.3
   
7. Añade SSL
   → Script ejecuta certbot
   → HTTPS automático
```

---

## Estructura en GitHub

```
tu-empresa/panel/
├── install.sh              ← Script instalación
├── requirements.txt
├── api/
│   ├── main.py            ← App FastAPI
│   ├── models/            ← BD models
│   ├── routes/            ← Endpoints (próximo)
│   └── utils/
├── scripts/               ← Scripts Python (próximo)
├── config/
├── frontend/              ← HTML/JS (próximo)
├── .env.example
├── .gitignore
├── README.md
└── ROADMAP.md
```

Puedes clonarlo privado en GitHub, y cada servidor lo obtiene con:
```bash
git clone git@github.com:tu-empresa/panel.git /opt/panel
```

---

## Compatibilidad

**Sistemas operativos:**
- Debian 12, 13

**Webservers:**
- Nginx solo
- Apache + Nginx

**PHP:**
- 7.4, 8.0, 8.1, 8.2, 8.3 (todas o las que quieras)

**Base de datos:**
- PostgreSQL (instalado automáticamente)

---

## Seguridad

El `install.sh` configura:
- ✓ PostgreSQL con usuario/contraseña
- ✓ API FastAPI (solo localhost 127.0.0.1)
- ✓ Permisos de carpetas (700 para private)
- ✓ Certificados SSL con certbot

**Recomendaciones producción:**
- Cambiar `SECRET_KEY` en .env
- Cambiar `API_TOKEN` en .env
- Usar HTTPS en la API (Nginx proxy)
- Firewall: solo puerto 8001 desde IP confiada
- Backups automáticos de /opt/panel

---

## Ventajas vs Hestia

| Aspecto | Hestia | Tu Panel |
|--------|--------|---------|
| **Mantenimiento** | Depende Hestia devs | Tú lo controlas |
| **Actualizaciones** | Pueden romper tus cambios | Tú controlas todo |
| **Arquitectura** | Legacy PHP + Bash | Moderno: Python + FastAPI |
| **Personalización** | Limitada | Sin límites |
| **Escalabilidad** | Difícil | Fácil |
| **IPv6** | Medio implementado | Soporte completo (priority) |
| **Documentación** | Escasa | Tu código = documentación |
| **Costo** | Gratis, pero limitado | Gratis, control total |

---

## ¿Por dónde empiezo?

### Opción A: Quiero el código ya (Fase 2)
Si quieres que avance y haga las rutas API, dimelo.

### Opción B: Quiero entender todo primero
Lee:
- STRUCTURE.md → cómo está organizado
- ROADMAP.md → qué falta
- install.sh → qué hace en el servidor
- api/main.py → cómo funciona FastAPI

### Opción C: Quiero probarlo ya
En tu máquina (no necesita servidor):
```bash
# Instalar dependencias
pip install -r requirements.txt

# Ejecutar API (sin BD real, falla pero ves las rutas)
python api/main.py

# Ver docs en: http://localhost:8001/docs
```

---

## Siguiente paso: ¿Continuamos?

Una vez hayas revisado la estructura, ¿quieres que haga:

**A)** Las rutas API (usuarios, dominios, PHP, SSL, IPv6)
**B)** Los scripts Python que ejecutan las funciones reales
**C)** El frontend HTML/JS simple
**D)** Otra cosa

¿Cuál prefieres?

---

**Fecha**: Mayo 2026
**Estado**: Fase 1 completada ✓
**Siguiente**: Fase 2 (Rutas API)
