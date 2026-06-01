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

from api.routes import users, domains, php, ssl, ipv6, auth, settings, dns, system, mail, databases, firewall, fail2ban, security_monitor, ip_lists, file_manager, crowdsec, plans, sftp, crons, server_ips, backups, templates, notifications, dns_cluster

# Crear app FastAPI
app = FastAPI(
    title=PANEL_NAME,
    description="Panel de control para servidores web",
    version=PANEL_VERSION,
)

# ── Cabeceras de seguridad HTTP en todas las respuestas del panel ──
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # Clickjacking: el panel no debe poder embeberse en iframes de terceros
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        # MIME sniffing
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        # No filtrar la URL del panel a sitios externos
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        # Desactivar APIs del navegador que el panel no usa
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=(), payment=()"
        )
        # CSP: bloquea embedding y limita orígenes. Permisivo con los CDN que
        # usa la SPA (Bootstrap Icons, fuentes) e inline styles de Vue.
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "font-src 'self' https://cdn.jsdelivr.net https://fonts.gstatic.com; "
            "script-src 'self' https://cdn.jsdelivr.net; "
            "connect-src 'self'; "
            "frame-ancestors 'self'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        return response

app.add_middleware(SecurityHeadersMiddleware)

# CORS — el panel se sirve desde su propio dominio (frontend y API en el mismo
# host vía nginx), así que no se necesitan orígenes cruzados. Restringido a los
# definidos en PANEL_CORS_ORIGINS (coma-separados); por defecto, ninguno externo.
_cors_origins = [o.strip() for o in os.getenv("PANEL_CORS_ORIGINS", "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
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
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret VARCHAR(256)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled BOOLEAN DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled_at TIMESTAMP",
        # Asegurar longitud correcta si la columna ya existía con 64 chars
        "ALTER TABLE users ALTER COLUMN totp_secret TYPE VARCHAR(256)",
        # Suspensión individual de dominio
        "ALTER TABLE domains ADD COLUMN IF NOT EXISTS is_suspended BOOLEAN DEFAULT FALSE",
        # Cron jobs de clientes
        """CREATE TABLE IF NOT EXISTS cron_jobs (
            id         SERIAL PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            domain_id  INTEGER REFERENCES domains(id) ON DELETE SET NULL,
            minute     VARCHAR(20) NOT NULL DEFAULT '*',
            hour       VARCHAR(20) NOT NULL DEFAULT '*',
            day        VARCHAR(20) NOT NULL DEFAULT '*',
            month      VARCHAR(20) NOT NULL DEFAULT '*',
            weekday    VARCHAR(20) NOT NULL DEFAULT '*',
            command    TEXT NOT NULL,
            comment    VARCHAR(255),
            is_active  BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            last_run   TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS ix_cron_jobs_user_id ON cron_jobs(user_id)",
        "CREATE INDEX IF NOT EXISTS ix_cron_jobs_domain_id ON cron_jobs(domain_id)",
        # ─────────────────────────────────────────────────────────────────
        # IPs del servidor (gestión de red)
        # ─────────────────────────────────────────────────────────────────
        """CREATE TABLE IF NOT EXISTS server_ips (
            id            SERIAL PRIMARY KEY,
            address       VARCHAR(45)  UNIQUE NOT NULL,
            netmask       VARCHAR(48),
            interface     VARCHAR(20)  NOT NULL DEFAULT 'eth0',
            ip_type       VARCHAR(20)  NOT NULL DEFAULT 'shared',
            is_ipv6       BOOLEAN      NOT NULL DEFAULT FALSE,
            nat_ip        VARCHAR(45),
            owner_user_id INTEGER      REFERENCES users(id) ON DELETE SET NULL,
            is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
            note          VARCHAR(255),
            created_at    TIMESTAMP    NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMP    DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_server_ips_ip_type ON server_ips(ip_type)",
        # Timezone en settings
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS timezone VARCHAR(64) DEFAULT 'UTC'",
        # ─────────────────────────────────────────────────────────────────
        # Fase 15: Sistema de backups (jobs + historial de ejecuciones)
        # ─────────────────────────────────────────────────────────────────
        """CREATE TABLE IF NOT EXISTS backup_jobs (
            id                SERIAL PRIMARY KEY,
            user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            domain_id         INTEGER REFERENCES domains(id) ON DELETE SET NULL,
            name              VARCHAR(100) NOT NULL,
            description       VARCHAR(255),
            include_files     BOOLEAN NOT NULL DEFAULT TRUE,
            include_databases BOOLEAN NOT NULL DEFAULT TRUE,
            include_mail      BOOLEAN NOT NULL DEFAULT FALSE,
            backup_type       VARCHAR(20)  NOT NULL DEFAULT 'incremental',
            destination_type  VARCHAR(10)  NOT NULL DEFAULT 'local',
            local_path        VARCHAR(512) NOT NULL DEFAULT '/backups',
            sftp_host         VARCHAR(255),
            sftp_port         INTEGER DEFAULT 22,
            sftp_user         VARCHAR(64),
            sftp_password     VARCHAR(500),
            sftp_path         VARCHAR(512),
            sftp_key_path     VARCHAR(512),
            retention_copies  INTEGER NOT NULL DEFAULT 7,
            is_active         BOOLEAN NOT NULL DEFAULT TRUE,
            created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMP DEFAULT NOW(),
            last_run          TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS ix_backup_jobs_user_id   ON backup_jobs(user_id)",
        "CREATE INDEX IF NOT EXISTS ix_backup_jobs_domain_id ON backup_jobs(domain_id)",
        """CREATE TABLE IF NOT EXISTS backup_records (
            id                SERIAL PRIMARY KEY,
            job_id            INTEGER NOT NULL REFERENCES backup_jobs(id) ON DELETE CASCADE,
            user_id           INTEGER REFERENCES users(id) ON DELETE SET NULL,
            status            VARCHAR(20) NOT NULL DEFAULT 'pending',
            is_incremental    BOOLEAN NOT NULL DEFAULT FALSE,
            backup_path       VARCHAR(1024),
            size_bytes        BIGINT DEFAULT 0,
            files_transferred INTEGER DEFAULT 0,
            files_total       INTEGER DEFAULT 0,
            db_count          INTEGER DEFAULT 0,
            log_output        TEXT,
            error_message     TEXT,
            started_at        TIMESTAMP NOT NULL DEFAULT NOW(),
            finished_at       TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS ix_backup_records_job_id  ON backup_records(job_id)",
        "CREATE INDEX IF NOT EXISTS ix_backup_records_user_id ON backup_records(user_id)",
        # Fase 15.1: restauración — distinguir copia de restauración
        "ALTER TABLE backup_records ADD COLUMN IF NOT EXISTS kind VARCHAR(20) NOT NULL DEFAULT 'backup'",
        # ─────────────────────────────────────────────────────────────────
        # Fase 15.2: Plantillas web (nginx + PHP-FPM presets)
        # ─────────────────────────────────────────────────────────────────
        """CREATE TABLE IF NOT EXISTS web_templates (
            id                    SERIAL PRIMARY KEY,
            name                  VARCHAR(64)  UNIQUE NOT NULL,
            slug                  VARCHAR(64)  UNIQUE NOT NULL,
            description           VARCHAR(255),
            category              VARCHAR(32)  NOT NULL DEFAULT 'cms',
            nginx_extra           TEXT,
            php_ini_overrides     TEXT,
            fastcgi_cache_default BOOLEAN NOT NULL DEFAULT FALSE,
            is_builtin            BOOLEAN NOT NULL DEFAULT FALSE,
            is_active             BOOLEAN NOT NULL DEFAULT TRUE,
            created_at            TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMP DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_web_templates_slug ON web_templates(slug)",
        # Campos en domains para registrar la plantilla aplicada
        "ALTER TABLE domains ADD COLUMN IF NOT EXISTS applied_template_id INTEGER REFERENCES web_templates(id) ON DELETE SET NULL",
        "ALTER TABLE domains ADD COLUMN IF NOT EXISTS applied_template_name VARCHAR(64)",
        "ALTER TABLE domains ADD COLUMN IF NOT EXISTS template_nginx_extra TEXT",
        # Redirección 301 y docroot personalizado (Fase 16)
        "ALTER TABLE domains ADD COLUMN IF NOT EXISTS redirect_to VARCHAR(512)",
        "ALTER TABLE domains ADD COLUMN IF NOT EXISTS custom_docroot VARCHAR(512)",
        # SSL avanzado (force_https, HSTS)
        "ALTER TABLE domains ADD COLUMN IF NOT EXISTS force_https BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE domains ADD COLUMN IF NOT EXISTS hsts_enabled BOOLEAN NOT NULL DEFAULT FALSE",
        # Rate limiting anti-abuso (Fase 19)
        "ALTER TABLE domains ADD COLUMN IF NOT EXISTS rate_limit_enabled BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE domains ADD COLUMN IF NOT EXISTS rate_limit_rps INTEGER NOT NULL DEFAULT 10",
        "ALTER TABLE domains ADD COLUMN IF NOT EXISTS rate_limit_burst INTEGER NOT NULL DEFAULT 20",
        # Hardening PHP relajado por dominio (Fase 20)
        "ALTER TABLE domains ADD COLUMN IF NOT EXISTS php_hardening_relaxed BOOLEAN NOT NULL DEFAULT FALSE",
        # ─────────────────────────────────────────────────────────────────
        # Fase 18: Notificaciones (avisos de cuota disco/tráfico al usuario)
        # ─────────────────────────────────────────────────────────────────
        """CREATE TABLE IF NOT EXISTS notifications (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            level       VARCHAR(16)  NOT NULL DEFAULT 'info',
            title       VARCHAR(128) NOT NULL,
            message     TEXT         NOT NULL,
            dedup_key   VARCHAR(64),
            is_read     BOOLEAN      NOT NULL DEFAULT FALSE,
            created_at  TIMESTAMP    NOT NULL DEFAULT NOW(),
            read_at     TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS ix_notifications_user_id   ON notifications(user_id)",
        "CREATE INDEX IF NOT EXISTS ix_notifications_is_read   ON notifications(is_read)",
        "CREATE INDEX IF NOT EXISTS ix_notifications_dedup     ON notifications(user_id, dedup_key, is_read)",
        # Autoinstalador: subcarpeta docroot por plantilla (ej. 'public' Laravel)
        "ALTER TABLE web_templates ADD COLUMN IF NOT EXISTS docroot_subdir VARCHAR(64)",
        # ─────────────────────────────────────────────────────────────────
        # Fase 21: Cluster DNS (master/slave). Sin nodos => panel sirve DNS.
        # ─────────────────────────────────────────────────────────────────
        """CREATE TABLE IF NOT EXISTS dns_nodes (
            id              SERIAL PRIMARY KEY,
            role            VARCHAR(10)  NOT NULL,
            hostname        VARCHAR(255) NOT NULL,
            ip              VARCHAR(45)  NOT NULL,
            ssh_user        VARCHAR(64)  DEFAULT 'root',
            ssh_port        INTEGER      DEFAULT 22,
            ssh_key_path    VARCHAR(255),
            status          VARCHAR(16)  NOT NULL DEFAULT 'pending',
            tsig_configured BOOLEAN      NOT NULL DEFAULT FALSE,
            last_sync_at    TIMESTAMP,
            last_error      TEXT,
            created_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMP    DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_dns_nodes_role ON dns_nodes(role)",
        # Clave TSIG compartida del cluster (se guarda en settings, singleton)
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS dns_tsig_name VARCHAR(64)",
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS dns_tsig_secret VARCHAR(128)",
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS dns_tsig_algo VARCHAR(32) DEFAULT 'hmac-sha256'",
        # Salud del cluster DNS (la escribe el timer dns-cluster-health)
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS dns_cluster_health_json TEXT",
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS dns_cluster_health_at TIMESTAMP",
        # Fase A: nameservers propios del panel
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS dns_ns1 VARCHAR(255)",
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS dns_ns2 VARCHAR(255)",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception as e:
                print(f"⚠ Migration skipped: {e}")

    # Sembrar plantillas builtin si la tabla está vacía
    _seed_builtin_templates(engine)

def _seed_builtin_templates(engine):
    """Inserta las plantillas builtin si no existen aún."""
    from scripts.template_manager import BUILTIN_TEMPLATES
    from api.models.database import SessionLocal
    db = SessionLocal()
    try:
        from api.models.models_template import WebTemplate
        for tpl in BUILTIN_TEMPLATES:
            exists = db.query(WebTemplate).filter(WebTemplate.slug == tpl["slug"]).first()
            if not exists:
                obj = WebTemplate(
                    name=tpl["name"],
                    slug=tpl["slug"],
                    description=tpl.get("description"),
                    category=tpl.get("category", "cms"),
                    nginx_extra=tpl.get("nginx_extra"),
                    php_ini_overrides=tpl.get("php_ini_overrides"),
                    fastcgi_cache_default=tpl.get("fastcgi_cache_default", False),
                    docroot_subdir=tpl.get("docroot_subdir"),
                    is_builtin=True,
                    is_active=True,
                )
                db.add(obj)
            elif exists.is_builtin:
                # Refrescar plantillas builtin ya sembradas (correcciones de
                # nginx_extra, docroot_subdir, etc.). No tocamos las del usuario.
                exists.nginx_extra = tpl.get("nginx_extra")
                exists.php_ini_overrides = tpl.get("php_ini_overrides")
                exists.fastcgi_cache_default = tpl.get("fastcgi_cache_default", False)
                exists.docroot_subdir = tpl.get("docroot_subdir")
        db.commit()
        print(f"✓ Plantillas web: {len(BUILTIN_TEMPLATES)} builtin registradas")
    except Exception as e:
        db.rollback()
        print(f"⚠ Error sembrando plantillas: {e}")
    finally:
        db.close()


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
app.include_router(dns_cluster.router, prefix="/api", tags=["DNS Cluster"])
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
app.include_router(crons.router,            prefix="/api", tags=["Crons"])
app.include_router(server_ips.router,       prefix="/api", tags=["Server IPs"])
app.include_router(backups.router,          prefix="/api", tags=["Backups"])
app.include_router(templates.router,        prefix="/api", tags=["Templates"])
app.include_router(file_manager.router,     prefix="/api", tags=["File Manager"])
app.include_router(notifications.router,     prefix="/api", tags=["Notifications"])
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
