"""
Servidores de origen guardados para migraciones (estilo cPanel: guardas un
servidor Hestia/cPanel y "reconectas" sin rellenar todo cada vez).

La contraseña SSH (o la clave privada) se guardan CIFRADAS con Fernet, igual que
las credenciales de SMTP relay y backups S3. Nunca se devuelven en claro por la
API: solo se usan en el servidor para conectar.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime
from datetime import datetime
from api.models.database import Base


class MigrationSource(Base):
    __tablename__ = "migration_sources"

    id          = Column(Integer, primary_key=True, index=True)
    # Etiqueta para reconocerlo en la lista ("Hestia VPS cliente X").
    label       = Column(String(120), nullable=False)
    panel       = Column(String(20), default="hestia")   # hestia | cpanel
    host        = Column(String(255), nullable=False)
    ssh_user    = Column(String(64), default="root")
    ssh_port    = Column(Integer, default=22)
    # Credenciales CIFRADAS (Fernet). Una de las dos (o ambas).
    ssh_password_enc = Column(Text, nullable=True)
    ssh_key_enc      = Column(Text, nullable=True)
    # Último usuario remoto exportado (para preseleccionar; no es secreto).
    last_remote_user = Column(String(64), nullable=True)

    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<MigrationSource {self.label} {self.host}>"
