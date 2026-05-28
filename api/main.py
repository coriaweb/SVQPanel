from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session
from datetime import datetime
import os
import sys

# Añadir el directorio parent al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.models.database import create_tables, get_db
from config.config import PANEL_NAME, PANEL_VERSION

from api.routes import users, domains, php, ssl, ipv6, auth, settings, dns, system, mail, databases, firewall, fail2ban, security_monitor, ip_lists, file_manager, crowdsec, plans, sftp

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
        # Fase 9f: campos antispam por dominio
        "ALTER TABLE mail_domains ADD COLUMN IF NOT EXISTS spam_tag_threshold FLOAT DEFAULT 6.0",
        "ALTER TABLE mail_domains ADD COLUMN IF NOT EXISTS spam_reject_threshold FLOAT DEFAULT 15.0",
        "ALTER TABLE mail_domains ADD COLUMN IF NOT EXISTS whitelist_senders TEXT DEFAULT ''",
        "ALTER TABLE mail_domains ADD COLUMN IF NOT EXISTS blacklist_senders TEXT DEFAULT ''",
        # Índices de correo para consultas frecuentes
        "CREATE INDEX IF NOT EXISTS ix_mail_domains_user_id ON mail_domains(user_id)",
        "CREATE INDEX IF NOT EXISTS ix_mailboxes_mail_domain_id ON mailboxes(mail_domain_id)",
        "CREATE INDEX IF NOT EXISTS ix_mail_aliases_mail_domain_id ON mail_aliases(mail_domain_id)",
        # Fase 10: MariaDB — bases de datos de clientes
        """CREATE TABLE IF NOT EXISTS client_databases (
            id               SERIAL PRIMARY KEY,
            user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            domain_id        INTEGER REFERENCES domains(id) ON DELETE SET NULL,
            db_name          VARCHAR(64)  UNIQUE NOT NULL,
            db_name_suffix   VARCHAR(48)  NOT NULL,
            db_user          VARCHAR(64)  UNIQUE NOT NULL,
            db_user_suffix   VARCHAR(48)  NOT NULL,
            db_password_hash VARCHAR(255) NOT NULL,
            db_charset       VARCHAR(20)  DEFAULT 'utf8mb4',
            db_collation     VARCHAR(50)  DEFAULT 'utf8mb4_unicode_ci',
            quota_mb         INTEGER      DEFAULT 1024,
            size_mb          INTEGER      DEFAULT 0,
            is_active        BOOLEAN      DEFAULT TRUE,
            created_at       TIMESTAMP    DEFAULT NOW(),
            updated_at       TIMESTAMP    DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_client_databases_user_id   ON client_databases(user_id)",
        "CREATE INDEX IF NOT EXISTS ix_client_databases_domain_id  ON client_databases(domain_id)",
        # Límite de BDs por usuario
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS databases_limit INTEGER DEFAULT 5",
        # Fase 10b: contraseña cifrada con Fernet para phpMyAdmin autologin
        "ALTER TABLE client_databases ADD COLUMN IF NOT EXISTS db_password_enc VARCHAR(500)",
        # ─────────────────────────────────────────────────────────────────
        # Fase 12: Seguridad (firewall nftables, fail2ban, listas IP, auditoría)
        # ─────────────────────────────────────────────────────────────────
        """CREATE TABLE IF NOT EXISTS firewall_rules (
            id           SERIAL PRIMARY KEY,
            action       VARCHAR(10)  NOT NULL,
            protocol     VARCHAR(10)  NOT NULL DEFAULT 'tcp',
            port_range   VARCHAR(50),
            source_ip    VARCHAR(64),
            description  VARCHAR(255),
            is_whitelist BOOLEAN      NOT NULL DEFAULT FALSE,
            priority     INTEGER      NOT NULL DEFAULT 100,
            is_active    BOOLEAN      NOT NULL DEFAULT TRUE,
            created_by   INTEGER      REFERENCES users(id) ON DELETE SET NULL,
            created_at   TIMESTAMP    NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMP    DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_firewall_rules_priority ON firewall_rules(priority)",
        """CREATE TABLE IF NOT EXISTS banned_ips (
            id          SERIAL PRIMARY KEY,
            ip          VARCHAR(45)  NOT NULL,
            banned_by   VARCHAR(20)  NOT NULL,
            jail_name   VARCHAR(64),
            reason      VARCHAR(255),
            banned_at   TIMESTAMP    NOT NULL DEFAULT NOW(),
            expires_at  TIMESTAMP,
            unbanned_at TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS ix_banned_ips_ip       ON banned_ips(ip)",
        "CREATE INDEX IF NOT EXISTS ix_banned_ips_active   ON banned_ips(unbanned_at) WHERE unbanned_at IS NULL",
        """CREATE TABLE IF NOT EXISTS ip_lists (
            id                      SERIAL PRIMARY KEY,
            name                    VARCHAR(64)  UNIQUE NOT NULL,
            description             VARCHAR(255),
            url                     VARCHAR(2048) NOT NULL,
            action                  VARCHAR(10)  NOT NULL DEFAULT 'block',
            address_family          VARCHAR(10)  NOT NULL DEFAULT 'both',
            refresh_interval_hours  INTEGER      NOT NULL DEFAULT 24,
            max_entries             INTEGER      NOT NULL DEFAULT 500000,
            enabled                 BOOLEAN      NOT NULL DEFAULT TRUE,
            last_fetched_at         TIMESTAMP,
            last_success_at         TIMESTAMP,
            last_error              TEXT,
            sha256_last             VARCHAR(64),
            entry_count_v4          INTEGER      DEFAULT 0,
            entry_count_v6          INTEGER      DEFAULT 0,
            created_by              INTEGER      REFERENCES users(id) ON DELETE SET NULL,
            created_at              TIMESTAMP    NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMP    DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS security_audit_log (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER  REFERENCES users(id) ON DELETE SET NULL,
            user_label  VARCHAR(64),
            category    VARCHAR(20)  NOT NULL,
            action      VARCHAR(40)  NOT NULL,
            target      VARCHAR(255),
            before      TEXT,
            after       TEXT,
            ip_origin   VARCHAR(45),
            success     BOOLEAN      NOT NULL DEFAULT TRUE,
            error       TEXT,
            created_at  TIMESTAMP    NOT NULL DEFAULT NOW()
        )""",
        # Fase 11: límites de upload en settings
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS max_upload_mb INTEGER DEFAULT 100",
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS max_text_file_mb INTEGER DEFAULT 2",
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS max_extract_mb INTEGER DEFAULT 500",
        "CREATE INDEX IF NOT EXISTS ix_security_audit_user_id            ON security_audit_log(user_id)",
        "CREATE INDEX IF NOT EXISTS ix_security_audit_category           ON security_audit_log(category)",
        "CREATE INDEX IF NOT EXISTS ix_security_audit_created_at         ON security_audit_log(created_at)",
        "CREATE INDEX IF NOT EXISTS ix_security_audit_category_created   ON security_audit_log(category, created_at DESC)",
        # ─────────────────────────────────────────────────────────────────
        # Fase 13: Planes (plantillas de límites) — snapshot a usuarios
        # ─────────────────────────────────────────────────────────────────
        """CREATE TABLE IF NOT EXISTS plans (
            id                      SERIAL PRIMARY KEY,
            name                    VARCHAR(64)  NOT NULL,
            description             VARCHAR(255),
            owner_id                INTEGER      REFERENCES users(id) ON DELETE CASCADE,
            disk_quota_mb           INTEGER      NOT NULL DEFAULT 1024,
            traffic_quota_mb_month  INTEGER      NOT NULL DEFAULT 10240,
            domains_limit           INTEGER      NOT NULL DEFAULT 5,
            databases_limit         INTEGER      NOT NULL DEFAULT 5,
            mailboxes_limit         INTEGER      NOT NULL DEFAULT 10,
            dns_zones_limit         INTEGER      NOT NULL DEFAULT 10,
            is_default              BOOLEAN      NOT NULL DEFAULT FALSE,
            created_at              TIMESTAMP    NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMP    DEFAULT NOW(),
            CONSTRAINT uq_plans_owner_name UNIQUE (owner_id, name)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_plans_owner_id ON plans(owner_id)",
        # Solo 1 plan default por owner (índice parcial donde is_default=TRUE)
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_plans_default_per_owner ON plans(COALESCE(owner_id, 0)) WHERE is_default = TRUE",
        # Campos en users que el plan rellena al asignarlo (snapshot)
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS plan_id INTEGER REFERENCES plans(id) ON DELETE SET NULL",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS plan_name VARCHAR(64)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS disk_quota_mb INTEGER DEFAULT 1024",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS traffic_quota_mb_month INTEGER DEFAULT 10240",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS mailboxes_limit INTEGER DEFAULT 10",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS dns_zones_limit INTEGER DEFAULT 10",
        # Stats que el cron va actualizando (Fase 13.2)
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS disk_used_mb INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS traffic_used_mb_month INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS stats_updated_at TIMESTAMP",
        # ─────────────────────────────────────────────────────────────────
        # Fase 14: FastCGI cache por dominio (nginx)
        # ─────────────────────────────────────────────────────────────────
        "ALTER TABLE domains ADD COLUMN IF NOT EXISTS fastcgi_cache_enabled BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE domains ADD COLUMN IF NOT EXISTS fastcgi_cache_ttl_minutes INTEGER NOT NULL DEFAULT 60",
        # ─────────────────────────────────────────────────────────────────
        # Fase 14.2: SFTP por usuario (chroot, password, SSH keys)
        # ─────────────────────────────────────────────────────────────────
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS sftp_enabled BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS sftp_password_set_at TIMESTAMP",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS ssh_keys_count INTEGER NOT NULL DEFAULT 0",
        # ─────────────────────────────────────────────────────────────────
        # Fase 14.3: php.ini por dominio (pool FPM dedicado)
        # ─────────────────────────────────────────────────────────────────
        "ALTER TABLE domains ADD COLUMN IF NOT EXISTS php_ini_overrides TEXT",
        # ─────────────────────────────────────────────────────────────────
        # Fase 14.4: cuentas SFTP adicionales (subcuentas con jaula bind-mount)
        # ─────────────────────────────────────────────────────────────────
        """CREATE TABLE IF NOT EXISTS sftp_accounts (
            id              SERIAL PRIMARY KEY,
            owner_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            username        VARCHAR(64)  UNIQUE NOT NULL,
            label           VARCHAR(32)  NOT NULL,
            target_path     VARCHAR(512) NOT NULL,
            jail_path       VARCHAR(512) NOT NULL,
            mount_name      VARCHAR(64)  NOT NULL,
            password_set_at TIMESTAMP,
            ssh_keys_count  INTEGER      NOT NULL DEFAULT 0,
            created_at      TIMESTAMP    NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_sftp_accounts_owner_id ON sftp_accounts(owner_id)",
        # ─────────────────────────────────────────────────────────────────
        # SSL del propio panel (hostname + certificado)
        # ─────────────────────────────────────────────────────────────────
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS panel_hostname VARCHAR(255)",
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS ssl_panel_enabled BOOLEAN DEFAULT FALSE",
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS ssl_panel_expires TIMESTAMP",
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS force_https BOOLEAN DEFAULT FALSE",
        # 2FA
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret VARCHAR(64)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled BOOLEAN DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled_at TIMESTAMP",
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
app.include_router(mail.router,      prefix="/api", tags=["Mail"])
app.include_router(databases.router, prefix="/api", tags=["Databases"])
app.include_router(firewall.router,         prefix="/api", tags=["Firewall"])
app.include_router(fail2ban.router,         prefix="/api", tags=["Fail2ban"])
app.include_router(security_monitor.router, prefix="/api", tags=["Security Monitor"])
app.include_router(ip_lists.router,         prefix="/api", tags=["IP Lists"])
app.include_router(crowdsec.router,         prefix="/api", tags=["CrowdSec"])
app.include_router(plans.router,            prefix="/api", tags=["Plans"])
app.include_router(sftp.router,             prefix="/api", tags=["SFTP"])
app.include_router(file_manager.router,     prefix="/api", tags=["File Manager"])
# Autoconfig/Autodiscover sin prefijo (clientes de correo los buscan en rutas raíz)
app.include_router(mail.router, prefix="", include_in_schema=False)

# Manejo de errores HTTP 413 (Payload Too Large)
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    if exc.status_code == 413:
        return JSONResponse(
            status_code=413,
            content={
                "status": "error",
                "message": exc.detail or "El archivo es demasiado grande",
                "code": "PAYLOAD_TOO_LARGE"
            }
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": exc.detail or "Error en la solicitud"}
    )

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
