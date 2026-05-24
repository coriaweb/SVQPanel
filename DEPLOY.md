GUÍA: SUBIR A GITHUB Y DESPLEGAR
=================================

## PASO 1: Crear repositorio en GitHub

1. Ve a: https://github.com/new
2. Rellena:
   - Repository name: `panel`
   - Description: "Panel de control de servidores"
   - Visibility: **PUBLIC** ✓
3. Click en "Create repository"

Ahora tienes: `https://github.com/tu-usuario/panel`

---

## PASO 2: Subir archivos a GitHub

### En tu máquina local:

```bash
# 1. Clona el repo vacío
git clone https://github.com/tu-usuario/panel.git
cd panel

# 2. Copia aquí TODOS estos archivos:
#    - install.sh
#    - requirements.txt
#    - README.md
#    - SUMMARY.md
#    - ROADMAP.md
#    - STRUCTURE.md
#    - .env.example
#    - .gitignore
#    - api/ (carpeta completa con main.py, models/, etc)
#    - scripts/ (carpeta, puede estar vacía)
#    - config/ (carpeta, puede estar vacía)

# 3. Haz commit y push
git add .
git commit -m "Fase 1: Estructura base del panel"
git push origin main
```

**Listo.** Ahora el código está en GitHub público.

---

## PASO 3: Desplegar en un servidor Debian

### En el servidor (como root):

```bash
# Opción A: Directa (si tu usuario es "tu-usuario")
curl https://raw.githubusercontent.com/tu-usuario/panel/main/install.sh | bash

# Opción B: Si el nombre del repo no es exactamente "panel"
# (Descarga primero y edita)
curl -o install.sh https://raw.githubusercontent.com/tu-usuario/panel/main/install.sh

# Edita la línea que dice:
# REPO_URL="https://github.com/tu-usuario/panel.git"
# Con tu URL correcta si es diferente

nano install.sh  # (o vim, o lo que uses)

# Ejecuta
bash install.sh
```

---

## PASO 4: Responder preguntas del installer

El script preguntará:

```
¿Qué webserver necesitas?
1) Nginx solo
2) Apache + Nginx
→ Elige 1 o 2

¿Qué versiones PHP necesitas?
Disponibles: 7.4, 8.0, 8.1, 8.2, 8.3
→ Escribe: 8.2 8.3
  (o solo 8.2, o las que quieras)
```

---

## PASO 5: Espera a que termine

El script:
- ✓ Actualiza sistema
- ✓ Instala dependencias
- ✓ Instala Nginx/Apache
- ✓ Instala PHP versions
- ✓ Configura PostgreSQL
- ✓ Clona tu repo en `/opt/panel`
- ✓ Configura Python

Cuando termina:

```
════════════════════════════════════════
✓ INSTALACIÓN COMPLETADA
════════════════════════════════════════

Próximos pasos:
1. cd /opt/panel
2. source venv/bin/activate
3. pip install -r requirements.txt
4. python api/main.py

El panel estará disponible en: http://localhost:8001
```

---

## PASO 6: Prueba que funciona

```bash
cd /opt/panel
source venv/bin/activate
pip install -r requirements.txt
python api/main.py
```

Abre: http://localhost:8001/docs

Deberías ver la documentación de la API.

---

## PASO 7: (Opcional) Actualizar código en todos los servidores

Cuando hagas cambios:

```bash
# En tu máquina:
git push origin main

# En cada servidor (manual o con cronjob):
cd /opt/panel
git pull origin main
```

---

## Resumen visual:

```
TU MÁQUINA
   ↓
git push → GitHub (public)
   ↓
SERVIDOR 1
   ↓
curl install.sh → git clone → /opt/panel funciona
   ↓
SERVIDOR 2, 3, N...
   ↓
(mismo proceso)
```

---

## Troubleshooting

### Error: "fatal: cannot access 'https://github.com/...'"
→ Verifica que el nombre del repo y usuario sean correctos

### Error: "PostgreSQL connection refused"
→ El script debería haber instalado PostgreSQL. Ejecuta:
```bash
sudo systemctl restart postgresql
```

### Error: "Port 8001 already in use"
→ Cambia el puerto en `/opt/panel/.env`

### El script se detiene sin terminar
→ Probablemente el SO no es Debian 12/13. Verifica:
```bash
cat /etc/os-release | grep VERSION_ID
```

---

¿Alguna duda? Puedes volver a ejecutar el install.sh cuando quieras.
