"""
Esquemas Pydantic para dominios
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class DomainCreate(BaseModel):
    user_id: int
    domain_name: str = Field(..., min_length=5, max_length=255)
    php_version: Optional[str] = Field("8.2", pattern="^(7\\.4|8\\.[0-3])$")


class DomainUpdate(BaseModel):
    php_version: Optional[str] = Field(None, pattern="^(7\\.4|8\\.[0-3])$")
    is_active: Optional[bool] = None
    ipv4: Optional[str] = None
    ipv6: Optional[str] = None


class DomainResponse(BaseModel):
    id: int
    user_id: int
    domain_name: str
    public_html: str
    php_version: str
    ssl_enabled: bool
    ssl_expires: Optional[datetime]
    ipv4: Optional[str]
    ipv6: Optional[str]
    is_active: bool
    disk_usage: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
