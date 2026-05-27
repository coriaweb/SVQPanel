"""
Esquemas Pydantic para Fase 12 — Firewall, fail2ban, listas IP, auditoría.
"""

from pydantic import BaseModel, Field, field_validator, HttpUrl
from typing import Optional, List
from datetime import datetime
import ipaddress
import re

VALID_ACTIONS    = {"allow", "deny", "reject"}
VALID_PROTOCOLS  = {"tcp", "udp", "icmp", "any"}
VALID_FAMILIES   = {"ipv4", "ipv6", "both"}
VALID_LIST_ACTIONS = {"block", "allow"}

SLUG_RE       = re.compile(r"^[a-z][a-z0-9_]{1,62}$")
PORT_RANGE_RE = re.compile(r"^(\d{1,5})(-\d{1,5})?$")


def _validate_ip_or_cidr(value: str) -> str:
    """Acepta IPv4/IPv6 con o sin máscara CIDR; devuelve la forma canónica."""
    try:
        net = ipaddress.ip_network(value, strict=False)
        return str(net) if net.prefixlen != net.max_prefixlen else str(net.network_address)
    except ValueError:
        raise ValueError(f"IP/CIDR inválido: {value}")


# ─────────────────────────────────────────────────────────────────────────────
# Firewall Rules
# ─────────────────────────────────────────────────────────────────────────────
class FirewallRuleCreate(BaseModel):
    action:        str = Field(..., description="allow | deny | reject")
    protocol:      str = Field("tcp", description="tcp | udp | icmp | any")
    port_range:    Optional[str] = Field(None, description="'80' o '8000-9000' o null")
    source_ip:     Optional[str] = Field(None, description="IP o CIDR; null = cualquiera")
    description:   Optional[str] = Field(None, max_length=255)
    is_whitelist:  bool = False
    priority:      int  = Field(100, ge=1, le=10000)
    is_active:     bool = True

    @field_validator("action")
    @classmethod
    def _vk_action(cls, v):
        v = v.lower()
        if v not in VALID_ACTIONS:
            raise ValueError(f"action debe ser uno de: {sorted(VALID_ACTIONS)}")
        return v

    @field_validator("protocol")
    @classmethod
    def _vk_protocol(cls, v):
        v = v.lower()
        if v not in VALID_PROTOCOLS:
            raise ValueError(f"protocol debe ser uno de: {sorted(VALID_PROTOCOLS)}")
        return v

    @field_validator("port_range")
    @classmethod
    def _vk_port_range(cls, v):
        if v is None or v == "":
            return None
        m = PORT_RANGE_RE.match(v.strip())
        if not m:
            raise ValueError("port_range: formato '80' o '8000-9000'")
        parts = [int(x) for x in v.replace("-", " ").split()]
        if any(p < 1 or p > 65535 for p in parts):
            raise ValueError("Puertos fuera de rango (1-65535)")
        if len(parts) == 2 and parts[0] >= parts[1]:
            raise ValueError("Rango inválido: inicio >= fin")
        return v

    @field_validator("source_ip")
    @classmethod
    def _vk_source_ip(cls, v):
        if v is None or v == "":
            return None
        return _validate_ip_or_cidr(v.strip())


class FirewallRuleUpdate(BaseModel):
    action:        Optional[str]  = None
    protocol:      Optional[str]  = None
    port_range:    Optional[str]  = None
    source_ip:     Optional[str]  = None
    description:   Optional[str]  = Field(None, max_length=255)
    is_whitelist:  Optional[bool] = None
    priority:      Optional[int]  = Field(None, ge=1, le=10000)
    is_active:     Optional[bool] = None

    _vk_action     = field_validator("action")(FirewallRuleCreate._vk_action.__func__)
    _vk_protocol   = field_validator("protocol")(FirewallRuleCreate._vk_protocol.__func__)
    _vk_port_range = field_validator("port_range")(FirewallRuleCreate._vk_port_range.__func__)
    _vk_source_ip  = field_validator("source_ip")(FirewallRuleCreate._vk_source_ip.__func__)


class FirewallRuleResponse(BaseModel):
    id:            int
    action:        str
    protocol:      str
    port_range:    Optional[str]
    source_ip:     Optional[str]
    description:   Optional[str]
    is_whitelist:  bool
    priority:      int
    is_active:     bool
    created_by:    Optional[int]
    created_at:    datetime
    updated_at:    Optional[datetime]

    class Config:
        from_attributes = True


class FirewallApplyResponse(BaseModel):
    rules_applied: int
    sets_present:  List[str]
    auto_whitelisted_ip: Optional[str] = None
    message:       str


class FirewallStatusResponse(BaseModel):
    enabled:        bool
    table_present:  bool
    rule_count:     int
    whitelist_count: int
    banned_count:   int


