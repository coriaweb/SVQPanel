"""
Rutas API para despliegue Git por dominio (con autenticación).

El endpoint público del webhook vive en git_webhook.py (sin auth).
Toda operación de disco la hace scripts/git_manager.GitManager como el usuario
dueño del dominio.
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.models.database import get_db
from api.models.models_user import User
from api.models.models_domain import Domain
from api.models.models_git import GitDeployment
from api.dependencies import require_auth
from scripts.git_manager import (
    GitManager, GitError, validate_repo_url, sanitize_ref, gen_webhook_token,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _get_owned_domain(domain_id: int, db: Session, current_user: User) -> Domain:
    """Carga un dominio verificando acceso (anti-IDOR). Mismo criterio que domains.py."""
    dom = db.query(Domain).filter(Domain.id == domain_id).first()
    if not dom:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    role = getattr(current_user, "role", None)
    if role == "admin":
        return dom
    if role == "reseller":
        client_ids = [u.id for u in db.query(User.id).filter(User.parent_id == current_user.id).all()]
        client_ids.append(current_user.id)
        if dom.user_id in client_ids:
            return dom
    elif dom.user_id == current_user.id:
        return dom
    raise HTTPException(status_code=404, detail="Dominio no encontrado")


def _owner(dom: Domain, db: Session) -> User:
    owner = db.query(User).filter(User.id == dom.user_id).first()
    if not owner:
        raise HTTPException(status_code=500, detail="Propietario del dominio no encontrado")
    return owner


def _webhook_url(dom: Domain) -> str:
    if not dom.git_webhook_token:
        return ""
    return f"https://{dom.domain_name}/git/webhook/{dom.git_webhook_token}"


def _record_deployment(db: Session, dom: Domain, result: dict, trigger: str,
                       status_str: str = "success"):
    rec = GitDeployment(
        domain_id=dom.id,
        commit_sha=result.get("commit_sha"),
        commit_msg=result.get("commit_msg"),
        branch=result.get("branch"),
        ref=result.get("branch"),
        release_dir=result.get("release_dir"),
        status=status_str,
        trigger=trigger,
        build_log=result.get("build_log"),
    )
    db.add(rec)
    db.commit()
    return rec


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────
class GitSetupRequest(BaseModel):
    repo_url: str
    branch: str = "main"
    provider: str = "github"
    build_commands: str = ""
    keep_releases: int = 5


class GitUpdateRequest(BaseModel):
    branch: Optional[str] = None
    build_commands: Optional[str] = None
    keep_releases: Optional[int] = None


class GitRollbackRequest(BaseModel):
    release_name: str


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────
def _status_payload(dom: Domain, db: Session) -> dict:
    owner = _owner(dom, db)
    mgr = GitManager()
    disk = {}
    try:
        disk = mgr.status(owner.username, dom.domain_name)
    except Exception as e:
        logger.warning(f"git status disk falló para {dom.domain_name}: {e}")
    last = (db.query(GitDeployment)
              .filter(GitDeployment.domain_id == dom.id)
              .order_by(GitDeployment.created_at.desc())
              .first())
    return {
        "enabled": bool(dom.git_enabled),
        "repo_url": dom.git_repo_url,
        "branch": dom.git_branch,
        "provider": dom.git_provider,
        "build_commands": dom.git_build_commands or "",
        "keep_releases": dom.git_keep_releases,
        "deploy_key_pub": dom.git_deploy_key_pub or disk.get("deploy_key_pub", ""),
        "webhook_url": _webhook_url(dom),
        "active_release": disk.get("active_release", ""),
        "releases": disk.get("releases", []),
        "public_html_is_symlink": disk.get("public_html_is_symlink", False),
        "last_deployment": {
            "commit_sha": last.commit_sha, "commit_msg": last.commit_msg,
            "status": last.status, "trigger": last.trigger,
            "created_at": last.created_at.isoformat() if last.created_at else None,
        } if last else None,
    }


@router.get("/git/domains/{domain_id}")
async def git_status(domain_id: int, current_user: User = Depends(require_auth),
                     db: Session = Depends(get_db)):
    dom = _get_owned_domain(domain_id, db, current_user)
    return {"status": "success", "data": _status_payload(dom, db)}


@router.post("/git/domains/{domain_id}/deploy-key")
async def git_gen_deploy_key(domain_id: int, current_user: User = Depends(require_auth),
                             db: Session = Depends(get_db)):
    dom = _get_owned_domain(domain_id, db, current_user)
    owner = _owner(dom, db)
    try:
        pub = GitManager().gen_deploy_key(owner.username, dom.domain_name)
    except GitError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Se necesitan permisos para generar la clave")
    dom.git_deploy_key_pub = pub
    db.commit()
    return {"status": "success", "deploy_key_pub": pub}


@router.post("/git/domains/{domain_id}/setup")
async def git_setup(domain_id: int, data: GitSetupRequest,
                    current_user: User = Depends(require_auth),
                    db: Session = Depends(get_db)):
    dom = _get_owned_domain(domain_id, db, current_user)
    owner = _owner(dom, db)
    try:
        repo_url = validate_repo_url(data.repo_url)
        branch = sanitize_ref(data.branch)
    except GitError as e:
        raise HTTPException(status_code=422, detail=str(e))

    keep = max(1, min(int(data.keep_releases or 5), 30))
    token = dom.git_webhook_token or gen_webhook_token()

    mgr = GitManager()
    try:
        result = mgr.setup(owner.username, dom.domain_name, repo_url, branch,
                           build_commands=data.build_commands or "", keep=keep)
    except GitError as e:
        # Error de usuario (repo inválido, dir no vacío, build falló)
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"git setup falló para {dom.domain_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Error desplegando: {e}")

    dom.git_enabled = True
    dom.git_repo_url = repo_url
    dom.git_branch = branch
    dom.git_provider = (data.provider or "github")[:20]
    dom.git_build_commands = data.build_commands or ""
    dom.git_keep_releases = keep
    dom.git_webhook_token = token
    db.commit()
    _record_deployment(db, dom, result, trigger="initial")
    return {"status": "success", "data": _status_payload(dom, db),
            "message": "Repositorio desplegado correctamente"}


@router.put("/git/domains/{domain_id}")
async def git_update(domain_id: int, data: GitUpdateRequest,
                     current_user: User = Depends(require_auth),
                     db: Session = Depends(get_db)):
    dom = _get_owned_domain(domain_id, db, current_user)
    if not dom.git_enabled:
        raise HTTPException(status_code=400, detail="El despliegue Git no está activo")
    if data.branch is not None:
        try:
            dom.git_branch = sanitize_ref(data.branch)
        except GitError as e:
            raise HTTPException(status_code=422, detail=str(e))
    if data.build_commands is not None:
        dom.git_build_commands = data.build_commands
    if data.keep_releases is not None:
        dom.git_keep_releases = max(1, min(int(data.keep_releases), 30))
    db.commit()
    return {"status": "success", "data": _status_payload(dom, db)}


@router.post("/git/domains/{domain_id}/deploy")
async def git_deploy(domain_id: int, current_user: User = Depends(require_auth),
                     db: Session = Depends(get_db)):
    dom = _get_owned_domain(domain_id, db, current_user)
    if not dom.git_enabled:
        raise HTTPException(status_code=400, detail="El despliegue Git no está activo")
    owner = _owner(dom, db)
    try:
        result = GitManager().deploy(
            owner.username, dom.domain_name, branch=dom.git_branch or "main",
            build_commands=dom.git_build_commands or "",
            keep=dom.git_keep_releases or 5, trigger="manual",
        )
    except GitError as e:
        # Registrar el fallo para que se vea en el historial
        _record_deployment(db, dom, {"branch": dom.git_branch}, trigger="manual",
                           status_str="failed")
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"git deploy falló para {dom.domain_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Error desplegando: {e}")
    _record_deployment(db, dom, result, trigger="manual")
    return {"status": "success", "data": _status_payload(dom, db),
            "message": "Despliegue completado"}


@router.post("/git/domains/{domain_id}/rollback")
async def git_rollback(domain_id: int, data: GitRollbackRequest,
                       current_user: User = Depends(require_auth),
                       db: Session = Depends(get_db)):
    dom = _get_owned_domain(domain_id, db, current_user)
    if not dom.git_enabled:
        raise HTTPException(status_code=400, detail="El despliegue Git no está activo")
    owner = _owner(dom, db)
    try:
        result = GitManager().rollback(owner.username, dom.domain_name, data.release_name)
    except GitError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"git rollback falló para {dom.domain_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Error en rollback: {e}")
    # El rollback no resuelve commit/branch nuevos; registramos la release destino
    rec = GitDeployment(domain_id=dom.id, release_dir=result.get("release_dir"),
                        branch=dom.git_branch, status="success", trigger="rollback",
                        commit_msg=f"Rollback a {data.release_name}")
    db.add(rec)
    db.commit()
    return {"status": "success", "data": _status_payload(dom, db),
            "message": f"Rollback a {data.release_name} completado"}


@router.get("/git/domains/{domain_id}/deployments")
async def git_deployments(domain_id: int, current_user: User = Depends(require_auth),
                          db: Session = Depends(get_db)):
    dom = _get_owned_domain(domain_id, db, current_user)
    rows = (db.query(GitDeployment)
              .filter(GitDeployment.domain_id == dom.id)
              .order_by(GitDeployment.created_at.desc())
              .limit(50).all())
    return {"status": "success", "data": [{
        "id": r.id, "commit_sha": r.commit_sha, "commit_msg": r.commit_msg,
        "branch": r.branch, "release_dir": r.release_dir,
        "release_name": (r.release_dir or "").rsplit("/", 1)[-1],
        "status": r.status, "trigger": r.trigger,
        "build_log": r.build_log,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]}


@router.delete("/git/domains/{domain_id}")
async def git_disable(domain_id: int, current_user: User = Depends(require_auth),
                      db: Session = Depends(get_db)):
    dom = _get_owned_domain(domain_id, db, current_user)
    owner = _owner(dom, db)
    try:
        GitManager().disable(owner.username, dom.domain_name, restore_files=True)
    except Exception as e:
        logger.warning(f"git disable (restore) falló para {dom.domain_name}: {e}")
    dom.git_enabled = False
    dom.git_webhook_token = None
    db.commit()
    return {"status": "success", "message": "Despliegue Git desactivado"}
