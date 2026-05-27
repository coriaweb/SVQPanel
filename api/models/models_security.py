"""
Modelos de seguridad — Firewall (nftables), Fail2ban, Listas IP, Auditoría
Fase 12.
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Index
from datetime import datetime
from api.models.database import Base


# ─────────────────────────────────────────────────────────────────────────────
# Reglas estáticas de firewall (gestionadas por el panel en table inet svqpanel)
# ─────────────────────────────────────────────────────────────────────────────
class FirewallRule(Base):
    __tablename__ = "firewall_rules"

    id            = Column(Integer, primary_key=True, index=True)

    # Tipo de regla
    action        = Column(String(10),  nullable=False)   # 'allow' | 'deny' | 'reject'
    protocol      = Column(String(10),  nullable=False, default="tcp")  # tcp|udp|icmp|any
    port_range    = Column(String(50),  nullable=True)    # '80', '8000-9000', null = cualquier puerto
    source_ip     = Column(String(64),  nullable=True)    # IP, CIDR, o null = 0.0.0.0/0 / ::/0

    # Metadatos
    description   = Column(String(255), nullable=True)
    is_whitelist  = Column(Boolean, default=False, nullable=False)
                       # Si True, esta regla tiene prioridad sobre cualquier deny/blocklist
                       # Se usa para garantizar acceso del admin (anti-lockout).

    # Orden de aplicación dentro de la chain (más bajo = primero)
    priority      = Column(Integer, default=100, nullable=False)

    is_active     = Column(Boolean, default=True, nullable=False)
    created_by    = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<FirewallRule {self.action} {self.protocol}/{self.port_range} from {self.source_ip}>"


# ─────────────────────────────────────────────────────────────────────────────
# IPs baneadas (registradas para la vista; la fuente de verdad sigue siendo
# fail2ban y nftables. Esto es para auditoría y listado rápido.)
# ─────────────────────────────────────────────────────────────────────────────
class BannedIp(Base):
    __tablename__ = "banned_ips"

    id          = Column(Integer, primary_key=True, index=True)
    ip          = Column(String(45), nullable=False, index=True)
    banned_by   = Column(String(20), nullable=False)            # 'fail2ban' | 'manual' | 'iplist'
    jail_name   = Column(String(64), nullable=True)             # solo si banned_by='fail2ban'
    reason      = Column(String(255), nullable=True)
    banned_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at  = Column(DateTime, nullable=True)               # null = permanente
    unbanned_at = Column(DateTime, nullable=True)               # null = aún activo

    def __repr__(self):
        return f"<BannedIp {self.ip} by={self.banned_by} jail={self.jail_name}>"


# ─────────────────────────────────────────────────────────────────────────────
# Listas IP desde URL externa (ej. ipverse, spamhaus, tor exit list…)
# Cada lista se materializa en un named set de nftables: bl_v4_<slug> / bl_v6_<slug>
# ─────────────────────────────────────────────────────────────────────────────
class IpList(Base):
    __tablename__ = "ip_lists"

    id                    = Column(Integer, primary_key=True, index=True)
    name                  = Column(String(64),  unique=True, nullable=False, index=True)
                              # slug usado para nombrar el set en nftables (a-z0-9_)
    description           = Column(String(255), nullable=True)
    url                   = Column(String(2048), nullable=False)
    action                = Column(String(10),  nullable=False, default="block")  # 'block' | 'allow'
    address_family        = Column(String(10),  nullable=False, default="both")   # 'ipv4' | 'ipv6' | 'both'

    refresh_interval_hours = Column(Integer, default=24, nullable=False)
    max_entries            = Column(Integer, default=500_000, nullable=False)

    enabled               = Column(Boolean, default=True, nullable=False)

    # Estado de la última sincronización
    last_fetched_at       = Column(DateTime, nullable=True)
    last_success_at       = Column(DateTime, nullable=True)
    last_error            = Column(Text, nullable=True)
    sha256_last           = Column(String(64), nullable=True)
    entry_count_v4        = Column(Integer, default=0)
    entry_count_v6        = Column(Integer, default=0)

    created_by            = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at            = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at            = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<IpList {self.name} action={self.action} entries={self.entry_count_v4+self.entry_count_v6}>"


# ─────────────────────────────────────────────────────────────────────────────
# Auditoría — quién hizo qué cambio de firewall y cuándo
# ─────────────────────────────────────────────────────────────────────────────
class SecurityAuditLog(Base):
    __tablename__ = "security_audit_log"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    user_label  = Column(String(64),  nullable=True)   # username snapshot (por si se borra el user)

    category    = Column(String(20),  nullable=False, index=True)
                       # 'firewall' | 'fail2ban' | 'iplist' | 'whitelist'
    action      = Column(String(40),  nullable=False)
                       # 'create_rule', 'delete_rule', 'apply', 'unban_ip', 'add_iplist'…
    target      = Column(String(255), nullable=True)
                       # descripción del objetivo (IP, nombre lista, port…)
    before      = Column(Text, nullable=True)          # JSON serializado del estado previo
    after       = Column(Text, nullable=True)          # JSON serializado del estado nuevo

    ip_origin   = Column(String(45),  nullable=True)   # IP del request que originó el cambio
    success     = Column(Boolean, default=True, nullable=False)
    error       = Column(Text, nullable=True)

    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self):
        return f"<SecurityAuditLog {self.category}.{self.action} by={self.user_label} ok={self.success}>"


Index("ix_security_audit_category_created", SecurityAuditLog.category, SecurityAuditLog.created_at.desc())
