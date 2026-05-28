"""
SftpAccount — cuentas SFTP adicionales (subcuentas) de un cliente.

Cada subcuenta es un usuario Linux real, enjaulado de forma estricta
(bind-mount) a una carpeta concreta dentro del espacio del cliente.
El acceso de escritura se concede con ACLs para no alterar la propiedad
owner:www-data que usan nginx y PHP-FPM.
"""

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from api.models.database import Base


class SftpAccount(Base):
    __tablename__ = "sftp_accounts"

    id        = Column(Integer, primary_key=True, index=True)
    owner_id  = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)

    username    = Column(String(64), unique=True, nullable=False)  # usuario Linux
    label       = Column(String(32), nullable=False)               # nombre amigable
    target_path = Column(String(512), nullable=False)              # carpeta destino (abs)
    jail_path   = Column(String(512), nullable=False)              # dir del chroot (abs)
    mount_name  = Column(String(64),  nullable=False)              # subdir dentro de la jaula

    password_set_at = Column(DateTime, nullable=True)
    ssh_keys_count  = Column(Integer, default=0, nullable=False)
    created_at      = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", foreign_keys=[owner_id])

    def __repr__(self):
        return f"<SftpAccount {self.username} → {self.target_path}>"
