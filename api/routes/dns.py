"""
Rutas API para gestión DNS (zonas y registros BIND9)
"""

import ipaddress

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


def _get_server_ipv6(db: Session) -> str:
    """IPv6 GLOBAL de salida del correo del servidor (la que tiene PTR y por la
    que sale el correo por defecto). Es la que DEBE ir en el SPF de cada dominio:
    si el correo sale por IPv6 pero el SPF no la lista → SPF fail en Gmail.

    Fuente: smtp_bind_address6 de Postfix (lo que arreglamos para que sea la del
    hostname con PTR). Fallback a Settings.panel_ipv6 si Postfix no responde."""
    try:
        import subprocess
        r = subprocess.run(["postconf", "-h", "smtp_bind_address6"],
                           capture_output=True, text=True, timeout=5)
        ip = (r.stdout or "").strip()
        if ip and ":" in ip:
            return ip
    except Exception:
        pass
    s = db.query(Settings).filter(Settings.id == 1).first()
    return (getattr(s, "panel_ipv6", None) or "") if s else ""


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
                        "Crea primero el dominio (asignado a un cliente) y luego su zona DNS. "
                        "Si solo quieres correo/DNS y la web está en otro servidor, "
                        "crea el dominio marcando «Solo correo / DNS»."),
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

    default_records = _build_template_records(data.domain_name, ipv4, ipv6, ns1, ns2,
                                              template=data.template or "default",
                                              server_ipv6=_get_server_ipv6(db))
    for r in default_records:
        db.add(DnsRecord(zone_id=zone.id, **r))
    db.commit()

    # Sincronizar con BIND (cluster si lo hay, o local). _sync_zone_to_bind hace
    # el PRECHECK de "zona ya en otro panel" y lanza DNSClusterError con mensaje
    # claro. Si falla, REVERTIMOS la zona recién creada en la BD (no dejar una
    # zona huérfana que el cluster rechazó) y devolvemos el error al usuario.
    try:
        _sync_zone_to_bind(zone, db)
    except PermissionError:
        pass
    except Exception as e:
        from scripts.dns_cluster import DNSClusterError
        db.query(DnsRecord).filter(DnsRecord.zone_id == zone.id).delete()
        db.delete(zone)
        db.commit()
        if isinstance(e, DNSClusterError):
            raise HTTPException(status_code=409, detail=str(e))
        raise HTTPException(status_code=502, detail=f"Error sincronizando la zona: {e}")

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
            for r in _build_template_records(zone.domain_name, ipv4, ipv6, ns1, ns2,
                                             template=zone.template,
                                             server_ipv6=_get_server_ipv6(db)):
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

    # PRESERVAR los registros de los SUBDOMINIOS colgados de esta zona: regenerar
    # aplica la plantilla, pero gestion/socios viven como registros A/AAAA aquí y
    # no deben borrarse. Recuperamos sus 'name' antes de limpiar.
    sub_labels = set()
    for sub in db.query(Domain).filter(Domain.is_subdomain == True,  # noqa: E712
                                       Domain.parent_domain == zone.domain_name).all():
        sub_labels.add(subdomain_label(sub.domain_name, zone.domain_name))
    preserved = []
    if sub_labels:
        for r in db.query(DnsRecord).filter(DnsRecord.zone_id == zone_id).all():
            if r.name in sub_labels:
                preserved.append({"record_type": r.record_type, "name": r.name,
                                  "content": r.content, "ttl": r.ttl, "priority": r.priority})

    # Regenerar adopta los nameservers actuales del panel (SOA + registros NS)
    # y RESPETA la plantilla elegida en la zona (default/minimal/mail).
    zone.soa_ns = ns1
    db.query(DnsRecord).filter(DnsRecord.zone_id == zone_id).delete()
    for r in _build_template_records(zone.domain_name, ipv4, ipv6, ns1, ns2,
                                     template=zone.template,
                                     server_ipv6=_get_server_ipv6(db)):
        db.add(DnsRecord(zone_id=zone.id, **r))
    for r in preserved:  # re-añadir los registros de subdominios
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


