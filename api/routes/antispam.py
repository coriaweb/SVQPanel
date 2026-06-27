"""
Salud y ajuste del antispam (Rspamd) — solo admin.

  GET  /api/antispam/stats   → aprendizaje del Bayes, actividad y acciones.
  GET  /api/antispam/tuning  → umbrales, pesos de símbolos y reglas actuales.
  PUT  /api/antispam/tuning  → guardar umbrales + pesos de símbolos.
  PUT  /api/antispam/rules   → guardar reglas de contenido del admin.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.dependencies import require_admin
from api.models.models_user import User
from api.models.database import get_db

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


@router.get("/antispam/tuning")
async def antispam_tuning(current_user: User = Depends(require_admin)):
    """[Admin] Umbrales de acción, pesos de símbolos y reglas de contenido."""
    try:
        from scripts import rspamd_tuning
        return {"available": True, **rspamd_tuning.status()}
    except Exception as e:
        return {"available": False, "reason": str(e)}


def _persist_overrides(db: Session, *, weights=None, actions=None, rules=None):
    """Mezcla y guarda el JSON de overrides en Settings (preservando lo demás)."""
    import json
    from api.models.models_settings import Settings
    s = db.query(Settings).filter(Settings.id == 1).first()
    if not s:
        s = Settings(id=1)
        db.add(s)
    try:
        cur = json.loads(s.rspamd_overrides) if s.rspamd_overrides else {}
    except (ValueError, TypeError):
        cur = {}
    if weights is not None:
        cur["weights"] = weights
    if actions is not None:
        cur["actions"] = actions
    if rules is not None:
        cur["rules"] = rules
    s.rspamd_overrides = json.dumps(cur)
    db.commit()


@router.put("/antispam/tuning")
async def set_antispam_tuning(payload: dict,
                              current_user: User = Depends(require_admin),
                              db: Session = Depends(get_db)):
    """[Admin] Guarda umbrales (actions) y pesos de símbolos (weights)."""
    weights = payload.get("weights")
    actions = payload.get("actions")
    from scripts import rspamd_tuning
    res = rspamd_tuning.apply(weights, actions)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Error al aplicar"))
    _persist_overrides(db, weights=weights, actions=actions)
    return {"status": "success", **res}


@router.put("/antispam/rules")
async def set_antispam_rules(payload: dict,
                             current_user: User = Depends(require_admin),
                             db: Session = Depends(get_db)):
    """[Admin] Guarda las reglas de contenido del admin."""
    rules = payload.get("rules", [])
    from scripts import rspamd_tuning
    res = rspamd_tuning.apply_rules(rules)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Error al aplicar"))
    _persist_overrides(db, rules=rules)
    return {"status": "success", **res}
