# Guía de Instalación en WSL2 (Windows)

## Requisitos Previos

- Windows 10/11 con WSL2 habilitado
- Python 3.14+ (Windows)
- Git configurado

## Paso 1: Instalar Debian en WSL2

Si no tienes ninguna distribución Linux instalada:

```powershell
# En PowerShell como administrador
wsl --install -d Debian --no-launch
```

Esto descarga e instala Debian 13 en WSL2 (~2-3 minutos).

## Paso 2: Iniciar WSL2 y Preparar

```powershell
# En PowerShell
wsl -d Debian
```

Dentro de WSL (terminal Linux):

```bash
# Actualizar paquetes
sudo apt update && sudo apt upgrade -y

# Instalar git
sudo apt install -y git
```

## Paso 3: Clonar SVQPanel

```bash
# Opción A: En /opt (requiere sudo)
sudo git clone https://github.com/coriaweb/SVQPanel.git /opt/svqpanel
sudo chown -R $USER:$USER /opt/svqpanel
cd /opt/svqpanel

# Opción B: En home (sin sudo)
cd ~
git clone https://github.com/coriaweb/SVQPanel.git svqpanel
cd svqpanel
```

## Paso 4: Resolver Permisos de Git

Si obtienes error "dubious ownership":

```bash
git config --global --add safe.directory /opt/svqpanel
```

## Paso 5: Ejecutar Install Script

```bash
cd /opt/svqpanel

# Obtener cambios más recientes
git pull origin main

# Ejecutar instalación
sudo bash install.sh
```

### Durante la instalación:

**Webserver:** Elige `1` (Nginx)

**Versiones PHP:** Elige `8.2` (o `8.2 8.1` para múltiples)

⚠️ **Nota importante:** PHP 8.3+ puede no estar disponible en Debian 13. El script ahora maneja esto automáticamente.

## Paso 6: Verificar Instalación

```bash
# Ver estado del servicio
sudo systemctl status svqpanel

# Ver logs en tiempo real
sudo journalctl -u svqpanel -f

# Verificar que PostgreSQL esté corriendo
sudo systemctl status postgresql

# Verificar que Nginx esté corriendo
sudo systemctl status nginx
```

## Paso 7: Acceder desde Windows

Para acceder a SVQPanel desde tu navegador en Windows, necesita la IP de WSL:

```bash
# Dentro de WSL
hostname -I
```

O desde PowerShell en Windows:

```powershell
wsl hostname -I
```

Luego abre en tu navegador (reemplaza XX.XX.XX.XX con la IP):

- **API directa**: `http://XX.XX.XX.XX:8001`
- **Swagger docs**: `http://XX.XX.XX.XX:8001/docs`
- **Via Nginx**: `http://XX.XX.XX.XX`

## Troubleshooting

### Error: "Permission denied" en /opt

```bash
sudo chown -R $USER:$USER /opt/svqpanel
```

### Error: "software-properties-common not found"

El script ya está corregido para Debian 13. Asegúrate de tener la última versión:

```bash
git pull origin main
```

### PostgreSQL no inicia

```bash
sudo systemctl restart postgresql
sudo systemctl status postgresql
```

### Nginx no funciona

```bash
# Revisar sintaxis
sudo nginx -t

# Reiniciar
sudo systemctl restart nginx
```

### Ver logs de SVQPanel

```bash
sudo journalctl -u svqpanel -n 50 -f
```

## Comandos Útiles

```bash
# Reiniciar el servicio
sudo systemctl restart svqpanel

# Detener el servicio
sudo systemctl stop svqpanel

# Iniciar el servicio
sudo systemctl start svqpanel

# Ver estado completo
systemctl status svqpanel

# Habilitar autostart
sudo systemctl enable svqpanel

# Ver últimas 100 líneas de logs
sudo journalctl -u svqpanel -n 100

# Seguir logs en tiempo real
sudo journalctl -u svqpanel -f

# Buscar errores en los últimos 10 minutos
sudo journalctl -u svqpanel --since "10 min ago" | grep -i error
```

## Notas Importantes

1. **Permisos**: WSL2 con /opt requiere sudo. Si prefieres evitarlo, clona en tu home.

2. **Direcciones IP**: La IP de WSL cambia cada vez que se reinicia. Usa `hostname -I` para obtener la actual.

3. **Rendimiento**: WSL2 tiene buen rendimiento, pero el sistema de archivos Linux dentro de WSL es más lento que NTFS. Para desarrollo está bien.

4. **Base de datos**: Credenciales por defecto (cambiar en producción):
   - Usuario: `panel_user`
   - Contraseña: `panel_password_123`
   - Base de datos: `panel_db`

5. **Port 8001**: FastAPI corre en puerto 8001. Nginx escucha en puerto 80.

## Diferencias con Instalación en Servidor Real

En un servidor Debian 12/13 real:
- Los pasos son **idénticos**
- La IP es fija (no cambia)
- Mejor rendimiento del sistema de archivos
- Acceso directo sin WSL

El install.sh funciona igual en ambos casos.

---

**Última actualización**: 2026-05-24  
**Compatible con**: Debian 12, 13 (via WSL2 o servidor real)