def normalize_hostname_content(record_type: str, content: str) -> str:
    """Añade el punto final a los contenidos que son un FQDN (MX/CNAME/NS y el
    target de SRV). Función PURA.

    Sin el punto, BIND interpreta el valor como nombre RELATIVO a la zona y le
    pega el dominio detrás: un cliente que escribe `mail.sudominio.com` en un
    MX publica `mail.sudominio.com.sudominio.com.` (correo caído). Es un
    tecnicismo de ficheros de zona que el usuario final no tiene por qué
    conocer — lo corrige el editor, no el cliente. Un nombre SIN puntos
    (`mail`) se respeta: es un relativo válido y a veces intencionado.
    """
    c = (content or "").strip()
    rtype = (record_type or "").upper()

    def _fqdn_dot(value: str) -> str:
        if "." in value and not value.endswith("."):
            try:
                ipaddress.ip_address(value)   # una IP no lleva punto final
                return value
            except ValueError:
                return value + "."
        return value

    # Todos los tipos cuyo contenido es un hostname llevan la protección.
    if rtype in ("MX", "CNAME", "NS", "PTR", "DNAME"):
        return _fqdn_dot(c)
    if rtype == "SRV":
        # SRV: "peso puerto destino" (la prioridad va aparte) → el destino es
        # el último token.
        parts = c.split()
        if parts:
            parts[-1] = _fqdn_dot(parts[-1])
            return " ".join(parts)
    return c


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
        name=data.name,
        content=normalize_hostname_content(data.record_type, data.content),
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

    if data.content  is not None:
        record.content = normalize_hostname_content(record.record_type, data.content)
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


def find_parent_zone(db: Session, fqdn: str):
    """Devuelve la DnsZone padre de un FQDN si existe en el panel, o None.

    Para gestion.zococoria.es busca la zona más específica que sea sufijo:
    zococoria.es. Así un subdominio se cuelga de su zona real aunque haya varios
    niveles (a.b.zococoria.es → zona zococoria.es si b.zococoria.es no es zona)."""
    from api.models.models_dns import DnsZone
    labels = fqdn.split(".")
    # Probar sufijos cada vez más cortos: gestion.zococoria.es → zococoria.es → es
    for i in range(1, len(labels)):
        candidate = ".".join(labels[i:])
        z = db.query(DnsZone).filter(DnsZone.domain_name == candidate,
                                     DnsZone.is_active == True).first()  # noqa: E712
        if z:
            return z
    return None


def subdomain_label(fqdn: str, parent_domain: str) -> str:
    """'gestion.zococoria.es' + 'zococoria.es' → 'gestion' (la parte izquierda)."""
    if fqdn == parent_domain:
        return "@"
    suffix = "." + parent_domain
    return fqdn[:-len(suffix)] if fqdn.endswith(suffix) else fqdn


def apply_subdomain_dns(db: Session, fqdn: str, ipv4: str = None, ipv6: str = None) -> str:
    """DNS de un SUBDOMINIO. Si su zona padre vive en el panel, añade A/AAAA del
    subdominio DENTRO de esa zona (sin crear zona separada) y resincroniza.

    Devuelve: 'parent' si se añadió a la zona padre, 'own' si no hay padre en el
    panel (el caller debe crear zona propia como un dominio normal).
    """
    from api.models.models_dns import DnsRecord
    parent = find_parent_zone(db, fqdn)
    if not parent:
        return "own"  # padre no gestionada aquí → zona propia (comportamiento dominio)

    label = subdomain_label(fqdn, parent.domain_name)
    ipv4 = ipv4 or _get_server_ipv4(db)

    def _ensure(rtype, content):
        if not content:
            return
        exists = db.query(DnsRecord).filter(
            DnsRecord.zone_id == parent.id, DnsRecord.name == label,
            DnsRecord.record_type == rtype).first()
        if exists:
            exists.content = content
        else:
            db.add(DnsRecord(zone_id=parent.id, name=label, record_type=rtype,
                             content=content, ttl=parent.ttl or 14400, priority=0))

    _ensure("A", ipv4)
    _ensure("AAAA", ipv6)
    parent.serial = _bump_serial(parent.serial)
    db.commit()
    db.refresh(parent)
    try:
        _sync_zone_to_bind(parent, db)
    except Exception:
        pass
    return "parent"


