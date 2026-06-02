"""
Modelo del historial de despliegues Git por dominio.

Cada fila es un deploy (clonado inicial, pull manual o webhook). La config del
repositorio vive en el propio modelo Domain (git_* columns); aquí solo el log.
La clave privada del deploy key NO se almacena en BD: vive en
/home/{user}/.ssh/svqpanel_git_{domain} (0600). En Domain solo la pública.
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from api.models.database import Base


class GitDeployment(Base):
    """Un despliegue Git de un dominio (auditable y base del rollback)."""
    __tablename__ = "git_deployments"

    id          = Column(Integer, primary_key=True, index=True)
    domain_id   = Column(Integer, ForeignKey("domains.id", ondelete="CASCADE"),
                         nullable=False, index=True)

    commit_sha  = Column(String(64), nullable=True)
    commit_msg  = Column(String(500), nullable=True)
    branch      = Column(String(255), nullable=True)
    ref         = Column(String(255), nullable=True)
    release_dir = Column(String(512), nullable=True)   # carpeta releases/{ts}-{sha}

    # success | failed | running
    status      = Column(String(20), default="running", nullable=False)
    # initial | manual | webhook | rollback
    trigger     = Column(String(20), default="manual", nullable=False)
    build_log   = Column(Text, nullable=True)

    created_at  = Column(DateTime, default=datetime.utcnow, index=True)

    domain = relationship("Domain", back_populates="git_deployments")

    def __repr__(self):
        return f"<GitDeployment d={self.domain_id} {self.status} {self.commit_sha}>"
