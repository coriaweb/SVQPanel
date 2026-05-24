"""
Esquemas Pydantic para IPv6
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional
import ipaddress


class IPv6Create(BaseModel):
    ipv6: str

    @field_validator("ipv6")
    @classmethod
    def validate_ipv6(cls, v):
        try:
            addr = ipaddress.IPv6Address(v)
            return str(addr)
        except ipaddress.AddressValueError:
            raise ValueError("IPv6 inválido")


class IPv6Response(BaseModel):
    domain_id: int
    ipv6: str

    class Config:
        from_attributes = True