def remove_subdomain_dns(db: Session, fqdn: str) -> bool:
    """Quita los registros A/AAAA de un subdominio de su zona padre (al borrarlo).
    Devuelve True si tocó algo."""
    from api.models.models_dns import DnsRecord
    parent = find_parent_zone(db, fqdn)
    if not parent:
        return False
    label = subdomain_label(fqdn, parent.domain_name)
    q = db.query(DnsRecord).filter(DnsRecord.zone_id == parent.id,
                                   DnsRecord.name == label)
    n = q.count()
    if n:
        q.delete()
        parent.serial = _bump_serial(parent.serial)
        db.commit()
        db.refresh(parent)
        try:
            _sync_zone_to_bind(parent, db)
        except Exception:
            pass
    return n > 0


def build_spf(ipv4, ipv6=None, *extra_ipv6) -> str:
    """Construye el registro SPF con ip4 e ip6 según disponibilidad.

    ipv6 y extra_ipv6 permiten declarar VARIAS IPv6 (p.ej. la global del servidor
    + la dedicada del dominio): el correo puede salir por cualquiera, así que
    todas deben estar en el SPF o Gmail dará SPF fail. Se deduplican y se ignoran
    los vacíos."""
    mechs = ["v=spf1", "a", "mx"]
    if ipv4:
        mechs.append(f"ip4:{ipv4}")
    seen6 = []
    for v6 in (ipv6, *extra_ipv6):
        v6 = (v6 or "").strip()
        if v6 and v6 not in seen6:
            seen6.append(v6)
            mechs.append(f"ip6:{v6}")
    mechs.append("-all")
    return " ".join(mechs)


def apply_ip6_to_spf(spf: str, ipv6) -> str:
    """Devuelve el SPF con el mecanismo ip6 añadido/actualizado o eliminado.

    Función PURA. Si ipv6 tiene valor, garantiza un único `ip6:<ipv6>` (justo
    antes del all final); si es None/"", elimina cualquier `ip6:...` existente.
    Mantiene el resto de mecanismos intactos. Idempotente.
    """
    if not spf or not spf.startswith("v=spf1"):
        return spf
    # Tokeniza y elimina cualquier ip6: previo y el mecanismo all final.
    tokens = spf.split()
    all_mech = "-all"
    body = []
    for t in tokens[1:]:
        if t.lower().startswith("ip6:"):
            continue
        if t in ("-all", "~all", "?all", "+all"):
            all_mech = t
            continue
        body.append(t)
    if ipv6:
        body.append(f"ip6:{ipv6}")
    return " ".join(["v=spf1"] + body + [all_mech])


def compute_aaaa_changes(existing: list, ipv6, own_ipv4s=None) -> dict:
    """Decide qué AAAA crear/actualizar/borrar para reflejar `ipv6`. Función PURA.

    `existing`: lista de dicts {"record_type","name","content"} de la zona.
    `own_ipv4s`: colección de IPv4 del PROPIO servidor/dominio. Solo los A que
    apuntan a una de ellas reciben AAAA paralelo: un A hacia una IP EXTERNA
    (sip, facturacion, oficina… típico en zonas importadas) NO debe ganar un
    AAAA nuestro — ese servicio vive en otra máquina y los clientes dual-stack
    acabarían conectando aquí por IPv6. None = todos los A (compat).
    Devuelve {"upsert": [(name, ipv6), ...], "delete_names": [name, ...]}:
      - upsert: nombres que deben tener AAAA con ese contenido (A→AAAA paralelo).
      - delete_names: nombres cuyo AAAA sobra (huérfano, desactivación de IPv6,
        o AAAA nuestro colgado de un A externo — artefacto del bug anterior).
    """
    aaaa = {r["name"]: r.get("content") for r in existing if r["record_type"] == "AAAA"}
    if not ipv6:
        # Desactivar: borrar todos los AAAA existentes.
        return {"upsert": [], "delete_names": sorted(aaaa.keys())}

    a_all = {r["name"]: r.get("content") for r in existing if r["record_type"] == "A"}
    if own_ipv4s:
        own = {ip for ip in own_ipv4s if ip}
        a_names = sorted(n for n, c in a_all.items() if c in own)
        external = {n for n, c in a_all.items() if c not in own}
    else:
        a_names = sorted(a_all.keys())
        external = set()
    upsert = [(n, ipv6) for n in a_names if aaaa.get(n) != ipv6]
    # Fuera: AAAA cuyo name ya no tiene A (huérfano) y AAAA con NUESTRA IPv6
    # colgado de un nombre cuyo A es externo (paridad rota: v4 allí, v6 aquí).
    delete_names = sorted(
        {n for n in aaaa if n not in a_all} |
        {n for n in external if aaaa.get(n) == ipv6}
    )
    return {"upsert": upsert, "delete_names": delete_names}


