"""
Modelo de nodos del cluster DNS (master/slave).

El VPS del panel NO es un nodo: solo orquesta. Los nodos son los servidores
BIND9 que sirven DNS al mundo:
  - role="master" (ns1): recibe las zonas del panel por SSH y las sirve.
  - role="slave"  (ns2): copia las zonas del master vía AXFR + TSIG.

Mientras no haya ningún nodo configurado, el panel sirve DNS él mismo (BIND
local), comportamiento por defecto. En cuanto se aprovisiona un master, el
panel empuja las zonas a ese master.
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from datetime import datetime
from api.models.database import Base


class DnsNode(Base):
    __tablename__ = "dns_nodes"

    id           = Column(Integer, primary_key=True, index=True)
    role         = Column(String(10), nullable=False)            # "master" | "slave"
    hostname     = Column(String(255), nullable=False)           # ns1.tudominio.com
    ip           = Column(String(45), nullable=False)            # IP pública (la usan AXFR/notify)

    # Acceso SSH desde el panel para aprovisionar/empujar zonas
    ssh_user     = Column(String(64), default="root")
    ssh_port     = Column(Integer, default=22)
    ssh_key_path = Column(String(255), nullable=True)            # ruta a clave privada (opcional)

    # Estado de aprovisionamiento / replicación
    status          = Column(String(16), default="pending")      # pending|ok|error
    tsig_configured = Column(Boolean, default=False)             # la clave TSIG ya está en el nodo
    last_sync_at    = Column(DateTime, nullable=True)
    last_error      = Column(Text, nullable=True)

    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<DnsNode {self.role} {self.hostname} ({self.ip}) status={self.status}>"
