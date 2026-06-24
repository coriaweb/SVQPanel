"""
Esquemas Pydantic para configuración del panel
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime
import ipaddress


from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime
import ipaddress


class SettingsUpdate(BaseModel):
    panel_name: Optional[str] = Field(None, max_length=255)
    server_ipv4: Optional[str] = Field(None, max_length=45)
    ipv6_enabled: Optional[bool] = None
    ipv6_range: Optional[str] = Field(None, max_length=50)
    ipv6_gateway: Optional[str] = Field(None, max_length=50)
    network_interface: Optional[str] = Field(None, max_length=20)
    php_default_version: Optional[str] = Field(None, pattern="^(7\\.4|8\\.[0-5])$")
    max_upload_mb: Optional[int] = Field(None, ge=1, le=2048)
    max_text_file_mb: Optional[int] = Field(None, ge=1, le=100)
    max_extract_mb: Optional[int] = Field(None, ge=1, le=5120)
    panel_hostname: Optional[str] = Field(None, max_length=255)
    force_https: Optional[bool] = None
    timezone: Optional[str] = Field(None, max_length=64)
    dns_ns1: Optional[str] = Field(None, max_length=255)
    dns_ns2: Optional[str] = Field(None, max_length=255)
    # Política de contraseñas
    pwd_min_length: Optional[int] = Field(None, ge=6, le=128)
    pwd_require_upper: Optional[bool] = None
    pwd_require_lower: Optional[bool] = None
    pwd_require_digit: Optional[bool] = None
    pwd_require_symbol: Optional[bool] = None

    @field_validator("dns_ns1", "dns_ns2")
    @classmethod
    def validate_ns(cls, v):
        if v is None or v.strip() == "":
            return None
        import re
        v = v.strip().lower().rstrip(".")
        if not re.match(r"^(?=.{1,253}$)([a-z0-9](-?[a-z0-9])*\.)+[a-z]{2,}$", v):
            raise ValueError("Nameserver no válido (usa un FQDN, ej. ns1.tudominio.com)")
        return v

    @field_validator("ipv6_range")
    @classmethod
    def validate_ipv6_range(cls, v):
        if v is None or v == "":
            return None
        try:
            network = ipaddress.IPv6Network(v, strict=False)
            if network.prefixlen > 64:
                raise ValueError("El rango debe ser /64 o mayor (ej: /48, /64)")
            return str(network)
        except ValueError as e:
            raise ValueError(f"Rango IPv6 inválido: {e}")

    @field_validator("server_ipv4")
    @classmethod
    def validate_ipv4(cls, v):
        if v is None or v == "":
            return None
        try:
            ipaddress.IPv4Address(v)
            return v
        except ValueError:
            raise ValueError("Dirección IPv4 inválida")


class SettingsResponse(BaseModel):
    id: int
    panel_name: str
    panel_version: str
    server_ipv4: Optional[str] = None
    ipv6_enabled: bool
    ipv6_range: Optional[str] = None
    ipv6_gateway: Optional[str] = None
    panel_ipv6: Optional[str] = None
    network_interface: Optional[str] = "eth0"
    php_default_version: str
    max_upload_mb: int = 100
    max_text_file_mb: int = 2
    max_extract_mb: int = 500
    panel_hostname: Optional[str] = None
    ssl_panel_enabled: bool = False
    ssl_panel_expires: Optional[datetime] = None
    force_https: bool = False
    updated_at: Optional[datetime] = None

    timezone: str = "UTC"
    dns_ns1: Optional[str] = None
    dns_ns2: Optional[str] = None

    # Política de contraseñas
    pwd_min_length: int = 12
    pwd_require_upper: bool = True
    pwd_require_lower: bool = True
    pwd_require_digit: bool = True
    pwd_require_symbol: bool = False

    # Información calculada
    ipv6_total_ips: Optional[int] = None      # IPs disponibles en el rango
    ipv6_used_ips: Optional[int] = None       # IPs ya asignadas a dominios

    class Config:
        from_attributes = True


class IssuePanelSSLRequest(BaseModel):
    hostname: str = Field(..., min_length=3, max_length=255)
    email: str = Field(..., max_length=255)
    force_https: bool = True
