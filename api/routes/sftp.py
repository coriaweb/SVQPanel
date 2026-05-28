"""
Rutas API — SFTP (Fase 14.2)

Permite a admin, reseller (sobre sus clientes) y al propio usuario gestionar
su acceso SFTP: activar/desactivar, cambiar password Linux y manejar claves
SSH públicas en authorized_keys.
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.models.database import get_db
from api.models.models_user import User
from api.models.models_sftp_account import SftpAccount
from api.dependencies import get_current_user
from api.utils.security_audit import log_audit
from scripts import sftp_manager, sftp_account_manager as sftpacc

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────
class SftpEnableRequest(BaseModel):
    enabled: bool


class SftpPasswordRequest(BaseModel):
    password: str = Field(..., min_length=8, max_length=128)


class SshKeyAddRequest(BaseModel):
    public_key: str = Field(..., min_length=20, max_length=8192)


class SftpAccountCreate(BaseModel):
    label:          str = Field(..., min_length=2, max_length=16)
    target_subpath: str = Field(..., max_length=512)
    password:       Optional[str] = Field(None, min_length=8, max_length=128)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de autorización
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_target(user_id: int, actor: User, db: Session) -> User:
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if not actor.can_manage_user(target):
        raise HTTPException(status_code=403, detail="No puedes gestionar este usuario")
    if target.role == "admin":
        raise HTTPException(status_code=400, detail="Admin no usa SFTP-only (mantiene shell)")
    return target


# ─────────────────────────────────────────────────────────────────────────────
# Estado
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/users/{user_id}/sftp")
async def get_sftp_status(
    user_id: int,
    db:      Session = Depends(get_db),
    actor:   User    = Depends(get_current_user),
):
    target = _resolve_target(user_id, actor, db)
    keys = sftp_manager.list_ssh_keys(target.username)
    return {
        "username":             target.username,
        "enabled":              target.sftp_enabled,
        "password_set_at":      target.sftp_password_set_at,
        "ssh_keys":             keys,
        "ssh_keys_count":       len(keys),
        "home_dir":             sftp_manager.home_dir(target.username),
        "chroot_to":            sftp_manager.home_dir(target.username),
        "writable_dirs":        [f"/home/{target.username}/web",
                                  f"/home/{target.username}/files"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Enable / disable
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/users/{user_id}/sftp/enable")
async def set_sftp_enabled(
    user_id: int,
    payload: SftpEnableRequest,
    request: Request,
    db:      Session = Depends(get_db),
    actor:   User    = Depends(get_current_user),
):
    target = _resolve_target(user_id, actor, db)

    if payload.enabled:
        # Asegurar que el grupo + snippet sshd existen (idempotente)
        ok, msg = sftp_manager.ensure_sftp_group()
        if not ok:
            raise HTTPException(status_code=500, detail=f"grupo sftponly: {msg}")
        ok, msg = sftp_manager.ensure_sshd_snippet()
        if not ok:
            raise HTTPException(status_code=500, detail=f"sshd snippet: {msg}")
        ok, msg = sftp_manager.enable_sftp(target.username)
        if not ok:
            raise HTTPException(status_code=500, detail=f"enable_sftp: {msg}")
    else:
        ok, msg = sftp_manager.disable_sftp(target.username)
        if not ok:
            raise HTTPException(status_code=500, detail=f"disable_sftp: {msg}")

    target.sftp_enabled = payload.enabled
    db.commit()

    log_audit(db, user=actor, category="sftp",
              action="enable" if payload.enabled else "disable",
              target=target.username, request=request, success=True)
    return {"status": "ok", "enabled": target.sftp_enabled, "msg": msg}


# ─────────────────────────────────────────────────────────────────────────────
# Password (Linux account)
# ─────────────────────────────────────────────────────────────────────────────
@router.put("/users/{user_id}/sftp/password")
async def set_sftp_password(
    user_id: int,
    payload: SftpPasswordRequest,
    request: Request,
    db:      Session = Depends(get_db),
    actor:   User    = Depends(get_current_user),
):
    target = _resolve_target(user_id, actor, db)
    ok, msg = sftp_manager.set_password(target.username, payload.password)
    if not ok:
        raise HTTPException(status_code=500, detail=f"chpasswd: {msg}")

    target.sftp_password_set_at = datetime.utcnow()
    db.commit()

    log_audit(db, user=actor, category="sftp", action="set_password",
              target=target.username, request=request, success=True)
    return {"status": "ok", "set_at": target.sftp_password_set_at}


# ─────────────────────────────────────────────────────────────────────────────
# SSH keys
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/users/{user_id}/sftp/keys")
async def list_keys(
    user_id: int,
    db:      Session = Depends(get_db),
    actor:   User    = Depends(get_current_user),
):
    target = _resolve_target(user_id, actor, db)
    return sftp_manager.list_ssh_keys(target.username)


@router.post("/users/{user_id}/sftp/keys")
async def add_key(
    user_id: int,
    payload: SshKeyAddRequest,
    request: Request,
    db:      Session = Depends(get_db),
    actor:   User    = Depends(get_current_user),
):
    target = _resolve_target(user_id, actor, db)
    ok, msg, fp = sftp_manager.add_ssh_key(target.username, payload.public_key)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    # Refrescar contador
    target.ssh_keys_count = len(sftp_manager.list_ssh_keys(target.username))
    db.commit()

    log_audit(db, user=actor, category="sftp", action="add_key",
              target=f"{target.username} {fp}", request=request, success=True)
    return {"status": "added", "fingerprint": fp}


@router.delete("/users/{user_id}/sftp/keys/{fingerprint:path}")
async def delete_key(
    user_id:     int,
    fingerprint: str,
    request:     Request,
    db:          Session = Depends(get_db),
    actor:       User    = Depends(get_current_user),
):
    target = _resolve_target(user_id, actor, db)
    ok, msg = sftp_manager.remove_ssh_key(target.username, fingerprint)
    if not ok:
        raise HTTPException(status_code=404, detail=msg)

    target.ssh_keys_count = len(sftp_manager.list_ssh_keys(target.username))
    db.commit()

    log_audit(db, user=actor, category="sftp", action="delete_key",
              target=f"{target.username} {fingerprint}", request=request, success=True)
    return {"status": "removed"}


# ═════════════════════════════════════════════════════════════════════════════
# Cuentas SFTP adicionales (subcuentas con jaula estricta)
# ═════════════════════════════════════════════════════════════════════════════
def _account_or_404(db: Session, owner: User, account_id: int) -> SftpAccount:
    acc = db.query(SftpAccount).filter(
        SftpAccount.id == account_id, SftpAccount.owner_id == owner.id
    ).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Subcuenta no encontrada")
    return acc


@router.get("/users/{user_id}/sftp/folders")
async def list_target_folders(
    user_id: int,
    db:      Session = Depends(get_db),
    actor:   User    = Depends(get_current_user),
):
    """
    Carpetas candidatas (relativas al home) para enjaular una subcuenta:
    raíz de cada dominio, su public_html, y la carpeta files.
    """
    import os
    target = _resolve_target(user_id, actor, db)
    home = sftpacc.owner_home(target.username)
    folders: List[str] = []

    web = os.path.join(home, "web")
    if os.path.isdir(web):
        for entry in sorted(os.scandir(web), key=lambda e: e.name):
            if entry.is_dir(follow_symlinks=False):
                folders.append(f"web/{entry.name}")
                ph = os.path.join(entry.path, "public_html")
                if os.path.isdir(ph):
                    folders.append(f"web/{entry.name}/public_html")
    if os.path.isdir(os.path.join(home, "files")):
        folders.append("files")

    return {"home": home, "folders": folders}


@router.get("/users/{user_id}/sftp/accounts")
async def list_sftp_accounts(
    user_id: int,
    db:      Session = Depends(get_db),
    actor:   User    = Depends(get_current_user),
):
    target = _resolve_target(user_id, actor, db)
    accounts = db.query(SftpAccount).filter(SftpAccount.owner_id == target.id).all()
    out = []
    for a in accounts:
        out.append({
            "id":              a.id,
            "username":        a.username,
            "label":           a.label,
            "target_path":     a.target_path,
            "target_relative": a.target_path.replace(sftpacc.owner_home(target.username) + "/", ""),
            "password_set_at": a.password_set_at,
            "ssh_keys":        sftpacc.list_keys(a.jail_path, a.username),
            "created_at":      a.created_at,
        })
    return out


@router.post("/users/{user_id}/sftp/accounts")
async def create_sftp_account(
    user_id: int,
    payload: SftpAccountCreate,
    request: Request,
    db:      Session = Depends(get_db),
    actor:   User    = Depends(get_current_user),
):
    target = _resolve_target(user_id, actor, db)

    # username único previsible
    username = sftpacc.make_username(target.username, payload.label)
    if db.query(SftpAccount).filter(SftpAccount.username == username).first():
        raise HTTPException(status_code=409, detail=f"Ya existe una subcuenta '{payload.label}'")

    ok, msg, info = sftpacc.create_account(
        owner=target.username,
        label=payload.label,
        target_subpath=payload.target_subpath,
        password=payload.password,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    acc = SftpAccount(
        owner_id=target.id,
        username=info["username"],
        label=payload.label,
        target_path=info["target_path"],
        jail_path=info["jail_path"],
        mount_name=info["mount_name"],
    )
    if payload.password:
        from datetime import datetime
        acc.password_set_at = datetime.utcnow()
    db.add(acc)
    db.commit()
    db.refresh(acc)

    log_audit(db, user=actor, category="sftp", action="create_subaccount",
              target=f"{info['username']} → {info['target_path']}", request=request, success=True)
    return {"status": "created", "id": acc.id, "username": acc.username,
            "target_path": acc.target_path}


@router.delete("/users/{user_id}/sftp/accounts/{account_id}")
async def delete_sftp_account(
    user_id:    int,
    account_id: int,
    request:    Request,
    db:         Session = Depends(get_db),
    actor:      User    = Depends(get_current_user),
):
    target = _resolve_target(user_id, actor, db)
    acc = _account_or_404(db, target, account_id)

    sftpacc.delete_account(target.username, acc.username, acc.jail_path,
                           acc.target_path, acc.mount_name)
    db.delete(acc)
    db.commit()

    log_audit(db, user=actor, category="sftp", action="delete_subaccount",
              target=acc.username, request=request, success=True)
    return {"status": "deleted"}


@router.put("/users/{user_id}/sftp/accounts/{account_id}/password")
async def set_sftp_account_password(
    user_id:    int,
    account_id: int,
    payload:    SftpPasswordRequest,
    request:    Request,
    db:         Session = Depends(get_db),
    actor:      User    = Depends(get_current_user),
):
    target = _resolve_target(user_id, actor, db)
    acc = _account_or_404(db, target, account_id)
    ok, msg = sftpacc.set_password(acc.username, payload.password)
    if not ok:
        raise HTTPException(status_code=500, detail=f"chpasswd: {msg}")
    from datetime import datetime
    acc.password_set_at = datetime.utcnow()
    db.commit()
    log_audit(db, user=actor, category="sftp", action="subaccount_password",
              target=acc.username, request=request, success=True)
    return {"status": "ok"}


@router.post("/users/{user_id}/sftp/accounts/{account_id}/keys")
async def add_sftp_account_key(
    user_id:    int,
    account_id: int,
    payload:    SshKeyAddRequest,
    request:    Request,
    db:         Session = Depends(get_db),
    actor:      User    = Depends(get_current_user),
):
    target = _resolve_target(user_id, actor, db)
    acc = _account_or_404(db, target, account_id)
    ok, msg, fp = sftpacc.add_key(acc.jail_path, acc.username, payload.public_key)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    acc.ssh_keys_count = len(sftpacc.list_keys(acc.jail_path, acc.username))
    db.commit()
    log_audit(db, user=actor, category="sftp", action="subaccount_add_key",
              target=f"{acc.username} {fp}", request=request, success=True)
    return {"status": "added", "fingerprint": fp}


@router.delete("/users/{user_id}/sftp/accounts/{account_id}/keys/{fingerprint:path}")
async def delete_sftp_account_key(
    user_id:     int,
    account_id:  int,
    fingerprint: str,
    request:     Request,
    db:          Session = Depends(get_db),
    actor:       User    = Depends(get_current_user),
):
    target = _resolve_target(user_id, actor, db)
    acc = _account_or_404(db, target, account_id)
    ok, msg = sftpacc.remove_key(acc.jail_path, acc.username, fingerprint)
    if not ok:
        raise HTTPException(status_code=404, detail=msg)
    acc.ssh_keys_count = len(sftpacc.list_keys(acc.jail_path, acc.username))
    db.commit()
    log_audit(db, user=actor, category="sftp", action="subaccount_delete_key",
              target=f"{acc.username} {fingerprint}", request=request, success=True)
    return {"status": "removed"}
