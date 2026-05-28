"""
Modelo para IPs del servidor registradas en el panel (IPv4 e IPv6).
Similar al apartado "Red" de Hestia — IPs disponibles para asignar a dominios.
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from api.models.database import Base


class ServerIP(Base):
    __tablename__ = "server_ips"

    id            = Column(Integer, primary_key=True, autoincrement=True)

    # Dirección y red
    address       = Column(String(45),  unique=True, nullable=False)   # 185.104.188.71 o 2a01:db8::1
    netmask       = Column(String(48),  nullable=True)                 # 255.255.255.0  o /64
    interface     = Column(String(20),  nullable=False, default="eth0")

    # Tipo de uso
    ip_type       = Column(String(20),  nullable=False, default="shared")   # shared | dedicated
    is_ipv6       = Column(Boolean,     nullable=False, default=False)

    # NAT: si la IP interna es distinta a la pública
    nat_ip        = Column(String(45),  nullable=True)

    # Propietario (NULL = administrada por el propio admin del panel)
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    is_active     = Column(Boolean,  nullable=False, default=True)
    note          = Column(String(255), nullable=True)

    created_at    = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at    = Column(DateTime, nullable=True,  onupdate=datetime.utcnow)

    # Relaciones
    owner         = relationship("User", foreign_keys=[owner_user_id])

    def __repr__(self):
        return f"<ServerIP {self.address} ({self.ip_type})>"
