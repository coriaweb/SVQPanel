"""
Salud del antispam (Rspamd) — solo admin.

  GET /api/antispam/stats → aprendizaje del Bayes, actividad y acciones, para
       saber de un vistazo si el filtro está funcionando y aprendiendo.
"""

from fastapi import APIRouter, Depends

from api.dependencies import require_admin
from api.models.models_user import User

router = APIRouter()


@router.get("/antispam/stats")
async def antispam_stats(current_user: User = Depends(require_admin)):
    """[Admin] Estado del antispam: Bayes aprendido, correos escaneados, acciones."""
    try:
        from scripts.spam_learning import SpamLearningManager
        return SpamLearningManager().stats()
    except PermissionError:
        return {"available": False, "reason": "requiere root"}
    except Exception as e:
        return {"available": False, "reason": str(e)}
