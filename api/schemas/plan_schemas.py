"""
Schemas Pydantic para Plan.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator
import re

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-]{1,62}$")


class PlanBase(BaseModel):
    name:                   str           = Field(..., min_length=2, max_length=64)
    description:            Optional[str] = Field(None, max_length=255)
    disk_quota_mb:          int           = Field(1024,  ge=0)   # 0 = ilimitado
    traffic_quota_mb_month: int           = Field(10240, ge=0)
    domains_limit:          int           = Field(5,     ge=0)
    databases_limit:        int           = Field(5,     ge=0)
    mailboxes_limit:        int           = Field(10,    ge=0)
    dns_zones_limit:        int           = Field(10,    ge=0)
    is_default:             bool          = False

    @field_validator("name")
    @classmethod
    def _vk_name(cls, v: str) -> str:
        v = v.strip()
        if not NAME_RE.match(v):
            raise ValueError("name debe ser alfanumérico (espacios/_/- permitidos), 2-63 chars")
        return v


class PlanCreate(PlanBase):
    # Solo admins pueden pasar owner_id (para crear plan en nombre de un reseller).
    # Si es None y el creador es admin → plan global.
    # Si es None y el creador es reseller → owner = self.
    owner_id: Optional[int] = None


class PlanUpdate(BaseModel):
    name:                   Optional[str]  = Field(None, min_length=2, max_length=64)
    description:            Optional[str]  = Field(None, max_length=255)
    disk_quota_mb:          Optional[int]  = Field(None, ge=0)
    traffic_quota_mb_month: Optional[int]  = Field(None, ge=0)
    domains_limit:          Optional[int]  = Field(None, ge=0)
    databases_limit:        Optional[int]  = Field(None, ge=0)
    mailboxes_limit:        Optional[int]  = Field(None, ge=0)
    dns_zones_limit:        Optional[int]  = Field(None, ge=0)
    is_default:             Optional[bool] = None

    _vk_name = field_validator("name")(PlanBase._vk_name.__func__)


class PlanResponse(PlanBase):
    id:         int
    owner_id:   Optional[int]
    owner_username: Optional[str] = None
    users_count:    int = 0      # cuántos usuarios tienen este plan asignado
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True
