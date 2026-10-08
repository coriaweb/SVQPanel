"""
Consumo de CPU y RAM por dominio (su pool PHP-FPM dedicado).

Una fila por dominio y bucket de 5 minutos, solo si el dominio tuvo actividad
(sin filas = 0; la API rellena los huecos). Retención 30 días. Lo escribe el
muestreador de scripts/domain_resources.py (hilo de fondo del panel).
"""
from datetime import datetime

from sqlalchemy import Column, BigInteger, Integer, Float, DateTime, ForeignKey, Index

from api.models.database import Base


class DomainResourceSample(Base):
    __tablename__ = "domain_resource_samples"

    # BIGSERIAL en PostgreSQL; en SQLite (tests) solo INTEGER autoincrementa
    id          = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    domain_id   = Column(Integer, ForeignKey("domains.id", ondelete="CASCADE"), nullable=False)
    ts          = Column(DateTime, default=datetime.utcnow, nullable=False)  # inicio del bucket (UTC)
    cpu_seconds = Column(Float, default=0.0)     # tiempo de CPU (user+sys) gastado en el bucket
    mem_avg_mb  = Column(Float, default=0.0)     # PSS media del pool en el bucket
    mem_max_mb  = Column(Float, default=0.0)     # PSS máxima vista en el bucket
    procs_max   = Column(Integer, default=0)     # procesos PHP simultáneos (máximo)
    maxchildren_hits = Column(Integer, default=0)  # veces que el pool llegó a pm.max_children

    __table_args__ = (Index("ix_domain_resource_samples_domain_ts", "domain_id", "ts"),
                      Index("ix_domain_resource_samples_ts", "ts"))
