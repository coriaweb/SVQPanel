"""
Esquemas Pydantic — CrowdSec (Fase 12.7)
"""

from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel, Field, field_validator
import ipaddress
import re

# duration cscli: '4h', '1d', '30m', '7d12h'…
DURATION_RE = re.compile(r"^(\d+[smhd])+$", re.IGNORECASE)


class CrowdsecStatus(BaseModel):
    installed:    bool
    running:      bool
    version:      Optional[str] = None
    decisions:    int = 0
    bouncers:     int = 0
    collections:  int = 0
    scenarios:    int = 0


class CrowdsecDecision(BaseModel):
    id:         Optional[int] = None
    value:      Optional[str] = None
    scope:      Optional[str] = None
    type:       Optional[str] = None
    scenario:   Optional[str] = None
    origin:     Optional[str] = None
    duration:   Optional[str] = None
    country:    Optional[str] = None
    created_at: Optional[str] = None
    until:      Optional[str] = None


class CrowdsecAlert(BaseModel):
    id:              Optional[int] = None
    machine_id:      Optional[str] = None
    scenario:        Optional[str] = None
    message:         Optional[str] = None
    events_count:    Optional[int] = None
    start_at:        Optional[str] = None
    stop_at:         Optional[str] = None
    created_at:      Optional[str] = None
    source_ip:       Optional[str] = None
    source_scope:    Optional[str] = None
    source_country:  Optional[str] = None
    source_as:       Optional[str] = None


class CrowdsecBouncer(BaseModel):
    name:       Optional[str] = None
    revoked:    bool = False
    ip_address: Optional[str] = None
    type:       Optional[str] = None
    version:    Optional[str] = None
    last_pull:  Optional[str] = None
    created_at: Optional[str] = None


class CrowdsecCollection(BaseModel):
    name:        Optional[str] = None
    status:      Optional[str] = None
    version:     Optional[str] = None
    description: Optional[str] = None


class CrowdsecScenario(BaseModel):
    # Un escenario es la regla de detección concreta (p. ej.
    # http-bf-wordpress_bf_xmlrpc), que puede no pertenecer a ninguna colección.
    name:        Optional[str] = None
    status:      Optional[str] = None
    version:     Optional[str] = None
    description: Optional[str] = None


class CrowdsecBanRequest(BaseModel):
    ip:        str
    duration:  str = Field("4h", description="formato cscli: 4h, 1d, 30m…")
    reason:    Optional[str] = Field(None, max_length=255)
    type:      str = Field("ban", description="ban | captcha")

    @field_validator("ip")
    @classmethod
    def _vk_ip(cls, v: str) -> str:
        try:
            ipaddress.ip_network(v.strip(), strict=False)
        except ValueError:
            raise ValueError(f"IP/CIDR inválido: {v}")
        return v.strip()

    @field_validator("duration")
    @classmethod
    def _vk_duration(cls, v: str) -> str:
        if not DURATION_RE.match(v.strip()):
            raise ValueError("duration debe ser '4h', '1d', '30m'…")
        return v.strip().lower()

    @field_validator("type")
    @classmethod
    def _vk_type(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in {"ban", "captcha"}:
            raise ValueError("type debe ser 'ban' o 'captcha'")
        return v


class CrowdsecCapiStatus(BaseModel):
    enrolled:  bool = False
    logged_in: bool = False
    raw:       Optional[str] = None
