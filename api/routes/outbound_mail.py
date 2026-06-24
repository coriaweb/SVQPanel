"""
Correo saliente no autenticado (formularios PHP/web) — solo admin.

  GET /api/outbound-mail → resumen por usuario del sistema: límite no-auth
       (correos/hora), enviados en la última hora y % de uso.

Sirve para detectar sitios que abusan o están comprometidos (envío masivo).
"""

from fastapi import APIRouter, Depends

from api.dependencies import require_admin
from api.models.models_user import User
from scripts import outbound_mail

router = APIRouter()


@router.get("/outbound-mail")
async def get_outbound_mail(current_user: User = Depends(require_admin)):
    """[Admin] Resumen del correo saliente NO autenticado por usuario de sistema."""
    return outbound_mail.summary()
