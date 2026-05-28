"""
Esquemas Pydantic para SSL
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime


class SSLCreate(BaseModel):
    certificate: str
    key: str
    expires: Optional[datetime] = None


class SSLUpdate(BaseModel):
    certificate: Optional[str] = None
    key: Optional[str] = None
    expires: Optional[datetime] = None


class SSLCertInfo(BaseModel):
    issued_to:     Optional[str] = None
    sans:          Optional[List[str]] = []
    not_before:    Optional[str] = None
    not_after:     Optional[str] = None
    signature_alg: Optional[str] = None
    key_size:      Optional[str] = None
    key_type:      Optional[str] = None
    issuer:        Optional[str] = None
    pem:           Optional[str] = None


class SSLResponse(BaseModel):
    domain_id:    int
    ssl_enabled:  bool
    force_https:  bool = False
    hsts_enabled: bool = False
    ssl_expires:  Optional[datetime] = None
    certificate:  Optional[str] = None
    key:          Optional[str] = None
    cert_info:    Optional[SSLCertInfo] = None

    class Config:
        from_attributes = True


class SSLToggleRequest(BaseModel):
    enabled:      bool
    force_https:  bool = False
    hsts_enabled: bool = False
    email:        Optional[str] = Field(None, description="Email para certbot (solo al activar)")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        if v and "@" not in v:
            raise ValueError("Email inválido")
        return v
