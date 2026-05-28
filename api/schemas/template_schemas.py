"""
Schemas Pydantic para el sistema de plantillas web.
"""

from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
import json


class WebTemplateBase(BaseModel):
    name:                 str  = Field(..., min_length=1, max_length=64)
    slug:                 str  = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    description:          Optional[str] = Field(None, max_length=255)
    category:             str  = Field("cms", pattern="^(cms|framework|ecommerce|other)$")
    nginx_extra:          Optional[str] = None
    php_ini_overrides:    Optional[str] = None   # JSON string
    fastcgi_cache_default: bool = False
    is_active:            bool = True

    @field_validator("php_ini_overrides")
    @classmethod
    def validate_php_overrides(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            json.loads(v)
        except (json.JSONDecodeError, TypeError):
            raise ValueError("php_ini_overrides debe ser JSON válido")
        return v

    class Config:
        from_attributes = True


class WebTemplateCreate(WebTemplateBase):
    pass


class WebTemplateUpdate(BaseModel):
    name:                  Optional[str] = Field(None, min_length=1, max_length=64)
    description:           Optional[str] = Field(None, max_length=255)
    category:              Optional[str] = Field(None, pattern="^(cms|framework|ecommerce|other)$")
    nginx_extra:           Optional[str] = None
    php_ini_overrides:     Optional[str] = None
    fastcgi_cache_default: Optional[bool] = None
    is_active:             Optional[bool] = None

    class Config:
        from_attributes = True


class WebTemplateResponse(WebTemplateBase):
    id:         int
    is_builtin: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ApplyTemplateRequest(BaseModel):
    template_id:   int
    # Permite anular la sugerencia de FastCGI cache de la plantilla
    enable_cache:  Optional[bool] = None
    ttl_minutes:   int = Field(60, ge=1, le=1440)
