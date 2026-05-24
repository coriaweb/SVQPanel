# Guía de Actualización - SVQPanel

## Para Servidor Existente

Si ya tienes SVQPanel instalado, **NO ejecutes `install.sh`** nuevamente. En su lugar, usa el script de actualización:

### Paso 1: Descargar script de actualización
```bash
cd /opt/svqpanel
git pull origin main
```

### Paso 2: Ejecutar actualización
```bash
sudo bash update.sh
```

El script hará automáticamente:
- ✅ Detener el servicio SVQPanel
- ✅ Hacer backup de tu archivo `.env`
- ✅ Descargar los últimos cambios de git
- ✅ Actualizar dependencias Python
- ✅ Actualizar/compilar el frontend
- ✅ Ejecutar migraciones de BD
- ✅ Reiniciar el servicio
- ✅ Verificar que todo funciona

### Paso 3: Verificar funcionamiento
```bash
# Revisar que el servicio está corriendo
sudo systemctl status svqpanel

# Ver logs en tiempo real
sudo journalctl -u svqpanel -f

# Probar API
curl http://localhost:8001/api/health

# Probar usuario
curl http://localhost:8001/api/users
```

---

## Diferencias entre install.sh y update.sh

### `install.sh` - Para instalación limpia
- Instala todo desde cero
- Crea usuario `svqpanel`
- Configura PostgreSQL, Nginx, PHP
- Genera `.env` desde cero
- Crea servicio systemd
- **Borra datos existentes** (no usar en servidor activo)

### `update.sh` - Para actualizar servidor existente
- Preserva `.env` y configuración
- Solo actualiza código
- Actualiza dependencias
- Mantiene BD intacta
- Reinicia servicio limpiamente
- **Seguro para usar en producción**

---

## Cambios en Esta Actualización

### Frontend (NUEVO - Fase 4) 🎨
- Vue 3 con Vite
- Componentes de formularios
- Modales para crear/editar usuarios y dominios
- Gestión de SSL desde UI
- Gestión de IPv6 desde UI
- Dashboard con estadísticas

### Backend (ACTUALIZADO)
- 17 endpoints ahora ejecutan comandos reales
- UserManager integrado en rutas de usuarios
- DomainManager integrado en rutas de dominios
- SSLManager para Let's Encrypt
- IPv6Manager para asignación de direcciones

### Scripts (NUEVO - Fase 3) ⚙️
- Creación de usuarios del sistema
- Configuración de Nginx vhosts
- Cambio de versiones PHP
- Gestión de certificados SSL
- Asignación de IPv6

---

## Plan de Actualización Recomendado

### Para servidor en producción con datos importantes:

**1. Antes de actualizar:**
```bash
# Backup de BD
sudo su - postgres
pg_dump svqpanel_db > /tmp/backup_$(date +%Y%m%d).sql
exit

# Backup de directorio
cp -r /opt/svqpanel /opt/svqpanel.backup
```

**2. Ejecutar actualización:**
```bash
sudo bash /opt/svqpanel/update.sh
```

**3. Después de actualizar:**
```bash
# Verificar que todo funciona
curl http://localhost:8001/api/users

# Probar nuevo frontend (si lo tienes en producción)
# Ir a http://tu-servidor:5173 (desarrollo)
# o http://tu-servidor/app (producción)
```

**4. Si algo sale mal, restaurar:**
```bash
# Detener servicio
sudo systemctl stop svqpanel

# Restaurar
rm -rf /opt/svqpanel
cp -r /opt/svqpanel.backup /opt/svqpanel

# Iniciar
sudo systemctl start svqpanel
```

---

## Actualización Manual (paso a paso)

Si prefieres hacer control total:

```bash
# 1. Detener servicio
sudo systemctl stop svqpanel

# 2. Actualizar código
cd /opt/svqpanel
git pull origin main

# 3. Actualizar dependencias Python
source venv/bin/activate
pip install -r requirements.txt
deactivate

# 4. Compilar frontend (si tienes)
cd frontend
npm install
npm run build

# 5. Verificar/actualizar BD
cd ..
source venv/bin/activate
python3 -c "
from api.models.database import Base, engine
from api.models.models_user import User
from api.models.models_domain import Domain
Base.metadata.create_all(bind=engine)
"
deactivate

# 6. Reiniciar servicio
sudo systemctl start svqpanel

# 7. Verificar
curl http://localhost:8001/api/health
```

---

## Solución de Problemas

### "Permission denied" al ejecutar update.sh
```bash
chmod +x /opt/svqpanel/update.sh
sudo bash /opt/svqpanel/update.sh
```

### Servicio no inicia después de actualizar
```bash
# Ver error específico
sudo journalctl -u svqpanel -n 50

# Verificar sintaxis Python
python3 -m py_compile api/main.py

# Reintentar
sudo systemctl restart svqpanel
```

### Frontend no carga cambios
```bash
# Limpiar caché y reconstruir
cd /opt/svqpanel/frontend
rm -rf node_modules dist
npm install
npm run build
```

### BD con errores
```bash
# Resetear tablas (CUIDADO: borra datos)
source /opt/svqpanel/venv/bin/activate
python3 << 'EOF'
from api.models.database import Base, engine
Base.metadata.drop_all(bind=engine)  # Borra todo
Base.metadata.create_all(bind=engine)  # Recrear
EOF
deactivate
```

---

## Verificar Actualización Exitosa

```bash
# 1. Servicio activo
sudo systemctl is-active svqpanel
# Salida: active ✓

# 2. API respondiendo
curl -s http://localhost:8001/api/health | grep -o "ok"
# Salida: ok ✓

# 3. BD actualizada
curl -s http://localhost:8001/api/users | head -c 100
# Salida: JSON con usuarios ✓

# 4. Ver versión instalada
cd /opt/svqpanel && git log -1 --oneline
```

---

## Programar Actualizaciones Automáticas (Opcional)

Para actualizar automáticamente cada noche:

```bash
# Editar crontab
sudo crontab -e

# Agregar esta línea (actualizar a las 2 AM):
0 2 * * * /opt/svqpanel/update.sh >> /var/log/svqpanel-update.log 2>&1
```

---

## Resumen

| Situación | Comando |
|-----------|---------|
| **Instalación nueva** | `sudo bash install.sh` |
| **Actualizar servidor existente** | `sudo bash update.sh` |
| **Actualización manual** | Ver "Actualización Manual" arriba |
| **Rollback a versión anterior** | `git reset --hard HEAD~1` |

---

**Recomendación**: Siempre usa `update.sh` para actualizaciones en servidor existente.
