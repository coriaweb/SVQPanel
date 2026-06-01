"""
Rutas API del cluster DNS (master/slave). Solo admin.

Flujo típico:
  1. POST /dns/cluster/nodes        → alta ns1 (master) y ns2 (slave)
  2. POST /dns/cluster/nodes/{id}/test  → verifica SSH
  3. POST /dns/cluster/provision    → genera TSIG, instala BIND en ambos,
                                       configura master/slave y sube las zonas
  4. (a partir de aquí, crear/editar zonas las empuja el panel al master)
  5. GET  /dns/cluster/status       → estado + verificación de replicación

Mientras no haya master configurado, el panel sirve DNS él mismo (BIND local).
"""

import ipaddress
import re
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from api.models.database import get_db
from api.models.models_dns_node import DnsNode
from api.models.models_dns import DnsZone
from api.models.models_settings import Settings
from api.dependencies import require_admin
from scripts.dns_cluster import DNSCluster, DNSClusterError, _node_dict, DEFAULT_TSIG_ALGO

router = APIRouter()

_HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](-?[a-z0-9])*\.)+[a-z]{2,}$", re.I)


# ──────────────────────── Schemas ────────────────────────────────────────────
class DnsNodeCreate(BaseModel):
    role: str = Field(..., description="master o slave")
    hostname: str = Field(..., max_length=255)
    ip: str = Field(..., max_length=45)
    ssh_user: str = Field("root", max_length=64)
    ssh_port: int = Field(22, ge=1, le=65535)
    ssh_key_path: Optional[str] = Field(None, max_length=255)
    # Contraseña SSH opcional (no se persiste; solo se usa para aprovisionar)
    ssh_password: Optional[str] = Field(None, max_length=255)

    @field_validator("role")
    @classmethod
    def _role(cls, v):
        if v not in ("master", "slave"):
            raise ValueError("role debe ser 'master' o 'slave'")
        return v

    @field_validator("hostname")
    @classmethod
    def _host(cls, v):
        if not _HOSTNAME_RE.match(v):
            raise ValueError("hostname no válido (usa un FQDN, ej. ns1.tudominio.com)")
        return v.lower()

    @field_validator("ip")
    @classmethod
    def _ip(cls, v):
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError("IP no válida")
        return v


class DnsNodeResponse(BaseModel):
    id: int
    role: str
    hostname: str
    ip: str
    ssh_user: str
    ssh_port: int
    status: str
    tsig_configured: bool
    last_sync_at: Optional[datetime] = None
    last_error: Optional[str] = None

    class Config:
        from_attributes = True


# Guarda en memoria de proceso las contraseñas SSH dadas en el alta (no se
# persisten en BD). Si el backend se reinicia, hay que re-introducirlas para
# re-aprovisionar (las operaciones normales de zona usan clave o ya no las
# necesitan porque el cluster ya está montado).
_SSH_PASSWORDS: dict = {}


# ──────────────────────── Helpers ────────────────────────────────────────────
def _node_with_secret(node_row) -> dict:
    d = _node_dict(node_row)
    pw = _SSH_PASSWORDS.get(node_row.id)
    if pw and not d.get("ssh_key_path"):
        d["ssh_password"] = pw
    return d


def _get_master(db: Session) -> Optional[DnsNode]:
    return db.query(DnsNode).filter(DnsNode.role == "master").first()


def _get_slave(db: Session) -> Optional[DnsNode]:
    return db.query(DnsNode).filter(DnsNode.role == "slave").first()


def _all_zone_domains(db: Session) -> List[str]:
    return [z.domain_name for z in db.query(DnsZone).filter(DnsZone.is_active == True).all()]


# ──────────────────────── Endpoints ──────────────────────────────────────────
@router.get("/dns/cluster/nodes", response_model=List[DnsNodeResponse])
async def list_nodes(_=Depends(require_admin), db: Session = Depends(get_db)):
    return db.query(DnsNode).order_by(DnsNode.role).all()


@router.post("/dns/cluster/nodes", response_model=DnsNodeResponse,
             status_code=status.HTTP_201_CREATED)
