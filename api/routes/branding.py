"""
Marca blanca (branding) del panel.

Permite personalizar nombre, logo, favicon, color de acento y datos de soporte
para que un reseller presente el panel con su propia marca (estilo Plesk/WHMCS).

- GET /branding, /branding/logo y /branding/favicon son PÚBLICOS: la pantalla
  de login los necesita antes de autenticar. No exponen nada sensible.
- PUT /branding es solo-admin.
- branding_allowed() es el hook del futuro gate por licencia: cuando el plan
  de SVQHost incluya el flag white-label, se comprueba aquí (y solo aquí).
"""

import base64
import binascii
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.models.database import get_db
from api.dependencies import require_admin, require_license
from api.routes.settings import get_or_create_settings

router = APIRouter()

DEFAULT_NAME = "SVQPanel"

# Formatos de imagen aceptados. SVG se sirve con CSP restrictiva (ver abajo)
# para que un SVG con <script> no ejecute nada si se abre la URL directamente.
ALLOWED_IMAGE_MIMES = {
    "image/png", "image/jpeg", "image/webp", "image/svg+xml",
    "image/x-icon", "image/vnd.microsoft.icon", "image/gif",
}
MAX_IMAGE_BYTES = 512 * 1024   # 512 KB por imagen (de sobra para un logo)

HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def branding_allowed(settings) -> bool:
    """Gate de licencia para la marca blanca. De momento SIEMPRE permitido;
    cuando el Laravel de SVQHost exponga el flag en el plan, comprobar aquí
    settings.license_plan / license_valid y devolver False si no lo incluye."""
    return True


def get_brand_name(settings) -> str:
    """Nombre efectivo del panel (marca del cliente o SVQPanel)."""
    name = (getattr(settings, "brand_name", None) or "").strip()
    return name if (name and branding_allowed(settings)) else DEFAULT_NAME


def _is_custom(s) -> bool:
    return branding_allowed(s) and bool(
        (s.brand_name or "").strip()
        or (s.brand_accent_color or "").strip()
        or s.brand_logo
        or s.brand_favicon
    )


def _public_payload(s) -> dict:
    allowed = branding_allowed(s)
    custom = _is_custom(s)
    return {
        "is_custom": custom,
        "panel_name": get_brand_name(s),
        "accent_color": (s.brand_accent_color or None) if allowed else None,
        "has_logo": bool(s.brand_logo) and allowed,
        "has_favicon": bool(s.brand_favicon) and allowed,
        "support_url": (s.brand_support_url or None) if allowed else None,
        "support_email": (s.brand_support_email or None) if allowed else None,
        "hide_powered_by": bool(s.brand_hide_powered_by) and allowed,
        # updated_at sirve de cache-buster para las URLs de logo/favicon
        "version": s.updated_at.isoformat() if s.updated_at else "0",
    }


def _decode_image(data_b64: str, mime: str, what: str) -> str:
    """Valida una imagen en base64 (mime permitido + tamaño). Devuelve el
    base64 normalizado (sin prefijo data:)."""
    mime = (mime or "").strip().lower()
    if mime not in ALLOWED_IMAGE_MIMES:
        raise HTTPException(400, f"Formato de {what} no soportado ({mime or 'desconocido'}). "
                                 "Usa PNG, JPG, WebP, SVG o ICO.")
    # Aceptar tanto base64 pelado como data-URL completa
    if data_b64.startswith("data:"):
        try:
            data_b64 = data_b64.split(",", 1)[1]
        except IndexError:
            raise HTTPException(400, f"Imagen de {what} malformada.")
    try:
        raw = base64.b64decode(data_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, f"Imagen de {what} malformada (base64 inválido).")
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(400, f"La imagen de {what} supera el máximo de "
                                 f"{MAX_IMAGE_BYTES // 1024} KB.")
    if not raw:
        raise HTTPException(400, f"La imagen de {what} está vacía.")
    return base64.b64encode(raw).decode()


def _serve_image(b64: str, mime: str) -> Response:
    raw = base64.b64decode(b64)
    return Response(
        content=raw,
        media_type=mime or "application/octet-stream",
        headers={
            # SVG podría llevar scripts: si alguien abre la URL a pelo, la CSP
            # impide ejecutarlos. Como <img> no ejecutan nada de todos modos.
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "public, max-age=300",
        },
    )


