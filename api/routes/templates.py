"""
Rutas API para plantillas web.

Endpoints (todos autenticados):
  GET  /api/templates                        → listar plantillas activas
  GET  /api/templates/{id}                   → detalle
  POST /api/templates                        → crear (solo admin)
  PUT  /api/templates/{id}                   → actualizar (solo admin, no builtin slug)
  DELETE /api/templates/{id}                 → eliminar (solo admin, no builtin)
  POST /api/domains/{domain_id}/apply-template → aplicar plantilla a un dominio
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.models.database import get_db
from api.models.models_user import User
from api.models.models_domain import Domain
from api.models.models_template import WebTemplate
from api.schemas.template_schemas import (
    WebTemplateCreate, WebTemplateUpdate, WebTemplateResponse,
    ApplyTemplateRequest,
)
from api.dependencies import get_current_user, require_admin

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_template_or_404(template_id: int, db: Session) -> WebTemplate:
    t = db.query(WebTemplate).filter(WebTemplate.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada")
    return t


# ─────────────────────────────────────────────────────────────────────────────
# CRUD plantillas
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/templates", response_model=list[WebTemplateResponse])
async def list_templates(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lista todas las plantillas activas."""
    return (
        db.query(WebTemplate)
        .filter(WebTemplate.is_active == True)
        .order_by(WebTemplate.category, WebTemplate.name)
        .all()
    )


@router.get("/templates/{template_id}", response_model=WebTemplateResponse)
async def get_template(
    template_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_template_or_404(template_id, db)


@router.post("/templates", response_model=WebTemplateResponse, status_code=201)
async def create_template(
    data: WebTemplateCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Crea una plantilla personalizada (solo admin)."""
    if db.query(WebTemplate).filter(WebTemplate.slug == data.slug).first():
        raise HTTPException(status_code=409, detail=f"Ya existe una plantilla con slug '{data.slug}'")

    tpl = WebTemplate(**data.model_dump(), is_builtin=False)
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


@router.put("/templates/{template_id}", response_model=WebTemplateResponse)
async def update_template(
    template_id: int,
    data: WebTemplateUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Actualiza una plantilla (solo admin)."""
    tpl = _get_template_or_404(template_id, db)

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(tpl, field, value)

    db.commit()
    db.refresh(tpl)
    return tpl


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(
    template_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Elimina una plantilla personalizada (no se pueden eliminar builtin)."""
    tpl = _get_template_or_404(template_id, db)
    if tpl.is_builtin:
        raise HTTPException(
            status_code=400,
            detail="Las plantillas integradas no se pueden eliminar. Puedes desactivarlas."
        )
    db.delete(tpl)
    db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Aplicar plantilla a un dominio
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/domains/{domain_id}/apply-template")
async def apply_template(
    domain_id: int,
    req: ApplyTemplateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Aplica una plantilla web al dominio indicado.
    Regenera el vhost nginx + pool PHP-FPM con los presets de la plantilla.
    """
    # Obtener dominio y verificar acceso
    domain = db.query(Domain).filter(Domain.id == domain_id).first()
    if not domain:
        raise HTTPException(status_code=404, detail="Dominio no encontrado")
    if current_user.role != "admin" and domain.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Sin permiso sobre este dominio")

    # Obtener propietario del dominio (username del sistema)
    owner = db.query(User).filter(User.id == domain.user_id).first()
    if not owner:
        raise HTTPException(status_code=404, detail="Usuario propietario no encontrado")

    # Obtener plantilla
    template = _get_template_or_404(req.template_id, db)
    if not template.is_active:
        raise HTTPException(status_code=400, detail="La plantilla no está activa")

    # Aplicar
    from scripts.template_manager import TemplateManager
    manager = TemplateManager()

    result = manager.apply_template(
        domain_row=domain,
        template_row=template,
        username=owner.username,
        enable_cache=req.enable_cache,
        ttl_minutes=req.ttl_minutes,
    )

    if result["status"] != "success":
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Error desconocido al aplicar la plantilla")
        )

    db.commit()
    db.refresh(domain)

    return {
        "status":                "success",
        "message":               f"Plantilla '{template.name}' aplicada a {domain.domain_name}",
        "domain_id":             domain.id,
        "template_id":           template.id,
        "template_name":         template.name,
        "nginx_updated":         result["nginx_updated"],
        "php_pool_updated":      result["php_pool"],
        "cache_enabled":         domain.fastcgi_cache_enabled,
        "applied_template_name": domain.applied_template_name,
    }
