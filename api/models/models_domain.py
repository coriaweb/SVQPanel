from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from api.models.database import Base

class Domain(Base):
    __tablename__ = "domains"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # Dominio
    domain_name = Column(String(255), unique=True, nullable=False, index=True)
    
    # Rutas
    public_html = Column(String(255), nullable=False)  # /home/user/public_html/domain
    
    # PHP
    php_version = Column(String(10), default="8.2")  # 7.4, 8.0, 8.1, 8.2, 8.3
    
    # SSL
    ssl_enabled = Column(Boolean, default=False)
    ssl_certificate = Column(Text, nullable=True)
    ssl_key = Column(Text, nullable=True)
    ssl_expires = Column(DateTime, nullable=True)
    
    # IPv4 e IPv6
    ipv4 = Column(String(45), nullable=True)
    ipv6 = Column(String(45), nullable=True)
    
    # Estado
    is_active     = Column(Boolean, default=True)
    is_suspended  = Column(Boolean, default=False, nullable=False)  # suspendido individualmente
    
    # FastCGI cache (Fase 14)
    fastcgi_cache_enabled    = Column(Boolean, default=False, nullable=False)
    fastcgi_cache_ttl_minutes = Column(Integer, default=60, nullable=False)

    # php.ini overrides por dominio (JSON: {"memory_limit":"256M",...}) — Fase 14.3
    php_ini_overrides = Column(Text, nullable=True)

    # Plantilla web aplicada (Fase 15)
    applied_template_id   = Column(Integer, ForeignKey("web_templates.id", ondelete="SET NULL"), nullable=True)
    applied_template_name = Column(String(64), nullable=True)
    template_nginx_extra  = Column(Text, nullable=True)

    # Redirección 301 y docroot personalizado (Fase 16)
    redirect_to    = Column(String(512), nullable=True)   # ej: https://otro.com
    custom_docroot = Column(String(512), nullable=True)   # ej: /home/user/web/domain/app/public

    # SSL avanzado
    force_https  = Column(Boolean, default=False, nullable=False)
    hsts_enabled = Column(Boolean, default=False, nullable=False)

    # Rate limiting anti-abuso (Fase 19) — off por defecto
    rate_limit_enabled = Column(Boolean, default=False, nullable=False)
    rate_limit_rps     = Column(Integer, default=10, nullable=False)
    rate_limit_burst   = Column(Integer, default=20, nullable=False)

    # Hardening PHP relajado (Fase 20): si True este dominio permite
    # exec/system/etc. open_basedir y el resto del hardening se mantienen.
    php_hardening_relaxed = Column(Boolean, default=False, nullable=False)

    # Modo solo-lectura HTTP: bloquea POST/PUT/DELETE/PATCH excepto desde las
    # IPs indicadas. Útil para contener un CMS comprometido o proteger APIs.
    # allowed_mutation_ips: JSON array de IPs/CIDRs, ej: ["1.2.3.4","10.0.0.0/8"]
    readonly_mode_enabled  = Column(Boolean, default=False, nullable=False)
    allowed_mutation_ips   = Column(Text, nullable=True)  # JSON array, NULL = nadie

    # Despliegue Git (Fase 21) — repo desplegado en public_html (symlink a
    # releases/). La clave privada del deploy key NO va en BD (vive en ~/.ssh).
    git_enabled        = Column(Boolean, default=False, nullable=False)
    git_repo_url       = Column(String(512), nullable=True)
    git_branch         = Column(String(255), default="main", nullable=True)
    git_provider       = Column(String(20), default="github", nullable=True)  # github|gitlab|generic
    git_webhook_token  = Column(String(64), nullable=True, index=True)  # secreto del webhook
    git_build_commands = Column(Text, nullable=True)  # uno por línea, ejecutados como el usuario
    git_deploy_key_pub = Column(Text, nullable=True)  # clave pública SSH (la privada en ~/.ssh)
    git_keep_releases  = Column(Integer, default=5, nullable=False)

    # Estadísticas
    disk_usage = Column(Integer, default=0)  # MB
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    ssl_renewed_at = Column(DateTime, nullable=True)
    
    # Relaciones
    user      = relationship("User",           back_populates="domains")
    databases = relationship("ClientDatabase", back_populates="domain", cascade="all, delete-orphan")
    cron_jobs = relationship("CronJob",        back_populates="domain")
    git_deployments = relationship("GitDeployment", back_populates="domain", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Domain {self.domain_name}>"
