"""
Rutas API para gestión DNS (zonas y registros BIND9)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from api.models.database import get_db
from api.models.models_dns import DnsZone, DnsRecord
from api.models.models_domain import Domain
from api.models.models_user import User
from api.models.models_settings import Settings
from api.schemas.dns_schemas import (
    DnsZoneCreate, DnsZoneUpdate, DnsZoneResponse, DnsZoneListItem,
    DnsRecordCreate, DnsRecordUpdate, DnsRecordResponse,
)
from api.dependencies import require_auth, require_admin
from scripts.dns_manager import DNSManager

router = APIRouter()


# ──────────────────────── helpers de permisos ────────────────────────────────

def _user_can_edit_zone(zone: DnsZone, current_user, db: Session) -> bool:
    """True si el usuario puede editar esta zona (es admin o es propietario del dominio)"""
    if current_user.role == "admin":
        return True
    domain = db.query(Domain).filter(Domain.domain_name == zone.domain_name).first()
    return domain is not None and domain.user_id == current_user.id


def _require_zone_access(zone: DnsZone, current_user, db: Session):
    """Lanza 403 si el usuario no puede editar la zona"""
    if not _user_can_edit_zone(zone, current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para modificar esta zona DNS"
        )


# ──────────────────────── helpers técnicos ───────────────────────────────────

def _get_all_active_zones(db: Session) -> list:
    return [z.domain_name for z in db.query(DnsZone).filter(DnsZone.is_active == True).all()]


def _get_server_ipv4(db: Session) -> str:
    """
    Obtiene la IP pública del servidor.
    1. Si está guardada en Settings.server_ipv4, la devuelve.
    2. Si no, la detecta automáticamente con `ip -4 addr show scope global`.
    3. Si todo falla, devuelve vacío.
    """
    s = db.query(Settings).filter(Settings.id == 1).first()
    if s and s.server_ipv4:
        return s.server_ipv4

    # Detectar automáticamente si no está guardada
    try:
        import subprocess
        r = subprocess.run(
            ["ip", "-4", "addr", "show", "scope", "global"],
            capture_output=True, text=True, timeout=5,
        )
        for line in r.stdout.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                ip = line.split()[1].split("/")[0]
                if ip and not ip.startswith("127."):
                    return ip
    except Exception:
        pass

    return ""


def _sync_zone_to_bind(zone: DnsZone, db: Session):
    """
    Sincroniza la zona. Si hay cluster DNS configurado, empuja la zona al master
    (ns1) por SSH y este replica al slave (ns2). Si NO hay cluster, escribe el
    BIND local del panel (comportamiento por defecto: el panel sirve DNS).
    """
    records = db.query(DnsRecord).filter(DnsRecord.zone_id == zone.id).all()
    record_dicts = [
        {"record_type": r.record_type, "name": r.name,
         "content": r.content, "ttl": r.ttl, "priority": r.priority}
        for r in records
    ]
    from scripts.dns_manager import get_panel_nameservers
    panel_ns1, _ = get_panel_nameservers(db)
    soa_ns = zone.soa_ns or panel_ns1
    ttl = zone.ttl or 14400

    # 1) Intentar cluster (no requiere root local; va por SSH al master)
    try:
        from scripts.dns_cluster import push_zone_to_cluster
        zone_text = DNSManager.render_zone(
            zone.domain_name, zone.serial, record_dicts, soa_ns=soa_ns, ttl=ttl,
        )
        if push_zone_to_cluster(db, zone.domain_name, zone_text,
                                dnssec=bool(zone.dnssec_enabled)):
            return  # empujada al cluster; el panel no sirve DNS en este modo
    except Exception as e:
        # Si el cluster falla, lo registramos pero NO caemos al BIND local
        # (sería incoherente). La ruta puede exponer el error si lo desea.
        import logging
        logging.getLogger(__name__).error(f"push al cluster DNS falló: {e}")
        raise

    # 2) Sin cluster → BIND local del panel
    try:
        manager = DNSManager()
        manager.write_zone_from_records(
            zone.domain_name, zone.serial, record_dicts,
            soa_ns=soa_ns, ttl=ttl,
        )
        all_zones = _get_all_active_zones(db)
        manager.reload_zone(zone.domain_name, all_zones)
    except PermissionError:
        pass  # entorno dev sin root


def _zone_to_list_item(zone: DnsZone, record_count: int, can_edit: bool) -> DnsZoneListItem:
    return DnsZoneListItem(
        id=zone.id, domain_name=zone.domain_name, serial=zone.serial,
        is_active=zone.is_active, record_count=record_count, created_at=zone.created_at,
        ip_address=zone.ip_address, soa_ns=zone.soa_ns, ttl=zone.ttl,
        template=zone.template, dnssec_enabled=zone.dnssec_enabled, expires_at=zone.expires_at,
        can_edit=can_edit,
    )


def _zone_to_response(zone: DnsZone, records: list, can_edit: bool) -> DnsZoneResponse:
    return DnsZoneResponse(
        id=zone.id, domain_name=zone.domain_name, serial=zone.serial,
        is_active=zone.is_active, created_at=zone.created_at,
        ip_address=zone.ip_address, soa_ns=zone.soa_ns, ttl=zone.ttl,
        template=zone.template, dnssec_enabled=zone.dnssec_enabled, expires_at=zone.expires_at,
        can_edit=can_edit,
        records=[DnsRecordResponse.model_validate(r) for r in records]
    )


# ──────────────────────── Zonas ──────────────────────────────────────────────

@router.get("/dns", response_model=List[DnsZoneListItem])
async def list_zones(
    current_user=Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Listar zonas DNS (admin ve todas, usuario solo las de sus dominios)"""
    if current_user.role == "admin":
        zones = db.query(DnsZone).order_by(DnsZone.domain_name).all()
    else:
        # Solo zonas de dominios que pertenecen al usuario
        user_domains = db.query(Domain.domain_name).filter(Domain.user_id == current_user.id).all()
        user_domain_names = [d.domain_name for d in user_domains]
        zones = db.query(DnsZone).filter(
            DnsZone.domain_name.in_(user_domain_names)
        ).order_by(DnsZone.domain_name).all()

    result = []
    for z in zones:
        count = db.query(DnsRecord).filter(DnsRecord.zone_id == z.id).count()
        result.append(_zone_to_list_item(z, count, can_edit=True))
    return result


