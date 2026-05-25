"""
Rutas API para gestión DNS (zonas y registros BIND9)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from api.models.database import get_db
from api.models.models_dns import DnsZone, DnsRecord
from api.models.models_domain import Domain
from api.models.models_settings import Settings
from api.schemas.dns_schemas import (
    DnsZoneCreate, DnsZoneUpdate, DnsZoneResponse, DnsZoneListItem,
    DnsRecordCreate, DnsRecordUpdate, DnsRecordResponse,
)
from api.dependencies import require_auth, require_admin
from scripts.dns_manager import DNSManager

router = APIRouter()


# ──────────────────────── helpers ────────────────────────────────────────────

def _get_all_active_zones(db: Session) -> list:
    return [z.domain_name for z in db.query(DnsZone).filter(DnsZone.is_active == True).all()]


def _get_server_ipv4(db: Session) -> str:
    s = db.query(Settings).filter(Settings.id == 1).first()
    return s.server_ipv4 if s and s.server_ipv4 else ""


def _sync_zone_to_bind(zone: DnsZone, db: Session):
    """Regenera zone file + recarga BIND9 con los registros actuales de la zona"""
    records = db.query(DnsRecord).filter(DnsRecord.zone_id == zone.id).all()
    record_dicts = [
        {"record_type": r.record_type, "name": r.name,
         "content": r.content, "ttl": r.ttl, "priority": r.priority}
        for r in records
    ]
    try:
        manager = DNSManager()
        manager.write_zone_from_records(
            zone.domain_name,
            zone.serial,
            record_dicts,
            soa_ns=zone.soa_ns or "ns1.svqpanel.local",
            ttl=zone.ttl or 14400,
        )
        all_zones = _get_all_active_zones(db)
        manager.reload_zone(zone.domain_name, all_zones)
    except PermissionError:
        pass  # entorno dev sin root


# ──────────────────────── Zonas ──────────────────────────────────────────────

@router.get("/dns", response_model=List[DnsZoneListItem])
async def list_zones(
    current_user=Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Listar todas las zonas DNS"""
    zones = db.query(DnsZone).order_by(DnsZone.domain_name).all()
    result = []
    for z in zones:
        count = db.query(DnsRecord).filter(DnsRecord.zone_id == z.id).count()
        result.append(DnsZoneListItem(
            id=z.id, domain_name=z.domain_name, serial=z.serial,
            is_active=z.is_active, record_count=count, created_at=z.created_at,
            ip_address=z.ip_address, soa_ns=z.soa_ns, ttl=z.ttl,
            template=z.template, dnssec_enabled=z.dnssec_enabled, expires_at=z.expires_at,
        ))
    return result


@router.post("/dns", response_model=DnsZoneResponse, status_code=status.HTTP_201_CREATED)
async def create_zone(
    data: DnsZoneCreate,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db)
):
    """[Admin] Crear zona DNS con plantilla por defecto"""
    existing = db.query(DnsZone).filter(DnsZone.domain_name == data.domain_name).first()
    if existing:
        raise HTTPException(status_code=409, detail="La zona ya existe")

    # IP: usar la indicada, o la del servidor si no se especificó
    ipv4 = data.ip_address or _get_server_ipv4(db)
    soa_ns = data.soa_ns or "ns1.svqpanel.local"
    ttl    = data.ttl or 14400

    # Obtener IPv6 del dominio si existe
    domain = db.query(Domain).filter(Domain.domain_name == data.domain_name).first()
    ipv6 = domain.ipv6 if domain else None

    try:
        manager = DNSManager()
        serial = manager.create_zone(
            data.domain_name, ipv4=ipv4, ipv6=ipv6,
            ns1=soa_ns, ttl=ttl,
        )
    except PermissionError:
        serial = 2026052501  # dev

    zone = DnsZone(
        domain_name=data.domain_name, serial=serial,
        ip_address=ipv4, soa_ns=soa_ns, ttl=ttl,
        template=data.template or "default",
        dnssec_enabled=data.dnssec_enabled or False,
        expires_at=data.expires_at,
    )
    db.add(zone)
    db.commit()
    db.refresh(zone)

    # Insertar registros de la plantilla en BD
    default_records = _build_template_records(data.domain_name, ipv4, ipv6, soa_ns)
    for r in default_records:
        db.add(DnsRecord(zone_id=zone.id, **r))
    db.commit()

    # Reload BIND9
    try:
        manager = DNSManager()
        all_zones = _get_all_active_zones(db)
        manager.reload_zone(data.domain_name, all_zones)
    except PermissionError:
        pass

    db.refresh(zone)
    records = db.query(DnsRecord).filter(DnsRecord.zone_id == zone.id).all()
    return DnsZoneResponse(
        id=zone.id, domain_name=zone.domain_name, serial=zone.serial,
        is_active=zone.is_active, created_at=zone.created_at,
        ip_address=zone.ip_address, soa_ns=zone.soa_ns, ttl=zone.ttl,
        template=zone.template, dnssec_enabled=zone.dnssec_enabled, expires_at=zone.expires_at,
        records=[DnsRecordResponse.model_validate(r) for r in records]
    )


