"""
Modelos DNS — zonas y registros (BIND9)
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, ForeignKey, Text
from datetime import datetime
from api.models.database import Base


class DnsZone(Base):
    __tablename__ = "dns_zones"

    id            = Column(Integer, primary_key=True, index=True)
    domain_name   = Column(String(255), unique=True, nullable=False, index=True)
    serial        = Column(Integer, default=2026052501)   # YYYYMMDDNN
    is_active     = Column(Boolean, default=True)

    # Configuración de la zona (estilo Hestia)
    ip_address    = Column(String(45), nullable=True)             # IP del servidor para registros A
    soa_ns        = Column(String(255), default="ns1.svqpanel.local")  # Nameserver SOA
    ttl           = Column(Integer, default=14400)                # $TTL global de la zona
    template      = Column(String(50), default="default")        # Plantilla DNS usada
    dnssec_enabled = Column(Boolean, default=False)               # DNSSEC activo
    expires_at    = Column(Date, nullable=True)                   # Fecha expiración dominio

    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<DnsZone {self.domain_name}>"


class DnsRecord(Base):
    __tablename__ = "dns_records"

    id          = Column(Integer, primary_key=True, index=True)
    zone_id     = Column(Integer, ForeignKey("dns_zones.id", ondelete="CASCADE"), nullable=False)
    record_type = Column(String(10), nullable=False)   # A AAAA CNAME MX TXT NS SRV CAA
    name        = Column(String(255), nullable=False)  # @ o subdominio
    content     = Column(Text, nullable=False)         # IP, hostname, texto…
    ttl         = Column(Integer, default=14400)
    priority    = Column(Integer, default=0)           # para MX y SRV

    def __repr__(self):
        return f"<DnsRecord {self.record_type} {self.name} → {self.content}>"
