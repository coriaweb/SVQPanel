"""
Esquemas Pydantic para gestión de IPs del servidor
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal
from datetime import datetime
import ipaddress
import re


def _validate_address(v: str) -> str:
    v = v.strip()
    try:
        ipaddress.IPv4Address(v)
        return v
    except ValueError:
        pass
    try:
        ipaddress.IPv6Address(v)
        return v
    except ValueError:
        raise ValueError(f"Dirección IP inválida: {v!r}")


def _validate_netmask(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    v = v.strip()
    # Acepta /24, /64 o 255.255.255.0
    if re.match(r'^/?\d{1,3}$', v):
        bits = int(v.lstrip('/'))
        if 0 <= bits <= 128:
            return f"/{bits}" if not v.startswith('/') else v
    try:
        ipaddress.IPv4Address(v)
        return v
    except ValueError:
        pass
    raise ValueError(f"Máscara de red inválida: {v!r}")


class ServerIPCreate(BaseModel):
    address:       str  = Field(..., max_length=45)
    netmask:       Optional[str] = Field(None, max_length=48)
    interface:     str  = Field("eth0", max_length=20)
    ip_type:       Literal["shared", "dedicated"] = "shared"
    nat_ip:        Optional[str] = Field(None, max_length=45)
    owner_user_id: Optional[int] = None
    is_active:     bool = True
    note:          Optional[str] = Field(None, max_length=255)

    @field_validator("address")
    @classmethod
    def check_address(cls, v):
        return _validate_address(v)

    @field_validator("netmask")
    @classmethod
    def check_netmask(cls, v):
        return _validate_netmask(v)

    @field_validator("nat_ip")
    @classmethod
    def check_nat(cls, v):
        if v is None or v == "":
            return None
        return _validate_address(v)


class ServerIPUpdate(BaseModel):
    netmask:       Optional[str] = Field(None, max_length=48)
    interface:     Optional[str] = Field(None, max_length=20)
    ip_type:       Optional[Literal["shared", "dedicated"]] = None
    nat_ip:        Optional[str] = Field(None, max_length=45)
    owner_user_id: Optional[int] = None
    is_active:     Optional[bool] = None
    note:          Optional[str] = Field(None, max_length=255)

    @field_validator("netmask")
    @classmethod
    def check_netmask(cls, v):
        return _validate_netmask(v)

    @field_validator("nat_ip")
    @classmethod
    def check_nat(cls, v):
        if v is None or v == "":
            return None
        return _validate_address(v)


class ServerIPResponse(BaseModel):
    id:            int
    address:       str
    netmask:       Optional[str] = None
    interface:     str
    ip_type:       str
    is_ipv6:       bool
    nat_ip:        Optional[str] = None
    owner_user_id: Optional[int] = None
    owner_username: Optional[str] = None
    is_active:     bool
    note:          Optional[str] = None
    domains_count: int = 0
    created_at:    datetime
    updated_at:    Optional[datetime] = None

    class Config:
        from_attributes = True


class SystemIPInfo(BaseModel):
    """IP detectada en el sistema (ip addr)"""
    address:   str
    netmask:   Optional[str] = None
    interface: str
    is_ipv6:   bool
    registered: bool = False   # ya está en la BD