# ─────────────────────────────────────────────────────────────────────────────
# Fail2ban
# ─────────────────────────────────────────────────────────────────────────────
class JailStatus(BaseModel):
    name:         str
    enabled:      bool
    currently_failed: int = 0
    total_failed:     int = 0
    currently_banned: int = 0
    total_banned:     int = 0
    file_list:        List[str] = []


class BannedIpResponse(BaseModel):
    ip:        str
    jail:      Optional[str] = None
    banned_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    banned_by: str = "fail2ban"   # 'fail2ban' | 'manual' | 'iplist'
    reason:    Optional[str] = None


class UnbanRequest(BaseModel):
    ip:   str
    jail: Optional[str] = None     # si null, intenta en todas las jails

    @field_validator("ip")
    @classmethod
    def _vk_ip(cls, v):
        try:
            ipaddress.ip_address(v.strip())
        except ValueError:
            raise ValueError(f"IP inválida: {v}")
        return v.strip()


class ManualBanRequest(BaseModel):
    ip:        str
    duration_seconds: Optional[int] = Field(None, ge=60, description="null = permanente")
    reason:    Optional[str] = Field(None, max_length=255)

    @field_validator("ip")
    @classmethod
    def _vk_ip(cls, v):
        try:
            ipaddress.ip_address(v.strip())
        except ValueError:
            raise ValueError(f"IP inválida: {v}")
        return v.strip()


class WhitelistF2BRequest(BaseModel):
    ip: str

    @field_validator("ip")
    @classmethod
    def _vk_ip(cls, v):
        try:
            ipaddress.ip_network(v.strip(), strict=False)
        except ValueError:
            raise ValueError(f"IP/CIDR inválido: {v}")
        return v.strip()


# ─────────────────────────────────────────────────────────────────────────────
# IP Lists
# ─────────────────────────────────────────────────────────────────────────────
class IpListCreate(BaseModel):
    name:                   str = Field(..., min_length=2, max_length=64)
    description:            Optional[str] = Field(None, max_length=255)
    url:                    str = Field(..., max_length=2048)
    action:                 str = Field("block")
    address_family:         str = Field("both")
    refresh_interval_hours: int = Field(24, ge=1, le=720)
    max_entries:            int = Field(500_000, ge=1, le=10_000_000)
    enabled:                bool = True

    @field_validator("name")
    @classmethod
    def _vk_name(cls, v):
        if not SLUG_RE.match(v):
            raise ValueError("name debe ser slug a-z 0-9 _ y empezar por letra")
        return v

    @field_validator("url")
    @classmethod
    def _vk_url(cls, v):
        v = v.strip()
        if not v.lower().startswith(("http://", "https://")):
            raise ValueError("URL debe usar http(s)://")
        return v

    @field_validator("action")
    @classmethod
    def _vk_action(cls, v):
        v = v.lower()
        if v not in VALID_LIST_ACTIONS:
            raise ValueError(f"action debe ser uno de: {sorted(VALID_LIST_ACTIONS)}")
        return v

    @field_validator("address_family")
    @classmethod
    def _vk_family(cls, v):
        v = v.lower()
        if v not in VALID_FAMILIES:
            raise ValueError(f"address_family debe ser uno de: {sorted(VALID_FAMILIES)}")
        return v


class IpListUpdate(BaseModel):
    description:            Optional[str]  = Field(None, max_length=255)
    url:                    Optional[str]  = Field(None, max_length=2048)
    action:                 Optional[str]  = None
    address_family:         Optional[str]  = None
    refresh_interval_hours: Optional[int]  = Field(None, ge=1, le=720)
    max_entries:            Optional[int]  = Field(None, ge=1, le=10_000_000)
    enabled:                Optional[bool] = None

    _vk_url    = field_validator("url")(IpListCreate._vk_url.__func__)
    _vk_action = field_validator("action")(IpListCreate._vk_action.__func__)
    _vk_family = field_validator("address_family")(IpListCreate._vk_family.__func__)


class IpListResponse(BaseModel):
    id:                     int
    name:                   str
    description:            Optional[str]
    url:                    str
    action:                 str
    address_family:         str
    refresh_interval_hours: int
    max_entries:            int
    enabled:                bool
    last_fetched_at:        Optional[datetime]
    last_success_at:        Optional[datetime]
    last_error:             Optional[str]
    entry_count_v4:         int = 0
    entry_count_v6:         int = 0
    created_at:             datetime

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────────────────────
# Audit log
# ─────────────────────────────────────────────────────────────────────────────
class AuditLogResponse(BaseModel):
    id:         int
    user_label: Optional[str]
    category:   str
    action:     str
    target:     Optional[str]
    ip_origin:  Optional[str]
    success:    bool
    error:      Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────────────────────
# Connections monitor
# ─────────────────────────────────────────────────────────────────────────────
class ActiveConnection(BaseModel):
    protocol:    str
    local_addr:  str
    local_port:  int
    remote_addr: str
    remote_port: int
    state:       str
    process:     Optional[str] = None
