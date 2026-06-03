"""
Esquemas Pydantic para dominios
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime
import re


class DomainCreate(BaseModel):
    user_id: int
    domain_name: str = Field(..., min_length=5, max_length=255)
    php_version: Optional[str] = Field("8.2", pattern="^(7\\.4|8\\.[0-5])$")
    dns_enabled:  Optional[bool] = False
    mail_enabled: Optional[bool] = False
    ipv4: Optional[str] = None
    ipv6: Optional[str] = None


class DomainUpdate(BaseModel):
    php_version:    Optional[str]  = Field(None, pattern="^(7\.4|8\.[0-5])$")
    is_active:      Optional[bool] = None
    ipv4:           Optional[str]  = None
    ipv6:           Optional[str]  = None
    redirect_to:    Optional[str]  = Field(None, max_length=512)
    custom_docroot: Optional[str]  = Field(None, max_length=512)

    @field_validator('redirect_to')
    @classmethod
    def validate_redirect_url(cls, v):
        if v is not None and v != '':
            if not re.match(r'^https?://', v):
                raise ValueError('redirect_to debe empezar por http:// o https://')
        return v or None

    @field_validator('custom_docroot')
    @classmethod
    def validate_docroot_path(cls, v):
        if v is not None and v != '':
            if not v.startswith('/'):
                raise ValueError('custom_docroot debe ser una ruta absoluta (empieza por /)')
            if '..' in v:
                raise ValueError('custom_docroot no puede contener ..')
        return v or None

    # Modo solo-lectura HTTP
    readonly_mode_enabled: Optional[bool] = None
    allowed_mutation_ips:  Optional[str]  = None  # JSON array de IPs/CIDRs
    # Headers HTTP de seguridad
    security_headers_enabled: Optional[bool] = None
    # HTTP/3 (QUIC)
    http3_enabled: Optional[bool] = None

    @field_validator('allowed_mutation_ips')
    @classmethod
    def validate_ips(cls, v):
        if v is None or v.strip() == '' or v.strip() == '[]':
            return None
        import json, ipaddress
        try:
            ips = json.loads(v)
        except Exception:
            raise ValueError('allowed_mutation_ips debe ser un JSON array')
        if not isinstance(ips, list):
            raise ValueError('allowed_mutation_ips debe ser un JSON array')
        for ip in ips:
            try:
                ipaddress.ip_network(ip, strict=False)
            except ValueError:
                raise ValueError(f"IP/CIDR inválido: {ip}")
        return v


class DomainResponse(BaseModel):
    id: int
    user_id: int
    domain_name: str
    public_html: Optional[str] = None
    php_version: Optional[str] = None
    ssl_enabled: Optional[bool] = False
    ssl_expires: Optional[datetime] = None
    force_https:  Optional[bool] = False
    hsts_enabled: Optional[bool] = False
    ipv4: Optional[str] = None
    ipv6: Optional[str] = None
    is_active: Optional[bool] = True
    is_suspended: Optional[bool] = False
    disk_usage: Optional[int] = 0
    # FastCGI cache (Fase 14)
    fastcgi_cache_enabled:     Optional[bool] = False
    fastcgi_cache_ttl_minutes: Optional[int]  = 60
    # Redirección y docroot personalizado (Fase 16)
    redirect_to:    Optional[str] = None
    custom_docroot: Optional[str] = None
    # Rate limiting anti-abuso (Fase 19)
    rate_limit_enabled: Optional[bool] = False
    rate_limit_rps:     Optional[int]  = 10
    rate_limit_burst:   Optional[int]  = 20
    php_hardening_relaxed: Optional[bool] = False
    # Modo solo-lectura HTTP
    readonly_mode_enabled: Optional[bool] = False
    allowed_mutation_ips:  Optional[str]  = None  # JSON array
    # Headers HTTP de seguridad
    security_headers_enabled: Optional[bool] = False
    # HTTP/3 (QUIC)
    http3_enabled: Optional[bool] = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
