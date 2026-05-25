"""
Esquemas Pydantic para dominios
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class DomainCreate(BaseModel):
    user_id: int
    domain_name: str = Field(..., min_length=5, max_length=255)
    php_version: Optional[str] = Field("8.2", pattern="^(7\\.4|8\\.[0-5])$")


class DomainUpdate(BaseModel):
    php_version: Optional[str] = Field(None, pattern="^(7\\.4|8\\.[0-5])$")
    is_active: Optional[bool] = None
    ipv4: Optional[str] = None
    ipv6: Optional[str] = None


class DomainResponse(BaseModel):
    id: int
    user_id: int
    domain_name: str
    public_html: Optional[str] = None
    php_version: Optional[str] = None
    ssl_enabled: Optional[bool] = False
    ssl_expires: Optional[datetime] = None
    ipv4: Optional[str] = None
    ipv6: Optional[str] = None
    is_active: Optional[bool] = True
    disk_usage: Optional[int] = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
