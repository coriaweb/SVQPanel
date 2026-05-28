"""
Rutas API para gestión de IPs del servidor
"""

import ipaddress
import subprocess
import re
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.models.database import get_db
from api.models.models_server_ip import ServerIP
from api.models.models_domain import Domain
from api.models.models_user import User
from api.schemas.server_ip_schemas import (
    ServerIPCreate, ServerIPUpdate, ServerIPResponse, SystemIPInfo
)
from api.dependencies import require_admin, require_auth

router = APIRouter()


def _is_ipv6(address: str) -> bool:
    try:
        ipaddress.IPv6Address(address)
        return True
    except ValueError:
        return False


def _count_domains(db: Session, ip: ServerIP) -> int:
    """Cuenta dominios que usan esta IP (IPv4 o IPv6)."""
    if ip.is_ipv6:
        return db.query(Domain).filter(Domain.ipv6 == ip.address).count()
    return db.query(Domain).filter(Domain.ipv4 == ip.address).count()


def _to_response(db: Session, ip: ServerIP) -> ServerIPResponse:
    owner_username = None
    if ip.owner_user_id:
        owner = db.query(User).filter(User.id == ip.owner_user_id).first()
        owner_username = owner.username if owner else None
    return ServerIPResponse(
        id=ip.id,
        address=ip.address,
        netmask=ip.netmask,
        interface=ip.interface,
        ip_type=ip.ip_type,
        is_ipv6=ip.is_ipv6,
        nat_ip=ip.nat_ip,
        owner_user_id=ip.owner_user_id,
        owner_username=owner_username,
        is_active=ip.is_active,
        note=ip.note,
        domains_count=_count_domains(db, ip),
        created_at=ip.created_at,
        updated_at=ip.updated_at,
    )


# ─── GET all ─────────────────────────────────────────────────────────────────

@router.get("/server-ips", response_model=List[ServerIPResponse])
async def list_server_ips(
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Lista todas las IPs registradas en el panel."""
    ips = db.query(ServerIP).order_by(ServerIP.is_ipv6, ServerIP.address).all()
    return [_to_response(db, ip) for ip in ips]


@router.get("/server-ips/available", response_model=List[ServerIPResponse])
async def list_available_ips(
    current_user=Depends(require_auth),
    db: Session = Depends(get_db),
):
    """
    Lista las IPs IPv4 activas del servidor disponibles para asignar a dominios.
    Accesible para cualquier usuario autenticado (para el selector en DomainForm).
    """
    ips = (
        db.query(ServerIP)
        .filter(ServerIP.is_ipv6 == False, ServerIP.is_active == True)  # noqa: E712
        .order_by(ServerIP.address)
        .all()
    )
    return [_to_response(db, ip) for ip in ips]


# ─── GET system IPs ───────────────────────────────────────────────────────────

@router.get("/server-ips/system", response_model=List[SystemIPInfo])
async def scan_system_ips(
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Detecta las IPs asignadas al sistema operativo via 'ip addr show'.
    Marca cuáles ya están registradas en la BD.
    Excluye loopback y link-local.
    """
    result: List[SystemIPInfo] = []
    registered_addrs = {r.address for r in db.query(ServerIP.address).all()}

    try:
        proc = subprocess.run(
            ["/sbin/ip", "-o", "addr", "show"],
            capture_output=True, text=True, timeout=10,
        )
        lines = proc.stdout.splitlines()
    except Exception:
        # fallback sin error
        return []

    # Formato: "2: eth0    inet 185.104.188.71/24 brd ..."
    # o:       "2: eth0    inet6 2a01:db8::1/64 scope global"
    for line in lines:
        parts = line.split()
        if len(parts) < 4:
            continue
        iface = parts[1].rstrip(":")
        family = parts[2]   # inet | inet6
        cidr = parts[3]     # addr/prefix

        if family not in ("inet", "inet6"):
            continue

        addr, _, prefix = cidr.partition("/")

        # Saltar loopback
        if iface in ("lo", "lo0") or addr.startswith("127.") or addr == "::1":
            continue

        # Saltar link-local IPv6 (fe80::)
        if addr.lower().startswith("fe80"):
            continue

        ipv6 = (family == "inet6")
        netmask = f"/{prefix}" if prefix else None

        result.append(SystemIPInfo(
            address=addr,
            netmask=netmask,
            interface=iface,
            is_ipv6=ipv6,
            registered=(addr in registered_addrs),
        ))

    return result


# ─── POST ─────────────────────────────────────────────────────────────────────

@router.post("/server-ips", response_model=ServerIPResponse, status_code=201)
async def create_server_ip(
    data: ServerIPCreate,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Registra una nueva IP en el panel."""
    existing = db.query(ServerIP).filter(ServerIP.address == data.address).first()
    if existing:
        raise HTTPException(status_code=409, detail="Esta dirección IP ya está registrada")

    ip = ServerIP(
        address=data.address,
        netmask=data.netmask,
        interface=data.interface,
        ip_type=data.ip_type,
        is_ipv6=_is_ipv6(data.address),
        nat_ip=data.nat_ip,
        owner_user_id=data.owner_user_id,
        is_active=data.is_active,
        note=data.note,
    )
    db.add(ip)
    db.commit()
    db.refresh(ip)
    return _to_response(db, ip)


# ─── GET one ──────────────────────────────────────────────────────────────────

@router.get("/server-ips/{ip_id}", response_model=ServerIPResponse)
async def get_server_ip(
    ip_id: int,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    ip = db.query(ServerIP).filter(ServerIP.id == ip_id).first()
    if not ip:
        raise HTTPException(status_code=404, detail="IP no encontrada")
    return _to_response(db, ip)


# ─── PUT ──────────────────────────────────────────────────────────────────────

@router.put("/server-ips/{ip_id}", response_model=ServerIPResponse)
async def update_server_ip(
    ip_id: int,
    data: ServerIPUpdate,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    ip = db.query(ServerIP).filter(ServerIP.id == ip_id).first()
    if not ip:
        raise HTTPException(status_code=404, detail="IP no encontrada")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(ip, field, value)

    db.commit()
    db.refresh(ip)
    return _to_response(db, ip)


# ─── DELETE ───────────────────────────────────────────────────────────────────

@router.delete("/server-ips/{ip_id}", status_code=204)
async def delete_server_ip(
    ip_id: int,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    ip = db.query(ServerIP).filter(ServerIP.id == ip_id).first()
    if not ip:
        raise HTTPException(status_code=404, detail="IP no encontrada")

    if _count_domains(db, ip) > 0:
        raise HTTPException(
            status_code=409,
            detail="No se puede eliminar: hay dominios usando esta IP. "
                   "Reasigna los dominios primero.",
        )

    db.delete(ip)
    db.commit()