def sync_aaaa_records_for_domain(domain_name: str, ipv6, db: Session) -> dict:
    """Sincroniza los registros AAAA de la zona DNS de un dominio con su IPv6.

    Se invoca al asignar/quitar la IPv6 de un dominio para mantener el DNS
    coherente con la realidad del servidor:
      - ipv6 con valor  → crea/actualiza un AAAA por cada registro A existente
        (paridad IPv4/IPv6: típicamente @ y mail; www/ftp son CNAME y heredan).
      - ipv6 None/""    → elimina todos los AAAA de la zona.

    DEFENSIVO: si el panel NO gestiona la zona de ese dominio (DNS externo), es
    un no-op silencioso. Devuelve un dict con lo que hizo (para logging/respuesta).
    """
    zone = db.query(DnsZone).filter(DnsZone.domain_name == domain_name).first()
    if not zone:
        # DNS externo o sin zona en el panel → no tocamos nada.
        return {"managed": False, "added": 0, "removed": 0}

    existing = db.query(DnsRecord).filter(DnsRecord.zone_id == zone.id).all()
    existing_dicts = [
        {"record_type": r.record_type, "name": r.name, "content": r.content}
        for r in existing
    ]
    # IPs v4 "propias": la del dominio + la principal del servidor + todas las
    # registradas en el panel (ServerIP). Solo los A que apuntan a ellas llevan
    # AAAA paralelo; los A externos (zonas importadas) no se tocan.
    own_ips = set()
    try:
        from api.models.models_domain import Domain as _Domain
        d = db.query(_Domain).filter(_Domain.domain_name == domain_name).first()
        if d and d.ipv4:
            own_ips.add(d.ipv4)
    except Exception:
        pass
    try:
        ip4 = _get_server_ipv4(db)
        if ip4:
            own_ips.add(ip4)
    except Exception:
        pass
    try:
        from api.models.models_server_ip import ServerIP as _SIP
        for r in db.query(_SIP).filter(_SIP.is_ipv6 == False).all():  # noqa: E712
            own_ips.add(r.address)
    except Exception:
        pass
    plan = compute_aaaa_changes(existing_dicts, ipv6,
                                own_ipv4s=own_ips or None)
    aaaa_by_name = {r.name: r for r in existing if r.record_type == "AAAA"}
    added = removed = 0

    for name, content in plan["upsert"]:
        rec = aaaa_by_name.get(name)
        if rec is None:
            db.add(DnsRecord(
                zone_id=zone.id, record_type="AAAA",
                name=name, content=content, ttl=14400, priority=0,
            ))
        else:
            rec.content = content
        added += 1
    for name in plan["delete_names"]:
        rec = aaaa_by_name.get(name)
        if rec is not None:
            db.delete(rec)
            removed += 1

    # NOTA: esta función NO toca el SPF. Asignar IPv6 a un dominio es una decisión
    # de WEB/DNS (crea el AAAA), pero el SPF declara por dónde sale el CORREO, que
    # casi siempre es la IPv6 GLOBAL del servidor (con PTR), no la dedicada del
    # dominio. Meter la IPv6 dedicada en el SPF cuando el correo NO sale por ella
    # provocaba SPF fail en Gmail. El SPF lo gobierna la preferencia de salida de
    # correo (mail_out_ip_pref) → set_domain_out_ip / regenerate_zone / backfill.
    spf_updated = False
    if added or removed:
        zone.serial = _bump_serial(zone.serial)
        db.commit()
        _sync_zone_to_bind(zone, db)

    return {"managed": True, "added": added, "removed": removed, "spf_updated": spf_updated}


# Plantillas DNS disponibles (clave interna → contenido). El frontend ofrece
# estas mismas. 'default' = completa (compat: zonas viejas que tengan 'minimal'
# o 'mail' caen en su equivalente más cercano vía _TEMPLATE_ALIASES).
DNS_TEMPLATES = ("web", "mail", "dns", "default")
_TEMPLATE_ALIASES = {"minimal": "dns", "full": "default", "complete": "default"}


