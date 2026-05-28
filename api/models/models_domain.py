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
    
    def __repr__(self):
        return f"<Domain {self.domain_name}>"
