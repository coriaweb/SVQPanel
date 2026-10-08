"""Dominios alias: otros nombres que llevan a la web de un dominio.

dominio.es / dominio.net → la web de dominio.com. Cada alias puede:
  - redirect=True  (por defecto, lo habitual): 301 al dominio principal, con la
    ruta. Bueno para SEO (una sola URL buena, sin contenido duplicado).
  - redirect=False: sirve la misma web con su propio nombre (server_name extra).
El alias y su www. entran en el certificado del dominio si resuelven aquí.
"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey

from api.models.database import Base


class DomainAlias(Base):
    __tablename__ = "domain_aliases"

    id = Column(Integer, primary_key=True, index=True)
    domain_id = Column(Integer, ForeignKey("domains.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    alias_name = Column(String(255), unique=True, nullable=False, index=True)
    redirect = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
