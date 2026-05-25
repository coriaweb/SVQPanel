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
    DnsZoneCreate, DnsZoneResponse, DnsZoneListItem,
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
        manager.write_zone_from_records(zone.domain_name, zone.serial, record_dicts)
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
            is_active=z.is_active, record_count=count, created_at=z.created_at
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

    ipv4 = _get_server_ipv4(db)

    # Obtener IPv6 del dominio si existe
    domain = db.query(Domain).filter(Domain.domain_name == data.domain_name).first()
    ipv6 = domain.ipv6 if domain else None

    try:
        manager = DNSManager()
        serial = manager.create_zone(data.domain_name, ipv4=ipv4, ipv6=ipv6)
    except PermissionError:
        serial = 2026052501  # dev

    zone = DnsZone(domain_name=data.domain_name, serial=serial)
    db.add(zone)
    db.commit()
    db.refresh(zone)

    # Insertar registros de la plantilla en BD
    default_records = _build_template_records(data.domain_name, ipv4, ipv6)
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

    # Actualizar serial
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


def _build_template_records(domain: str, ipv4: str, ipv6: str = None) -> list:
    """Registros por defecto — igual que plantilla Hestia"""
    records = []
    # NS
    records.append({"record_type": "NS", "name": "@", "content": "ns1.svqpanel.local.", "ttl": 86400, "priority": 0})
    records.append({"record_type": "NS", "name": "@", "content": "ns2.svqpanel.local.", "ttl": 86400, "priority": 0})
    # A
    if ipv4:
        for name in ["@", "www", "mail", "ftp"]:
            records.append({"record_type": "A", "name": name, "content": ipv4, "ttl": 14400, "priority": 0})
    # AAAA
    if ipv6:
        for name in ["@", "www"]:
            records.append({"record_type": "AAAA", "name": name, "content": ipv6, "ttl": 14400, "priority": 0})
    # MX
    records.append({"record_type": "MX", "name": "@", "content": f"mail.{domain}.", "ttl": 14400, "priority": 10})
    # TXT SPF
    records.append({"record_type": "TXT", "name": "@", "content": "v=spf1 a mx ~all", "ttl": 14400, "priority": 0})
    return records
