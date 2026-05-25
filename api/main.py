from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime
import os
import sys

# Añadir el directorio parent al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.models.database import create_tables, get_db
from config.config import PANEL_NAME, PANEL_VERSION

from api.routes import users, domains, php, ssl, ipv6, auth, settings, dns, system, mail

# Crear app FastAPI
app = FastAPI(
    title=PANEL_NAME,
    description="Panel de control para servidores web",
    version=PANEL_VERSION,
)

# CORS - Permitir requests desde frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Desarrollo: permitir todas las origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Crear tablas al iniciar
@app.on_event("startup")
async def startup():
    create_tables()
    _run_migrations()
    print(f"✓ {PANEL_NAME} v{PANEL_VERSION} iniciado")
    print(f"✓ Base de datos sincronizada")


def _run_migrations():
    """Migraciones incrementales para instalaciones existentes"""
    from api.models.database import engine
    from sqlalchemy import text
    migrations = [
        # Fase 5+: columna parent_id para sistema reseller
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES users(id) ON DELETE SET NULL",
        # Fase 6: interfaz de red en settings
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS network_interface VARCHAR(20) DEFAULT 'eth0'",
        # Fase 7: DNS — tablas dns_zones y dns_records (ya las crea create_all, pero por si acaso)
        """CREATE TABLE IF NOT EXISTS dns_zones (
            id SERIAL PRIMARY KEY,
            domain_name VARCHAR(255) UNIQUE NOT NULL,
            serial INTEGER DEFAULT 2026052501,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS dns_records (
            id SERIAL PRIMARY KEY,
            zone_id INTEGER NOT NULL REFERENCES dns_zones(id) ON DELETE CASCADE,
            record_type VARCHAR(10) NOT NULL,
            name VARCHAR(255) NOT NULL,
            content TEXT NOT NULL,
            ttl INTEGER DEFAULT 14400,
            priority INTEGER DEFAULT 0
        )""",
        # Fase 7b: campos extra en dns_zones
        "ALTER TABLE dns_zones ADD COLUMN IF NOT EXISTS ip_address VARCHAR(45)",
        "ALTER TABLE dns_zones ADD COLUMN IF NOT EXISTS soa_ns VARCHAR(255) DEFAULT 'ns1.svqpanel.local'",
        "ALTER TABLE dns_zones ADD COLUMN IF NOT EXISTS ttl INTEGER DEFAULT 14400",
        "ALTER TABLE dns_zones ADD COLUMN IF NOT EXISTS template VARCHAR(50) DEFAULT 'default'",
        "ALTER TABLE dns_zones ADD COLUMN IF NOT EXISTS dnssec_enabled BOOLEAN DEFAULT FALSE",
        "ALTER TABLE dns_zones ADD COLUMN IF NOT EXISTS expires_at DATE",
        # Fase 9b: tablas de correo
        """CREATE TABLE IF NOT EXISTS mail_domains (
            id            SERIAL PRIMARY KEY,
            user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            domain_id     INTEGER REFERENCES domains(id) ON DELETE SET NULL,
            domain_name   VARCHAR(255) UNIQUE NOT NULL,
            is_active     BOOLEAN DEFAULT TRUE,
            dkim_enabled  BOOLEAN DEFAULT FALSE,
            dkim_selector VARCHAR(50) DEFAULT 'mail',
            dkim_public_key TEXT,
            catch_all     VARCHAR(255),
            max_mailboxes INTEGER DEFAULT 0,
            created_at    TIMESTAMP DEFAULT NOW(),
            updated_at    TIMESTAMP DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS mailboxes (
            id             SERIAL PRIMARY KEY,
            mail_domain_id INTEGER NOT NULL REFERENCES mail_domains(id) ON DELETE CASCADE,
            username       VARCHAR(255) NOT NULL,
            password_hash  VARCHAR(255) NOT NULL,
            quota_mb       INTEGER DEFAULT 1024,
            is_active      BOOLEAN DEFAULT TRUE,
            created_at     TIMESTAMP DEFAULT NOW(),
            updated_at     TIMESTAMP DEFAULT NOW(),
            UNIQUE (mail_domain_id, username)
        )""",
        """CREATE TABLE IF NOT EXISTS mail_aliases (
            id             SERIAL PRIMARY KEY,
            mail_domain_id INTEGER NOT NULL REFERENCES mail_domains(id) ON DELETE CASCADE,
            source         VARCHAR(255) NOT NULL,
            destination    VARCHAR(255) NOT NULL,
            is_active      BOOLEAN DEFAULT TRUE,
            created_at     TIMESTAMP DEFAULT NOW(),
            UNIQUE (mail_domain_id, source)
        )""",
        # Índices de correo para consultas frecuentes
        "CREATE INDEX IF NOT EXISTS ix_mail_domains_user_id ON mail_domains(user_id)",
        "CREATE INDEX IF NOT EXISTS ix_mailboxes_mail_domain_id ON mailboxes(mail_domain_id)",
        "CREATE INDEX IF NOT EXISTS ix_mail_aliases_mail_domain_id ON mail_aliases(mail_domain_id)",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception as e:
                print(f"⚠ Migration skipped: {e}")

# Health check
@app.get("/", tags=["Health"])
async def root():
    return {
        "status": "ok",
        "panel": PANEL_NAME,
        "version": PANEL_VERSION,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/api/health", tags=["Health"])
async def health_check(db: Session = Depends(get_db)):
    """Health check con verificación de BD"""
    try:
        from sqlalchemy import text
        # Verificar conexión a BD
        db.execute(text("SELECT 1"))
        return {
            "status": "ok",
            "database": "connected",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "error", "message": str(e)}
        )

app.include_router(auth.router, prefix="/api", tags=["Authentication"])
app.include_router(users.router, prefix="/api", tags=["Users"])
app.include_router(domains.router, prefix="/api", tags=["Domains"])
app.include_router(php.router, prefix="/api", tags=["PHP"])
app.include_router(ssl.router, prefix="/api", tags=["SSL"])
app.include_router(ipv6.router, prefix="/api", tags=["IPv6"])
app.include_router(settings.router, prefix="/api", tags=["Settings"])
app.include_router(dns.router, prefix="/api", tags=["DNS"])
app.include_router(system.router, prefix="/api", tags=["System"])
app.include_router(mail.router, prefix="/api", tags=["Mail"])
# Autoconfig/Autodiscover sin prefijo (clientes de correo los buscan en rutas raíz)
app.include_router(mail.router, prefix="", include_in_schema=False)

# Manejo de errores global
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "status": "error",
            "message": "Error interno del servidor",
            "detail": str(exc) if os.getenv("DEBUG") else None
        }
    )

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PANEL_PORT", 8001))
    host = os.getenv("PANEL_HOST", "127.0.0.1")
    
    print(f"\n{'='*50}")
    print(f"  {PANEL_NAME} v{PANEL_VERSION}")
    print(f"{'='*50}")
    print(f"  URL: http://{host}:{port}")
    print(f"  Docs: http://{host}:{port}/docs")
    print(f"{'='*50}\n")
    
    uvicorn.run(
        "api.main:app",
        host=host,
        port=port,
        reload=True,
        log_level="info"
    )
