# Troubleshooting: Panel de Actualizaciones

## Problema: "0 paquetes disponibles" pero `apt` muestra actualizaciones

Este problema ocurre cuando el endpoint `/api/system/updates` no puede ejecutar correctamente `apt-get update` y `apt list --upgradable` debido a **permisos insuficientes**.

### Causas Comunes

1. **FastAPI no corre como root**
   - El servicio systemd debe tener `User=root` (revisar `/etc/systemd/system/svqpanel.service`)
   - O bien, el usuario bajo el que corre FastAPI no tiene permisos en sudoers

2. **Sudoers no está configurado**
   - Si FastAPI corre como usuario distinto a root, necesita permisos sudo sin contraseña
   - Archivo `/etc/sudoers.d/svqpanel-apt` no existe o está mal configurado

3. **Binarios apt no están disponibles**
   - Los comandos `apt-get` y `apt` no están en `/usr/bin` o no son accesibles

### Solución

#### 1. Verificar que FastAPI corre como root

```bash
# Ver el servicio
systemctl cat svqpanel | grep -A 5 "\[Service\]"
```

**Debe mostrar:**
```
User=root
```

Si no, editar `/etc/systemd/system/svqpanel.service` y cambiar `User=` a `root`, luego:
```bash
systemctl daemon-reload
systemctl restart svqpanel
```

#### 2. Configurar sudoers (si FastAPI NO corre como root)

Si por alguna razón FastAPI corre como otro usuario, ejecutar como root:

```bash
bash /opt/svqpanel/scripts/setup_sudoers.sh
```

O manualmente:
```bash
cat > /etc/sudoers.d/svqpanel-apt << 'EOF'
root ALL=(ALL) NOPASSWD: /usr/bin/apt-get, /usr/bin/apt
EOF
chmod 0440 /etc/sudoers.d/svqpanel-apt
visudo -c -f /etc/sudoers.d/svqpanel-apt
```

#### 3. Verificar que apt está disponible

```bash
which apt-get
which apt
# Deben mostrar: /usr/bin/apt-get y /usr/bin/apt
```

#### 4. Probar los comandos manualmente

```bash
# Actualizar índice
sudo apt-get update -qq

# Listar actualizables
sudo apt list --upgradable

# Contar
apt list --upgradable | grep -c "upgradable"
```

#### 5. Probar el endpoint directamente

```bash
curl -H "Authorization: Bearer <TU_TOKEN>" \
     https://svqhostpanel.svqhost.red/api/system/updates
```

Si devuelve un error, verifica el stderr del servicio:
```bash
journalctl -u svqpanel -n 50
```

### Instalación Limpia

Si la instalación es nueva, el `install.sh` ya configura sudoers automáticamente desde la versión actualizada. Solo asegúrate de ejecutar:

```bash
bash install.sh
```

### Debug

Si aún tienes problemas, añade logs al código:

1. Edita `/opt/svqpanel/api/routes/system.py`
2. En el endpoint `get_system_updates()`, descomenta las líneas de debug
3. Reinicia: `systemctl restart svqpanel`
4. Revisa: `journalctl -u svqpanel -f`

### Verifica el estado del servicio

```bash
systemctl status svqpanel
journalctl -u svqpanel -n 20 --no-pager
```

Si ves "Permission denied" o "command not found", ese es el error real.
