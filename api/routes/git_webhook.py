"""
Endpoint público del webhook de despliegue Git (SIN autenticación).

Se monta con prefix="" e include_in_schema=False, igual que el router de
autoconfig de correo, porque GitHub/GitLab llaman a una URL fija del dominio:
    POST https://{dominio}/git/webhook/{token}

Seguridad:
  - El {token} identifica el dominio (columna domains.git_webhook_token, índice).
  - Se valida la firma del proveedor:
      GitHub  → X-Hub-Signature-256: sha256=<hmac(token, body)>
      GitLab  → X-Gitlab-Token: <token>
    El secreto del HMAC/token es el propio git_webhook_token.
  - Solo se despliega si el push es a la rama configurada (payload ref).
  - El deploy corre en BackgroundTask para responder 200 rápido (GitHub corta a
    los 10s) y no bloquear al proveedor.
"""

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask

from api.models.database import SessionLocal
from api.models.models_domain import Domain
from api.models.models_user import User
from api.models.models_git import GitDeployment
from scripts.git_manager import GitManager, GitError

logger = logging.getLogger(__name__)
router = APIRouter()


def _verify_signature(domain: Domain, body: bytes, headers) -> bool:
    """Verifica la firma del proveedor con git_webhook_token como secreto."""
    token = (domain.git_webhook_token or "").encode()
    if not token:
        return False
    # GitHub: HMAC-SHA256 del body
    gh_sig = headers.get("x-hub-signature-256", "")
    if gh_sig.startswith("sha256="):
        expected = "sha256=" + hmac.new(token, body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, gh_sig)
    # GitLab: token plano en cabecera
    gl_tok = headers.get("x-gitlab-token", "")
    if gl_tok:
        return hmac.compare_digest(gl_tok, domain.git_webhook_token or "")
    # Genérico: sin firma configurada no aceptamos (evita disparos anónimos)
    return False


def _extract_ref(body: bytes) -> str:
    """Saca el 'ref' del payload (refs/heads/<rama>) si es un push."""
    try:
        data = json.loads(body or b"{}")
    except (ValueError, TypeError):
        return ""
    return data.get("ref", "") or ""


def _run_deploy_bg(domain_id: int, username: str, domain_name: str,
                   branch: str, build_commands: str, keep: int):
    """Ejecuta el deploy y registra el resultado (en BackgroundTask, su propia sesión)."""
    db = SessionLocal()
    try:
        try:
            result = GitManager().deploy(
                username, domain_name, branch=branch,
                build_commands=build_commands or "", keep=keep, trigger="webhook",
            )
            rec = GitDeployment(
                domain_id=domain_id, commit_sha=result.get("commit_sha"),
                commit_msg=result.get("commit_msg"), branch=result.get("branch"),
                ref=result.get("branch"), release_dir=result.get("release_dir"),
                status="success", trigger="webhook", build_log=result.get("build_log"),
            )
        except GitError as e:
            rec = GitDeployment(domain_id=domain_id, branch=branch, status="failed",
                               trigger="webhook", build_log=str(e))
        except Exception as e:
            logger.error(f"Webhook deploy falló para {domain_name}: {e}")
            rec = GitDeployment(domain_id=domain_id, branch=branch, status="failed",
                               trigger="webhook", build_log=str(e))
        db.add(rec)
        db.commit()
    finally:
        db.close()


@router.post("/git/webhook/{token}")
async def git_webhook(token: str, request: Request):
    body = await request.body()
    db = SessionLocal()
    try:
        domain = (db.query(Domain)
                    .filter(Domain.git_webhook_token == token,
                            Domain.git_enabled == True)  # noqa: E712
                    .first())
        if not domain:
            # No revelamos si el token existe o no
            return JSONResponse(status_code=404, content={"status": "not_found"})

        if not _verify_signature(domain, body, request.headers):
            logger.warning(f"Webhook con firma inválida para {domain.domain_name}")
            return JSONResponse(status_code=401, content={"status": "invalid_signature"})

        # Solo desplegar si el push es a la rama configurada
        ref = _extract_ref(body)
        branch = domain.git_branch or "main"
        if ref and ref != f"refs/heads/{branch}":
            return JSONResponse(status_code=200,
                                content={"status": "ignored", "reason": f"ref {ref} != {branch}"})

        owner = db.query(User).filter(User.id == domain.user_id).first()
        if not owner:
            return JSONResponse(status_code=500, content={"status": "no_owner"})

        # Capturar datos antes de cerrar la sesión (el deploy va en background)
        task = BackgroundTask(
            _run_deploy_bg, domain.id, owner.username, domain.domain_name,
            branch, domain.git_build_commands or "", domain.git_keep_releases or 5,
        )
        return JSONResponse(status_code=200, content={"status": "deploying"}, background=task)
    finally:
        db.close()
