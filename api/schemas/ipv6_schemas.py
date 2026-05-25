"""
Esquemas Pydantic para IPv6
"""

from pydantic import BaseModel, field_validator
from typing import Optional
import ipaddress


class IPv6Assign(BaseModel):
    ipv6_address: str
    network_interface: Optional[str] = "eth0"

    @field_validator("ipv6_address")
    @classmethod
    def validate_ipv6(cls, v):
        try:
            return str(ipaddress.IPv6Address(v))
        except ipaddress.AddressValueError:
            raise ValueError(f"Dirección IPv6 inválida: {v}")


class IPv6Response(BaseModel):
    domain_id: int
    ipv6_address: Optional[str] = None
    network_interface: Optional[str] = None
    is_active: bool = True

    class Config:
        from_attributes = True
