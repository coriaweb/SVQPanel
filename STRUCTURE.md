Panel Control - Estructura del Proyecto
======================================

```
/opt/panel/
├── venv/                          # Entorno Python virtual
├── api/
│   ├── main.py                    # FastAPI app principal
│   ├── auth.py                    # Autenticación y tokens
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── users.py               # CRUD usuarios
│   │   ├── domains.py             # CRUD dominios
│   │   ├── php.py                 # Gestión PHP versions
│   │   ├── ssl.py                 # Let's Encrypt
│   │   └── ipv6.py                # Gestión IPv6
│   ├── models/
│   │   ├── __init__.py
│   │   ├── user.py                # Modelo Usuario
│   │   ├── domain.py              # Modelo Dominio
│   │   ├── database.py            # Setup de BD
│   │   └── schemas.py             # Schemas Pydantic
│   └── utils/
│       ├── __init__.py
│       ├── logger.py              # Logging
│       └── decorators.py          # Decoradores custom
├── scripts/
│   ├── user_manager.py            # Crear/eliminar usuarios
│   ├── domain_manager.py          # Crear/eliminar dominios
│   ├── php_manager.py             # Cambiar PHP versions
│   ├── ssl_manager.py             # Certificados SSL
│   ├── ipv6_manager.py            # Gestión IPv6
│   └── nginx_manager.py           # Configuración Nginx
├── config/
│   ├── config.py                  # Configuración general
│   └── database.ini               # Credenciales BD
├── frontend/                      # (Opcional, para luego)
│   ├── index.html
│   ├── css/
│   └── js/
├── logs/
│   └── panel.log
├── data/
│   └── (datos del panel)
├── requirements.txt               # Dependencias Python
├── .gitignore
├── README.md
└── install.sh                     # Script instalación
```

Archivos a crear en orden:
1. requirements.txt (dependencias)
2. api/main.py (app principal)
3. api/models/ (BD modelos)
4. api/routes/ (endpoints)
5. scripts/ (lógica de negocio)
