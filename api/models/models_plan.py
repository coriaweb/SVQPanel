"""
Plan model — plantillas de límites que el admin o un reseller crean y
asignan a sus usuarios. Snapshot pattern: al asignar, los valores se
COPIAN al usuario; editar el plan después NO propaga a usuarios ya
asignados.

owner_id:
  - NULL    → plan global, creado y editable solo por admins
  - <user>  → plan de un reseller, solo él y los admins lo ven/editan
"""

from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import relationship
from datetime import datetime

from api.models.database import Base


class Plan(Base):
    __tablename__ = "plans"

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String(64),  nullable=False)
    description = Column(String(255), nullable=True)

    # Propietario: NULL = plan global (admins), otro = plan de un reseller
    owner_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )

    # Límites — coinciden con los campos del User
    disk_quota_mb           = Column(Integer, default=1024)   # 0 = ilimitado
    traffic_quota_mb_month  = Column(Integer, default=10240)  # 0 = ilimitado
    domains_limit           = Column(Integer, default=5)      # 0 = ilimitado
    databases_limit         = Column(Integer, default=5)
    mailboxes_limit         = Column(Integer, default=10)
    dns_zones_limit         = Column(Integer, default=10)

    # Si true, al crear un usuario nuevo bajo este owner sin plan explícito,
    # se aplica este. Solo puede haber 1 default por owner (UNIQUE parcial).
    is_default = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    owner = relationship("User", foreign_keys=[owner_id])

    __table_args__ = (
        # Nombre único por owner (un reseller puede tener "Básico" y el admin
        # también puede tener "Básico" global; no chocan).
        UniqueConstraint("owner_id", "name", name="uq_plans_owner_name"),
    )

    def __repr__(self):
        scope = "global" if self.owner_id is None else f"owner={self.owner_id}"
        return f"<Plan {self.name} ({scope})>"

    def snapshot(self) -> dict:
        """Devuelve los campos que se copian al asignar el plan a un usuario."""
        return {
            "disk_quota_mb":          self.disk_quota_mb,
            "traffic_quota_mb_month": self.traffic_quota_mb_month,
            "domains_limit":          self.domains_limit,
            "databases_limit":        self.databases_limit,
            "mailboxes_limit":        self.mailboxes_limit,
            "dns_zones_limit":        self.dns_zones_limit,
            "plan_id":                self.id,
            "plan_name":              self.name,
        }
