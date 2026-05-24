"""
Esquemas Pydantic para SSL
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class SSLCreate(BaseModel):
    certificate: str
    key: str
    expires: Optional[datetime] = None


class SSLUpdate(BaseModel):
    certificate: Optional[str] = None
    key: Optional[str] = None
    expires: Optional[datetime] = None


class SSLResponse(BaseModel):
    domain_id: int
    ssl_enabled: bool
    ssl_expires: Optional[datetime]
    certificate: Optional[str] = None
    key: Optional[str] = None

    class Config:
        from_attributes = True