@router.get("/dns/{zone_id}", response_model=DnsZoneResponse)
async def get_zone(
    zone_id: int,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Obtener zona con todos sus registros"""
    zone = db.query(DnsZone).filter(DnsZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zona no encontrada")
    records = db.query(DnsRecord).filter(DnsRecord.zone_id == zone_id).all()
    return DnsZoneResponse(
        id=zone.id, domain_name=zone.domain_name, serial=zone.serial,
        is_active=zone.is_active, created_at=zone.created_at,
        ip_address=zone.ip_address, soa_ns=zone.soa_ns, ttl=zone.ttl,
        template=zone.template, dnssec_enabled=zone.dnssec_enabled, expires_at=zone.expires_at,
        records=[DnsRecordResponse.model_validate(r) for r in records]
    )


@router.put("/dns/{zone_id}", response_model=DnsZoneResponse)
async def update_zone(
    zone_id: int,
    data: DnsZoneUpdate,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db)
):
    """[Admin] Editar configuración de una zona DNS (IP, SOA, TTL, DNSSEC, plantilla...)"""
    zone = db.query(DnsZone).filter(DnsZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zona no encontrada")

    changed = False

    if data.ip_address is not None:
        zone.ip_address = data.ip_address
        # Actualizar registros A que apuntaban a la IP anterior
        old_a_records = db.query(DnsRecord).filter(
            DnsRecord.zone_id == zone_id,
            DnsRecord.record_type == "A"
        ).all()
        for r in old_a_records:
            r.content = data.ip_address
        changed = True

    if data.soa_ns is not None:
        # Actualizar registros NS que apuntaban al SOA anterior
        old_ns = db.query(DnsRecord).filter(
            DnsRecord.zone_id == zone_id,
            DnsRecord.record_type == "NS",
            DnsRecord.name == "@"
        ).first()
        if old_ns and old_ns.content == (zone.soa_ns or "ns1.svqpanel.local") + ".":
            old_ns.content = data.soa_ns.rstrip(".") + "."
        zone.soa_ns = data.soa_ns
        changed = True

    if data.ttl is not None:
        zone.ttl = data.ttl
        changed = True

    if data.template is not None:
        zone.template = data.template
        changed = True

    if data.dnssec_enabled is not None:
        zone.dnssec_enabled = data.dnssec_enabled
        changed = True

    if data.expires_at is not None:
        zone.expires_at = data.expires_at
        changed = True

    if changed:
        zone.serial = _bump_serial(zone.serial)
        db.commit()
        db.refresh(zone)
        _sync_zone_to_bind(zone, db)

    records = db.query(DnsRecord).filter(DnsRecord.zone_id == zone_id).all()
    return DnsZoneResponse(
        id=zone.id, domain_name=zone.domain_name, serial=zone.serial,
        is_active=zone.is_active, created_at=zone.created_at,
        ip_address=zone.ip_address, soa_ns=zone.soa_ns, ttl=zone.ttl,
        template=zone.template, dnssec_enabled=zone.dnssec_enabled, expires_at=zone.expires_at,
        records=[DnsRecordResponse.model_validate(r) for r in records]
    )


@router.delete("/dns/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_zone(
    zone_id: int,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db)
):
    """[Admin] Eliminar zona y sus registros"""
    zone = db.query(DnsZone).filter(DnsZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zona no encontrada")

    domain_name = zone.domain_name
    db.query(DnsRecord).filter(DnsRecord.zone_id == zone_id).delete()
    db.delete(zone)
    db.commit()

    remaining = _get_all_active_zones(db)
    try:
        DNSManager().delete_zone(domain_name, remaining)
    except PermissionError:
        pass
    return None


# ──────────────────────── Registros ──────────────────────────────────────────

@router.get("/dns/{zone_id}/records", response_model=List[DnsRecordResponse])
async def list_records(
    zone_id: int,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Listar registros de una zona"""
    zone = db.query(DnsZone).filter(DnsZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zona no encontrada")
    return db.query(DnsRecord).filter(DnsRecord.zone_id == zone_id).all()


@router.post("/dns/{zone_id}/records", response_model=DnsRecordResponse, status_code=status.HTTP_201_CREATED)
async def add_record(
    zone_id: int,
    data: DnsRecordCreate,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db)
):
    """[Admin] Añadir registro a una zona"""
    zone = db.query(DnsZone).filter(DnsZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zona no encontrada")

    record = DnsRecord(
        zone_id=zone_id,
        record_type=data.record_type,
        name=data.name,
        content=data.content,
        ttl=data.ttl,
        priority=data.priority,
    )
    db.add(record)

    zone.serial = _bump_serial(zone.serial)
    db.commit()
    db.refresh(record)

    _sync_zone_to_bind(zone, db)
    return record


@router.put("/dns/{zone_id}/records/{record_id}", response_model=DnsRecordResponse)
async def update_record(
    zone_id: int,
    record_id: int,
    data: DnsRecordUpdate,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db)
):
    """[Admin] Editar un registro DNS"""
    zone = db.query(DnsZone).filter(DnsZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zona no encontrada")
    record = db.query(DnsRecord).filter(
        DnsRecord.id == record_id, DnsRecord.zone_id == zone_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Registro no encontrado")

    if data.content  is not None: record.content  = data.content
    if data.ttl      is not None: record.ttl      = data.ttl
    if data.priority is not None: record.priority = data.priority

    zone.serial = _bump_serial(zone.serial)
    db.commit()
    db.refresh(record)

    _sync_zone_to_bind(zone, db)
    return record


@router.delete("/dns/{zone_id}/records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_record(
    zone_id: int,
    record_id: int,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db)
):
    """[Admin] Eliminar un registro DNS"""
    zone = db.query(DnsZone).filter(DnsZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zona no encontrada")
    record = db.query(DnsRecord).filter(
        DnsRecord.id == record_id, DnsRecord.zone_id == zone_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Registro no encontrado")

    db.delete(record)
    zone.serial = _bump_serial(zone.serial)
    db.commit()

    _sync_zone_to_bind(zone, db)
    return None


# ──────────────────────── helpers privados ───────────────────────────────────

def _bump_serial(current: int) -> int:
    from datetime import datetime
    today = int(datetime.utcnow().strftime("%Y%m%d")) * 100
    return max(current + 1, today + 1)


def _build_template_records(domain: str, ipv4: str, ipv6: str = None, soa_ns: str = None) -> list:
    """
    Registros por defecto — plantilla Hestia default.
    NS×2, A(@+mail), CNAME(www+ftp+webmail), MX, TXT(SPF+DMARC), SRV(mail)
    """
    ns1 = (soa_ns or "ns1.svqpanel.local").rstrip(".")
    ns2 = ns1.replace("ns1.", "ns2.", 1) if "ns1." in ns1 else "ns2.svqpanel.local"
    records = []

    # NS
    records.append({"record_type": "NS", "name": "@", "content": f"{ns1}.", "ttl": 86400, "priority": 0})
    records.append({"record_type": "NS", "name": "@", "content": f"{ns2}.", "ttl": 86400, "priority": 0})

    # A records
    if ipv4:
        records.append({"record_type": "A",     "name": "@",    "content": ipv4, "ttl": 14400, "priority": 0})
        records.append({"record_type": "A",     "name": "mail", "content": ipv4, "ttl": 14400, "priority": 0})

    # AAAA
    if ipv6:
        records.append({"record_type": "AAAA",  "name": "@",    "content": ipv6, "ttl": 14400, "priority": 0})
        records.append({"record_type": "AAAA",  "name": "mail", "content": ipv6, "ttl": 14400, "priority": 0})

    # CNAME (como Hestia: www y ftp apuntan al dominio raíz)
    records.append({"record_type": "CNAME", "name": "www",     "content": f"{domain}.", "ttl": 14400, "priority": 0})
    records.append({"record_type": "CNAME", "name": "ftp",     "content": f"{domain}.", "ttl": 14400, "priority": 0})
    records.append({"record_type": "CNAME", "name": "webmail", "content": f"mail.{domain}.", "ttl": 14400, "priority": 0})

    # MX
    records.append({"record_type": "MX", "name": "@", "content": f"mail.{domain}.", "ttl": 14400, "priority": 0})

    # TXT — SPF (con ip4 explícita como Hestia)
    spf = f"v=spf1 a mx ip4:{ipv4} -all" if ipv4 else "v=spf1 a mx -all"
    records.append({"record_type": "TXT", "name": "@",    "content": spf,                              "ttl": 14400, "priority": 0})

    # TXT — DMARC
    records.append({"record_type": "TXT", "name": "_dmarc", "content": "v=DMARC1; p=quarantine; pct=100", "ttl": 14400, "priority": 0})

    # SRV — servicios de correo (para futura integración de servidor de correo)
    records.append({"record_type": "SRV", "name": "_submission._tcp", "content": f"0 587 mail.{domain}.", "ttl": 14400, "priority": 1})
    records.append({"record_type": "SRV", "name": "_imap._tcp",       "content": f"0 143 mail.{domain}.", "ttl": 14400, "priority": 1})
    records.append({"record_type": "SRV", "name": "_imaps._tcp",      "content": f"0 993 mail.{domain}.", "ttl": 14400, "priority": 1})
    records.append({"record_type": "SRV", "name": "_pop3._tcp",       "content": f"0 110 mail.{domain}.", "ttl": 14400, "priority": 1})
    records.append({"record_type": "SRV", "name": "_pop3s._tcp",      "content": f"0 995 mail.{domain}.", "ttl": 14400, "priority": 1})

    return records
