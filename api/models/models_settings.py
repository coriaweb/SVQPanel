"""
Modelo de configuración del panel (tabla singleton — siempre un único registro)
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from datetime import datetime
from api.models.database import Base



class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, default=1)

    # Panel
    panel_name = Column(String(255), default="SVQPanel")
    panel_version = Column(String(50), default="0.1.0")

    # Red - IPv4
    server_ipv4 = Column(String(45), nullable=True)          # IP pública del servidor

    # Red - IPv6
    ipv6_enabled = Column(Boolean, default=False)             # IPv6 activado
    ipv6_range = Column(String(50), nullable=True)            # Rango /64, ej: 2a01:4f8:1:2::/64
    ipv6_gateway = Column(String(50), nullable=True)          # Gateway IPv6 (opcional)
    network_interface = Column(String(20), default="eth0")    # Interfaz de red (eth0, ens3…)

    # PHP
    php_default_version = Column(String(10), default="8.2")

    # File Manager - Límites de subida
    max_upload_mb = Column(Integer, default=100)              # MB máximo por archivo
    max_text_file_mb = Column(Integer, default=2)             # MB máximo para editar en el panel
    max_extract_mb = Column(Integer, default=500)             # MB máximo para extraer ZIPs

    # SSL del propio panel
    panel_hostname = Column(String(255), nullable=True)       # Hostname del panel (ej: panel.midominio.com)
    ssl_panel_enabled = Column(Boolean, default=False)        # SSL emitido y activo para el panel
    ssl_panel_expires = Column(DateTime, nullable=True)       # Fecha de expiración del cert
    force_https = Column(Boolean, default=False)              # Redirigir HTTP → HTTPS del panel

    # Timestamps
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Settings panel={self.panel_name} ipv6={self.ipv6_range}>"