class BrandingUpdate(BaseModel):
    # None = no tocar; "" (cadena vacía) = borrar/volver al valor por defecto
    name:            str | None = Field(None, max_length=64)
    accent_color:    str | None = Field(None, max_length=9)
    logo_base64:     str | None = None
    logo_mime:       str | None = Field(None, max_length=64)
    favicon_base64:  str | None = None
    favicon_mime:    str | None = Field(None, max_length=64)
    support_url:     str | None = Field(None, max_length=255)
    support_email:   str | None = Field(None, max_length=255)
    hide_powered_by: bool | None = None
    reset:           bool = False   # True = borrar TODA la marca (volver a SVQPanel)


@router.get("/branding")
async def get_branding(db: Session = Depends(get_db)):
    """Marca activa del panel. PÚBLICO: el login lo carga antes de autenticar."""
    return _public_payload(get_or_create_settings(db))


@router.get("/branding/logo")
async def get_branding_logo(db: Session = Depends(get_db)):
    """Logo personalizado (público). 404 si no hay."""
    s = get_or_create_settings(db)
    if not s.brand_logo or not branding_allowed(s):
        raise HTTPException(404, "No hay logo personalizado")
    return _serve_image(s.brand_logo, s.brand_logo_mime)


@router.get("/branding/favicon")
async def get_branding_favicon(db: Session = Depends(get_db)):
    """Favicon personalizado (público). 404 si no hay."""
    s = get_or_create_settings(db)
    if not s.brand_favicon or not branding_allowed(s):
        raise HTTPException(404, "No hay favicon personalizado")
    return _serve_image(s.brand_favicon, s.brand_favicon_mime)


@router.put("/branding")
async def update_branding(
    data: BrandingUpdate,
    current_user=Depends(require_admin),
    _lic=Depends(require_license),
    db: Session = Depends(get_db),
):
    """Actualiza la marca blanca (solo admin). Campos a None no se tocan;
    cadena vacía = borrar ese elemento; reset=True borra toda la marca."""
    s = get_or_create_settings(db)

    if not branding_allowed(s):
        raise HTTPException(402, "Tu licencia no incluye la personalización de marca.")

    if data.reset:
        s.brand_name = None
        s.brand_accent_color = None
        s.brand_logo = None
        s.brand_logo_mime = None
        s.brand_favicon = None
        s.brand_favicon_mime = None
        s.brand_support_url = None
        s.brand_support_email = None
        s.brand_hide_powered_by = False
        db.commit()
        db.refresh(s)
        return _public_payload(s)

    if data.name is not None:
        name = data.name.strip()
        s.brand_name = name or None

    if data.accent_color is not None:
        color = data.accent_color.strip()
        if color and not HEX_COLOR_RE.match(color):
            raise HTTPException(400, "El color debe ser hexadecimal de 6 dígitos, ej: #f08a2a")
        s.brand_accent_color = color.lower() or None

    if data.logo_base64 is not None:
        if data.logo_base64 == "":
            s.brand_logo = None
            s.brand_logo_mime = None
        else:
            s.brand_logo = _decode_image(data.logo_base64, data.logo_mime, "logo")
            s.brand_logo_mime = data.logo_mime.strip().lower()

    if data.favicon_base64 is not None:
        if data.favicon_base64 == "":
            s.brand_favicon = None
            s.brand_favicon_mime = None
        else:
            s.brand_favicon = _decode_image(data.favicon_base64, data.favicon_mime, "favicon")
            s.brand_favicon_mime = data.favicon_mime.strip().lower()

    if data.support_url is not None:
        url = data.support_url.strip()
        if url and not re.match(r"^https?://", url):
            raise HTTPException(400, "La URL de soporte debe empezar por http:// o https://")
        s.brand_support_url = url or None

    if data.support_email is not None:
        email = data.support_email.strip()
        if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            raise HTTPException(400, "Email de soporte no válido")
        s.brand_support_email = email or None

    if data.hide_powered_by is not None:
        s.brand_hide_powered_by = bool(data.hide_powered_by)

    db.commit()
    db.refresh(s)
    return _public_payload(s)
