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
    is_active = Column(Boolean, default=True)
    
    # Estadísticas
    disk_usage = Column(Integer, default=0)  # MB
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    ssl_renewed_at = Column(DateTime, nullable=True)
    
    # Relaciones
    user      = relationship("User",           back_populates="domains")
    databases = relationship("ClientDatabase", back_populates="domain", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Domain {self.domain_name}>"
