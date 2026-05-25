"""
Esquemas Pydantic para DNS
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime, date

VALID_RECORD_TYPES = {"A", "AAAA", "CNAME", "MX", "TXT", "NS", "SRV", "CAA"}


class DnsRecordCreate(BaseModel):
    record_type: str = Field(..., description="Tipo: A AAAA CNAME MX TXT NS SRV CAA")
    name:        str = Field(..., min_length=1, max_length=255, description="@ o nombre de subdominio")
    content:     str = Field(..., min_length=1, max_length=500)
    ttl:         int = Field(14400, ge=60, le=86400)
    priority:    int = Field(0, ge=0, le=65535, description="Prioridad MX/SRV")

    @field_validator("record_type")
    @classmethod
    def validate_type(cls, v):
        v = v.upper()
        if v not in VALID_RECORD_TYPES:
            raise ValueError(f"Tipo inválido. Válidos: {', '.join(sorted(VALID_RECORD_TYPES))}")
        return v


class DnsRecordUpdate(BaseModel):
    content:  Optional[str] = Field(None, min_length=1, max_length=500)
    ttl:      Optional[int] = Field(None, ge=60, le=86400)
    priority: Optional[int] = Field(None, ge=0, le=65535)


class DnsRecordResponse(BaseModel):
    id:          int
    zone_id:     int
    record_type: str
    name:        str
    content:     str
    ttl:         int
    priority:    int

    class Config:
        from_attributes = True


class DnsZoneCreate(BaseModel):
    domain_name:    str = Field(..., min_length=4, max_length=255)
    ip_address:     Optional[str]  = None
    soa_ns:         Optional[str]  = "ns1.svqpanel.local"
    ttl:            Optional[int]  = Field(14400, ge=60, le=86400)
    template:       Optional[str]  = "default"
    dnssec_enabled: Optional[bool] = False
    expires_at:     Optional[date] = None


class DnsZoneUpdate(BaseModel):
    ip_address:     Optional[str]  = None
    soa_ns:         Optional[str]  = None
    ttl:            Optional[int]  = Field(None, ge=60, le=86400)
    template:       Optional[str]  = None
    dnssec_enabled: Optional[bool] = None
    expires_at:     Optional[date] = None


class DnsZoneResponse(BaseModel):
    id:             int
    domain_name:    str
    serial:         int
    is_active:      bool
    ip_address:     Optional[str]  = None
    soa_ns:         Optional[str]  = None
    ttl:            Optional[int]  = 14400
    template:       Optional[str]  = "default"
    dnssec_enabled: Optional[bool] = False
    expires_at:     Optional[date] = None
    records:        List[DnsRecordResponse] = []
    created_at:     Optional[datetime] = None

    class Config:
        from_attributes = True


class DnsZoneListItem(BaseModel):
    id:             int
    domain_name:    str
    serial:         int
    is_active:      bool
    ip_address:     Optional[str]  = None
    soa_ns:         Optional[str]  = None
    ttl:            Optional[int]  = 14400
    template:       Optional[str]  = "default"
    dnssec_enabled: Optional[bool] = False
    expires_at:     Optional[date] = None
    record_count:   int = 0
    created_at:     Optional[datetime] = None

    class Config:
        from_attributes = True