async def add_node(data: DnsNodeCreate, _=Depends(require_admin),
                   db: Session = Depends(get_db)):
    # Un único nodo por rol
    existing = db.query(DnsNode).filter(DnsNode.role == data.role).first()
    if existing:
        raise HTTPException(409, detail=f"Ya existe un nodo {data.role}; elimínalo o edítalo")

    node = DnsNode(
        role=data.role, hostname=data.hostname, ip=data.ip,
        ssh_user=data.ssh_user, ssh_port=data.ssh_port,
        ssh_key_path=data.ssh_key_path, status="pending",
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    if data.ssh_password:
        _SSH_PASSWORDS[node.id] = data.ssh_password
    return node


@router.post("/dns/cluster/nodes/{node_id}/test")
async def test_node(node_id: int, _=Depends(require_admin),
                    db: Session = Depends(get_db)):
    node = db.query(DnsNode).filter(DnsNode.id == node_id).first()
    if not node:
        raise HTTPException(404, detail="Nodo no encontrado")
    res = DNSCluster().test_connection(_node_with_secret(node))
    node.status = "ok" if res.get("ok") else "error"
    node.last_error = None if res.get("ok") else res.get("error")
    db.commit()
    return res


@router.delete("/dns/cluster/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(node_id: int, _=Depends(require_admin),
                      db: Session = Depends(get_db)):
    node = db.query(DnsNode).filter(DnsNode.id == node_id).first()
    if not node:
        raise HTTPException(404, detail="Nodo no encontrado")
    _SSH_PASSWORDS.pop(node_id, None)
    db.delete(node)
    db.commit()
    return None


def _do_provision(db: Session) -> dict:
    """
    Aprovisiona el cluster completo: genera la TSIG (si no existe), instala y
    configura BIND en master y slave, y sube todas las zonas activas.
    Lanza HTTPException en caso de fallo. Reutilizable por provision y resync.
    """
    master = _get_master(db)
    if not master:
        raise HTTPException(400, detail="Falta el nodo master (ns1). Da de alta uno primero.")
    slave = _get_slave(db)

    # TSIG: reutilizar la de settings o generar una nueva
    s = db.query(Settings).filter(Settings.id == 1).first()
    if not s:
        s = Settings(id=1)
        db.add(s)
        db.commit()
        db.refresh(s)

    cl = DNSCluster()
    if not s.dns_tsig_secret:
        tsig = cl.generate_tsig()
        s.dns_tsig_name = tsig["name"]
        s.dns_tsig_secret = tsig["secret"]
        s.dns_tsig_algo = tsig["algo"]
        db.commit()
    else:
        tsig = {"name": s.dns_tsig_name, "algo": s.dns_tsig_algo or DEFAULT_TSIG_ALGO,
                "secret": s.dns_tsig_secret}

    # Construir las zonas (texto) desde la BD
    from api.models.models_dns import DnsRecord
    from scripts.dns_manager import DNSManager
    domains = _all_zone_domains(db)
    zones = []
    for z in db.query(DnsZone).filter(DnsZone.is_active == True).all():
        recs = db.query(DnsRecord).filter(DnsRecord.zone_id == z.id).all()
        rec_dicts = [{"record_type": r.record_type, "name": r.name,
                      "content": r.content, "ttl": r.ttl, "priority": r.priority}
                     for r in recs]
        zones.append({
            "domain": z.domain_name,
            "dnssec": bool(z.dnssec_enabled),
            "zone_text": DNSManager.render_zone(
                z.domain_name, z.serial, rec_dicts,
                soa_ns=z.soa_ns or master.hostname, ttl=z.ttl or 14400),
        })

    # ── Asegurar acceso por CLAVE SSH (no por contraseña) ──────────────────────
    # El push diario de zonas usa load_cluster() (desde BD, sin la contraseña en
    # memoria). Para que funcione siempre, instalamos la clave del panel en cada
    # nodo (usando la contraseña una vez) y guardamos ssh_key_path en BD.
    from scripts.dns_cluster import PANEL_SSH_KEY
    cl.ensure_panel_key()
    for node_row in (master, slave):
        if not node_row:
            continue
        if not node_row.ssh_key_path:
            nd = _node_with_secret(node_row)
            if nd.get("ssh_password"):
                ok, err = cl.install_panel_key(nd)
                if not ok:
                    node_row.status = "error"
                    node_row.last_error = f"instalando clave SSH: {err}"
                    db.commit()
                    raise HTTPException(502, detail=f"No se pudo instalar la clave SSH en {node_row.hostname}: {err}")
            # A partir de ahora este nodo se usa por clave
            node_row.ssh_key_path = PANEL_SSH_KEY
            db.commit()

    md = _node_with_secret(master)
    sd = _node_with_secret(slave) if slave else md
    result = {"master": None, "slave": None}
    try:
        result["master"] = cl.provision_master(md, sd, tsig, zones)
        master.status = "ok"
        master.tsig_configured = True
        master.last_sync_at = datetime.utcnow()
        master.last_error = None
        db.commit()
    except DNSClusterError as e:
        master.status = "error"
        master.last_error = str(e)
        db.commit()
        raise HTTPException(502, detail=f"Aprovisionando master: {e}")

    if slave:
        try:
            result["slave"] = cl.provision_slave(md, sd, tsig, domains)
            slave.status = "ok"
            slave.tsig_configured = True
            slave.last_sync_at = datetime.utcnow()
            slave.last_error = None
            db.commit()
        except DNSClusterError as e:
            slave.status = "error"
            slave.last_error = str(e)
            db.commit()
            raise HTTPException(502, detail=f"Aprovisionando slave: {e}")

    return {"status": "success", "message": "Cluster DNS aprovisionado",
            "data": result, "zones": len(zones)}


@router.post("/dns/cluster/provision")
async def provision_cluster(_=Depends(require_admin), db: Session = Depends(get_db)):
    """Aprovisiona el cluster (instala/configura master y slave, sube zonas)."""
    return _do_provision(db)


@router.get("/dns/cluster/status")
async def cluster_status(_=Depends(require_admin), db: Session = Depends(get_db)):
    master = _get_master(db)
    slave = _get_slave(db)
    s = db.query(Settings).filter(Settings.id == 1).first()
    tsig_ready = bool(s and s.dns_tsig_secret)

    out = {
        "enabled": bool(master),
        "tsig_ready": tsig_ready,
        "master": DnsNodeResponse.model_validate(master).model_dump() if master else None,
        "slave": DnsNodeResponse.model_validate(slave).model_dump() if slave else None,
        "replication": None,
    }
    # Verificar replicación en el slave (una zona de muestra)
    if master and slave and tsig_ready:
        domains = _all_zone_domains(db)
        if domains:
            res = DNSCluster().verify_replication(_node_with_secret(slave), domains[0])
            out["replication"] = {"sample_domain": domains[0], **res}
    return out


@router.post("/dns/cluster/resync")
async def resync_cluster(_=Depends(require_admin), db: Session = Depends(get_db)):
    """Reempuja TODAS las zonas activas al master (útil tras cambios masivos)."""
    if not _get_master(db):
        raise HTTPException(400, detail="No hay cluster configurado")
    return _do_provision(db)


@router.get("/dns/cluster/health")
async def cluster_health(live: bool = False, _=Depends(require_admin),
                         db: Session = Depends(get_db)):
    """
    Salud de sincronización del cluster: por cada zona compara el serial de la
    BD del panel con el que sirven ns1 y ns2.

    - Por defecto devuelve el ÚLTIMO health-check calculado por el timer
      (rápido, sin SSH). Incluye 'checked_at'.
    - Con ?live=1 lo recalcula en el momento (hace SSH a los nodos).
    """
    import json
    from scripts.dns_cluster import compute_cluster_health

    if not _get_master(db):
        return {"enabled": False, "rows": [], "summary": None, "checked_at": None}

    if live:
        health = compute_cluster_health(db)
        return {"enabled": True, "live": True, "checked_at": None, **(health or {})}

    s = db.query(Settings).filter(Settings.id == 1).first()
    if s and s.dns_cluster_health_json:
        try:
            cached = json.loads(s.dns_cluster_health_json)
        except (ValueError, TypeError):
            cached = {"rows": [], "summary": None}
        return {
            "enabled": True, "live": False,
            "checked_at": s.dns_cluster_health_at.isoformat() if s.dns_cluster_health_at else None,
            **cached,
        }
    # Nunca se ha calculado: hacerlo en vivo esta vez
    health = compute_cluster_health(db)
    return {"enabled": True, "live": True, "checked_at": None, **(health or {})}