def _build_template_records(domain: str, ipv4: str, ipv6: str = None,
                            ns1: str = None, ns2: str = None,
                            template: str = "default",
                            server_ipv6: str = None) -> list:
    """
    Registros de una zona según la plantilla elegida:
      - dns:     NS×2 + A/AAAA(@). Zona mínima para resolver el dominio.
      - web:     dns + CNAME www. Sitio web sin correo.
      - mail:    NS×2 + A/AAAA(mail) + MX + SPF + DMARC + CNAME webmail. Solo correo.
      - default: TODO (web + correo + SRV + CAA). La plantilla completa.
    ns1/ns2: nameservers del panel (de get_panel_nameservers).
    server_ipv6: IPv6 GLOBAL de salida del correo del servidor. VA en el SPF
      además de la IPv6 del dominio: si el correo sale por la IPv6 global pero el
      SPF no la lista → SPF fail en Gmail. (ipv6 = dedicada del dominio, opcional.)
    """
    from scripts.dns_manager import DEFAULT_NS1, DEFAULT_NS2
    ns1 = (ns1 or DEFAULT_NS1).rstrip(".")
    ns2 = (ns2 or DEFAULT_NS2).rstrip(".")
    template = (template or "default").lower()
    template = _TEMPLATE_ALIASES.get(template, template)
    if template not in DNS_TEMPLATES:
        template = "default"
    records = []

    def add(rtype, name, content, ttl=14400, prio=0):
        records.append({"record_type": rtype, "name": name, "content": content,
                        "ttl": ttl, "priority": prio})

    # NS (en todas las plantillas)
    add("NS", "@", f"{ns1}.", 86400)
    add("NS", "@", f"{ns2}.", 86400)

    # ── Solo DNS: NS + A/AAAA del dominio raíz ──
    if template in ("dns", "web", "default"):
        if ipv4:
            add("A", "@", ipv4)
        if ipv6:
            add("AAAA", "@", ipv6)

    if template == "dns":
        return records

    # ── Solo web: + CNAME www ──
    if template == "web":
        add("CNAME", "www", f"{domain}.")
        return records

    # A/AAAA de mail (mail y default)
    if ipv4:
        add("A", "mail", ipv4)
    if ipv6:
        add("AAAA", "mail", ipv6)

    # ── Solo correo: A(mail) + MX + SPF + DMARC + CNAME webmail (sin web) ──
    if template == "mail":
        add("MX", "@", f"mail.{domain}.")
        # SPF: IPv6 global del servidor (por donde sale el correo) + la dedicada
        # del dominio si tiene. Sin la global, el correo por IPv6 daría SPF fail.
        add("TXT", "@", build_spf(ipv4, server_ipv6, ipv6))
        add("TXT", "_dmarc", "v=DMARC1; p=quarantine; pct=100")
        add("CNAME", "webmail", f"mail.{domain}.")
        return records

    # ── default: la plantilla COMPLETA (web + correo) ──
    add("CNAME", "www",     f"{domain}.")
    add("CNAME", "ftp",     f"{domain}.")
    add("CNAME", "webmail", f"mail.{domain}.")
    add("MX", "@", f"mail.{domain}.")
    add("TXT", "@",      build_spf(ipv4, server_ipv6, ipv6))
    add("TXT", "_dmarc", "v=DMARC1; p=quarantine; pct=100")
    add("SRV", "_submission._tcp", f"0 587 mail.{domain}.", prio=1)
    add("SRV", "_imap._tcp",       f"0 143 mail.{domain}.", prio=1)
    add("SRV", "_imaps._tcp",      f"0 993 mail.{domain}.", prio=1)
    add("SRV", "_pop3._tcp",       f"0 110 mail.{domain}.", prio=1)
    add("SRV", "_pop3s._tcp",      f"0 995 mail.{domain}.", prio=1)

    # CAA — solo Let's Encrypt puede emitir certs (normales y wildcard) para el
    # dominio. El panel emite todo con LE, así que esto no rompe renovaciones y
    # bloquea que cualquier otra CA emita un cert (por error o por ataque).
    records.extend(CAA_TEMPLATE_RECORDS())

    return records


def CAA_TEMPLATE_RECORDS() -> list:
    """Registros CAA por defecto: autoriza SOLO a Let's Encrypt (issue+issuewild)."""
    return [
        {"record_type": "CAA", "name": "@", "content": '0 issue "letsencrypt.org"',     "ttl": 14400, "priority": 0},
        {"record_type": "CAA", "name": "@", "content": '0 issuewild "letsencrypt.org"', "ttl": 14400, "priority": 0},
    ]