@router.post("/dns", response_model=DnsZoneResponse, status_code=status.HTTP_201_CREATED)
async def create_zone(
    data: DnsZoneCreate,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Crear zona DNS. La zona pertenece al cliente dueño del dominio.

    Seguridad: la zona SIEMPRE se ata a un dominio existente de un cliente (no del
    admin), igual que el resto de recursos. Un admin/reseller no puede crear zonas
    "sueltas" para dominios inexistentes o de su propia cuenta de admin.
    """
    domain = db.query(Domain).filter(Domain.domain_name == data.domain_name).first()

    if current_user.role != "admin":
        # Usuario/reseller: solo sus propios dominios
        if not domain or domain.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo puedes crear zonas DNS para tus propios dominios"
            )
    else:
        # Admin: el dominio debe existir y pertenecer a un cliente (no a un admin)
        if not domain:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(f"No existe el dominio '{data.domain_name}' en el panel. "
                        "Crea primero el dominio (asignado a un cliente) y luego su zona DNS."),
            )
        owner = db.query(User).filter(User.id == domain.user_id).first()
        if owner and (owner.is_admin or getattr(owner, "role", None) == "admin"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=("Ese dominio pertenece a una cuenta de administrador. "
                        "Las zonas DNS deben pertenecer a un cliente."),
            )

    existing = db.query(DnsZone).filter(DnsZone.domain_name == data.domain_name).first()
    if existing:
        raise HTTPException(status_code=409, detail="La zona ya existe")

    # Validar límite de zonas DNS del plan (dueño = propietario del dominio)
    owner_domain = db.query(Domain).filter(Domain.domain_name == data.domain_name).first()
    if owner_domain:
        owner = db.query(User).filter(User.id == owner_domain.user_id).first()
        if owner and getattr(owner, "dns_zones_limit", 0) and owner.dns_zones_limit > 0:
            zone_count = (
                db.query(DnsZone)
                .join(Domain, DnsZone.domain_name == Domain.domain_name)
                .filter(Domain.user_id == owner.id)
                .count()
            )
            if zone_count >= owner.dns_zones_limit:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        f"Límite de zonas DNS del plan alcanzado "
                        f"({zone_count}/{owner.dns_zones_limit})."
                    ),
                )

    from scripts.dns_manager import get_panel_nameservers
    ns1, ns2 = get_panel_nameservers(db)
    ipv4 = data.ip_address or _get_server_ipv4(db)
    # Por defecto el SOA usa el ns1 del panel; el usuario puede overridear soa_ns.
    soa_ns = data.soa_ns or ns1
    ttl    = data.ttl or 14400

    domain_obj = db.query(Domain).filter(Domain.domain_name == data.domain_name).first()
    ipv6 = domain_obj.ipv6 if domain_obj else None

    try:
        manager = DNSManager()
        serial = manager.create_zone(data.domain_name, ipv4=ipv4, ipv6=ipv6, ns1=soa_ns, ttl=ttl)
    except PermissionError:
        serial = 2026052501

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

    default_records = _build_template_records(data.domain_name, ipv4, ipv6, ns1, ns2)
    for r in default_records:
        db.add(DnsRecord(zone_id=zone.id, **r))
    db.commit()

    try:
        all_zones = _get_all_active_zones(db)
        DNSManager().reload_zone(data.domain_name, all_zones)
    except PermissionError:
        pass

    db.refresh(zone)
    records = db.query(DnsRecord).filter(DnsRecord.zone_id == zone.id).all()
    return _zone_to_response(zone, records, can_edit=True)


# ── Nameservers del panel (Fase A) — rutas ESTÁTICAS antes que /dns/{zone_id} ──

@router.get("/dns/nameservers")
async def get_nameservers(current_user=Depends(require_auth), db: Session = Depends(get_db)):
    """
    Nameservers efectivos del panel (settings → cluster → placeholder) + glue
    records sugeridos para registrar en el registrador del dominio padre.
    """
    from scripts.dns_manager import get_panel_nameservers, DEFAULT_NS1
    ns1, ns2 = get_panel_nameservers(db)
    server_ipv4 = _get_server_ipv4(db)

    ns1_ip = ns2_ip = None
    try:
        from api.models.models_dns_node import DnsNode
        m = db.query(DnsNode).filter(DnsNode.role == "master").first()
        s = db.query(DnsNode).filter(DnsNode.role == "slave").first()
        ns1_ip = m.ip if m else (server_ipv4 or None)
        ns2_ip = s.ip if s else None
    except Exception:
        ns1_ip = server_ipv4 or None

    return {
        "ns1": ns1, "ns2": ns2, "ns1_ip": ns1_ip, "ns2_ip": ns2_ip,
        "is_placeholder": ns1 == DEFAULT_NS1,
    }


@router.post("/dns/regenerate-all")
async def regenerate_all_zones(current_user=Depends(require_admin), db: Session = Depends(get_db)):
    """
    Regenera TODAS las zonas con los nameservers actuales del panel (actualiza
    SOA + registros NS) y las sincroniza. Útil tras configurar/cambiar los NS.
    """
    from scripts.dns_manager import get_panel_nameservers
    ns1, ns2 = get_panel_nameservers(db)
    zones = db.query(DnsZone).all()
    updated, failed = 0, []
    for zone in zones:
        try:
            ipv4 = zone.ip_address or _get_server_ipv4(db)
            domain_obj = db.query(Domain).filter(Domain.domain_name == zone.domain_name).first()
            ipv6 = domain_obj.ipv6 if domain_obj else None
            zone.soa_ns = ns1
            db.query(DnsRecord).filter(DnsRecord.zone_id == zone.id).delete()
            for r in _build_template_records(zone.domain_name, ipv4, ipv6, ns1, ns2):
                db.add(DnsRecord(zone_id=zone.id, **r))
            zone.serial = _bump_serial(zone.serial)
            db.commit()
            db.refresh(zone)
            _sync_zone_to_bind(zone, db)
            updated += 1
        except Exception as e:
            db.rollback()
            failed.append({"domain": zone.domain_name, "error": str(e)})
    return {"status": "success", "updated": updated, "failed": failed,
            "ns1": ns1, "ns2": ns2}


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

    can_edit = _user_can_edit_zone(zone, current_user, db)
    records = db.query(DnsRecord).filter(DnsRecord.zone_id == zone_id).all()
    return _zone_to_response(zone, records, can_edit=can_edit)


@router.put("/dns/{zone_id}", response_model=DnsZoneResponse)
async def update_zone(
    zone_id: int,
    data: DnsZoneUpdate,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Editar configuración de una zona DNS (IP, SOA, TTL, DNSSEC, plantilla...)"""
    zone = db.query(DnsZone).filter(DnsZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zona no encontrada")

    _require_zone_access(zone, current_user, db)

    changed = False

    if data.ip_address is not None:
        zone.ip_address = data.ip_address
        for r in db.query(DnsRecord).filter(DnsRecord.zone_id == zone_id, DnsRecord.record_type == "A").all():
            r.content = data.ip_address
        changed = True

    if data.soa_ns is not None:
        from scripts.dns_manager import get_panel_nameservers
        _pns1, _ = get_panel_nameservers(db)
        old_ns_dot = (zone.soa_ns or _pns1).rstrip(".") + "."
        old_ns_rec = db.query(DnsRecord).filter(
            DnsRecord.zone_id == zone_id, DnsRecord.record_type == "NS",
            DnsRecord.name == "@", DnsRecord.content == old_ns_dot
        ).first()
        if old_ns_rec:
            old_ns_rec.content = data.soa_ns.rstrip(".") + "."
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
    return _zone_to_response(zone, records, can_edit=True)


@router.post("/dns/{zone_id}/regenerate", response_model=DnsZoneResponse)
async def regenerate_zone(
    zone_id: int,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Regenera los registros de la zona con la plantilla actual"""
    zone = db.query(DnsZone).filter(DnsZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zona no encontrada")

    _require_zone_access(zone, current_user, db)

    from scripts.dns_manager import get_panel_nameservers
    ns1, ns2 = get_panel_nameservers(db)
    ipv4 = zone.ip_address or _get_server_ipv4(db)
    domain_obj = db.query(Domain).filter(Domain.domain_name == zone.domain_name).first()
    ipv6 = domain_obj.ipv6 if domain_obj else None

    # Regenerar adopta los nameservers actuales del panel (SOA + registros NS)
    zone.soa_ns = ns1
    db.query(DnsRecord).filter(DnsRecord.zone_id == zone_id).delete()
    for r in _build_template_records(zone.domain_name, ipv4, ipv6, ns1, ns2):
        db.add(DnsRecord(zone_id=zone.id, **r))

    zone.serial = _bump_serial(zone.serial)
    db.commit()
    db.refresh(zone)
    _sync_zone_to_bind(zone, db)

    records = db.query(DnsRecord).filter(DnsRecord.zone_id == zone_id).all()
    return _zone_to_response(zone, records, can_edit=True)


@router.delete("/dns/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_zone(
    zone_id: int,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Eliminar zona y sus registros"""
    zone = db.query(DnsZone).filter(DnsZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zona no encontrada")

    _require_zone_access(zone, current_user, db)

    domain_name = zone.domain_name
    db.query(DnsRecord).filter(DnsRecord.zone_id == zone_id).delete()
    db.delete(zone)
    db.commit()

    remaining = _get_all_active_zones(db)

    # Si hay cluster, borrar la zona del master y del slave
    try:
        from scripts.dns_cluster import load_cluster, DNSCluster, all_zones_meta
        cluster = load_cluster(db)
        if cluster:
            slave = cluster["slave"] or cluster["master"]
            DNSCluster(panel_id=cluster["panel_id"]).remove_zone(
                cluster["master"], slave, cluster["tsig"],
                domain_name, all_zones_meta(db))
            return None
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"borrado de zona en cluster falló: {e}")
        # seguimos para limpiar el BIND local si lo hubiera

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
    current_user=Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Añadir registro a una zona"""
    zone = db.query(DnsZone).filter(DnsZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zona no encontrada")

    _require_zone_access(zone, current_user, db)

    record = DnsRecord(
        zone_id=zone_id, record_type=data.record_type,
        name=data.name, content=data.content,
        ttl=data.ttl, priority=data.priority,
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
    current_user=Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Editar un registro DNS"""
    zone = db.query(DnsZone).filter(DnsZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zona no encontrada")

    _require_zone_access(zone, current_user, db)

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
    current_user=Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Eliminar un registro DNS"""
    zone = db.query(DnsZone).filter(DnsZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zona no encontrada")

    _require_zone_access(zone, current_user, db)

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


# ──────────────────────── DNSSEC (por zona, requiere cluster) ─────────────────

@router.get("/dns/{zone_id}/dnssec")
async def get_dnssec(
    zone_id: int,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """
    Estado DNSSEC de la zona + registros DS para el registrador.
    DNSSEC se firma en el master del cluster; sin cluster no está disponible.
    """
    zone = db.query(DnsZone).filter(DnsZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zona no encontrada")
    _require_zone_access(zone, current_user, db)

    out = {
        "enabled": bool(zone.dnssec_enabled),
        "cluster": False,
        "signed": False,
        "dnskeys": 0,
        "ds_records": [],
    }
    try:
        from scripts.dns_cluster import load_cluster, DNSCluster
        cluster = load_cluster(db)
        if cluster:
            out["cluster"] = True
            if zone.dnssec_enabled:
                cl = DNSCluster(panel_id=cluster["panel_id"])
                st = cl.dnssec_status(cluster["master"], zone.domain_name)
                out["signed"] = st["signed"]
                out["dnskeys"] = st["dnskeys"]
                if st["signed"]:
                    out["ds_records"] = cl.get_ds_records(cluster["master"], zone.domain_name)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"get_dnssec: {e}")
        out["error"] = str(e)
    return out


@router.post("/dns/{zone_id}/dnssec")
async def set_dnssec(
    zone_id: int,
    enabled: bool = True,
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """
    Activa/desactiva DNSSEC en la zona. Requiere cluster (el master firma con
    dnssec-policy). Tras activar, el DS tarda unos segundos en estar disponible;
    consúltalo con GET /dns/{id}/dnssec.
    """
    zone = db.query(DnsZone).filter(DnsZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zona no encontrada")
    _require_zone_access(zone, current_user, db)

    from scripts.dns_cluster import load_cluster
    if not load_cluster(db):
        raise HTTPException(
            status_code=409,
            detail="DNSSEC requiere un cluster DNS configurado (el master firma las zonas).")

    zone.dnssec_enabled = bool(enabled)
    zone.serial = _bump_serial(zone.serial)
    db.commit()
    db.refresh(zone)

    # Reempujar la zona al cluster con el nuevo estado DNSSEC (cambia el bloque
    # zone en ns1: añade/quita dnssec-policy y reubica el fichero).
    try:
        _sync_zone_to_bind(zone, db)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Zona actualizada pero falló el push al cluster: {e}")

    return {
        "status": "success",
        "enabled": zone.dnssec_enabled,
        "message": ("DNSSEC activado: la zona se está firmando. Espera unos segundos "
                    "y consulta el registro DS para subirlo a tu registrador."
                    if zone.dnssec_enabled else "DNSSEC desactivado."),
    }


# ──────────────────────── helpers privados ───────────────────────────────────

def _bump_serial(current: int) -> int:
    from datetime import datetime
    today = int(datetime.utcnow().strftime("%Y%m%d")) * 100
    return max(current + 1, today + 1)


def _build_template_records(domain: str, ipv4: str, ipv6: str = None,
                            ns1: str = None, ns2: str = None) -> list:
    """
    Registros por defecto — plantilla Hestia default.
    NS×2, A(@+mail), CNAME(www+ftp+webmail), MX, TXT(SPF+DMARC), SRV(mail)
    ns1/ns2: nameservers del panel (de get_panel_nameservers).
    """
    from scripts.dns_manager import DEFAULT_NS1, DEFAULT_NS2
    ns1 = (ns1 or DEFAULT_NS1).rstrip(".")
    ns2 = (ns2 or DEFAULT_NS2).rstrip(".")
    records = []

    # NS
    records.append({"record_type": "NS", "name": "@", "content": f"{ns1}.", "ttl": 86400, "priority": 0})
    records.append({"record_type": "NS", "name": "@", "content": f"{ns2}.", "ttl": 86400, "priority": 0})

    # A
    if ipv4:
        records.append({"record_type": "A",    "name": "@",    "content": ipv4, "ttl": 14400, "priority": 0})
        records.append({"record_type": "A",    "name": "mail", "content": ipv4, "ttl": 14400, "priority": 0})

    # AAAA
    if ipv6:
        records.append({"record_type": "AAAA", "name": "@",    "content": ipv6, "ttl": 14400, "priority": 0})
        records.append({"record_type": "AAAA", "name": "mail", "content": ipv6, "ttl": 14400, "priority": 0})

    # CNAME
    records.append({"record_type": "CNAME", "name": "www",     "content": f"{domain}.",      "ttl": 14400, "priority": 0})
    records.append({"record_type": "CNAME", "name": "ftp",     "content": f"{domain}.",      "ttl": 14400, "priority": 0})
    records.append({"record_type": "CNAME", "name": "webmail", "content": f"mail.{domain}.", "ttl": 14400, "priority": 0})

    # MX
    records.append({"record_type": "MX", "name": "@", "content": f"mail.{domain}.", "ttl": 14400, "priority": 0})

    # TXT SPF + DMARC
    spf = f"v=spf1 a mx ip4:{ipv4} -all" if ipv4 else "v=spf1 a mx -all"
    records.append({"record_type": "TXT", "name": "@",     "content": spf,                               "ttl": 14400, "priority": 0})
    records.append({"record_type": "TXT", "name": "_dmarc","content": "v=DMARC1; p=quarantine; pct=100", "ttl": 14400, "priority": 0})

    # SRV mail
    records.append({"record_type": "SRV", "name": "_submission._tcp", "content": f"0 587 mail.{domain}.", "ttl": 14400, "priority": 1})
    records.append({"record_type": "SRV", "name": "_imap._tcp",       "content": f"0 143 mail.{domain}.", "ttl": 14400, "priority": 1})
    records.append({"record_type": "SRV", "name": "_imaps._tcp",      "content": f"0 993 mail.{domain}.", "ttl": 14400, "priority": 1})
    records.append({"record_type": "SRV", "name": "_pop3._tcp",       "content": f"0 110 mail.{domain}.", "ttl": 14400, "priority": 1})
    records.append({"record_type": "SRV", "name": "_pop3s._tcp",      "content": f"0 995 mail.{domain}.", "ttl": 14400, "priority": 1})

    return records
