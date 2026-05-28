"""
Modelo SQLAlchemy para plantillas web de dominios.

Una WebTemplate encapsula:
  - Nombre / slug / descripción
  - Snippet extra de nginx (bloques location, headers, etc.)
  - Overrides de PHP ini (JSON) que se aplican al pool del dominio
  - Si la caché FastCGI debe activarse por defecto al aplicar la plantilla

Las plantillas "builtin" se crean en la migración y no pueden borrarse.
Los admins pueden crear plantillas propias (is_builtin = False).
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from api.models.database import Base


class WebTemplate(Base):
    __tablename__ = "web_templates"

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String(64),  unique=True, nullable=False)
    slug        = Column(String(64),  unique=True, nullable=False, index=True)
    description = Column(String(255), nullable=True)
    category    = Column(String(32),  default="cms", nullable=False)  # cms | framework | ecommerce | other

    # Snippet nginx que se inyecta DENTRO del bloque server {} (antes del location ~ \.php$)
    # Puede incluir location blocks, add_header, etc.
    nginx_extra         = Column(Text, nullable=True)

    # Overrides de PHP ini en formato JSON  {"memory_limit":"256M","upload_max_filesize":"64M"}
    php_ini_overrides   = Column(Text, nullable=True)

    # Sugerencia: ¿activar FastCGI cache al aplicar esta plantilla?
    fastcgi_cache_default = Column(Boolean, default=False, nullable=False)

    # Las plantillas builtin no pueden eliminarse desde la API
    is_builtin  = Column(Boolean, default=False, nullable=False)
    is_active   = Column(Boolean, default=True,  nullable=False)

    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
