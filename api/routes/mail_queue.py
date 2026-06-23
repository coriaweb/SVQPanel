"""
Cola de correo de Postfix (solo admin).

  GET    /api/mail-queue            → lista la cola
  POST   /api/mail-queue/flush      → reintenta toda la cola
  GET    /api/mail-queue/{qid}      → contenido de un mensaje
  POST   /api/mail-queue/{qid}/requeue → re-encola un mensaje
  DELETE /api/mail-queue/{qid}      → borra un mensaje (qid="ALL" vacía la cola)
"""

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import require_admin
from api.models.models_user import User
from scripts import postfix_queue

router = APIRouter()


@router.get("/mail-queue")
async def get_mail_queue(current_user: User = Depends(require_admin)):
    """[Admin] Lista los mensajes en la cola de Postfix."""
    return postfix_queue.list_queue()


@router.post("/mail-queue/flush")
async def flush_mail_queue(current_user: User = Depends(require_admin)):
    """[Admin] Reintenta la entrega de toda la cola."""
    ok, msg = postfix_queue.flush_queue()
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"status": "ok", "message": msg}


@router.get("/mail-queue/{qid}")
async def view_mail_message(qid: str, current_user: User = Depends(require_admin)):
    """[Admin] Muestra el contenido de un mensaje en cola."""
    ok, content = postfix_queue.message_content(qid)
    if not ok:
        raise HTTPException(status_code=400, detail=content)
    return {"id": qid, "content": content}


@router.post("/mail-queue/{qid}/requeue")
async def requeue_mail_message(qid: str, current_user: User = Depends(require_admin)):
    """[Admin] Re-encola un mensaje (o ALL) para reintento inmediato."""
    ok, msg = postfix_queue.requeue_message(qid)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "ok", "message": msg}


@router.delete("/mail-queue/{qid}")
async def delete_mail_message(qid: str, current_user: User = Depends(require_admin)):
    """[Admin] Borra un mensaje de la cola (qid='ALL' vacía toda la cola)."""
    ok, msg = postfix_queue.delete_message(qid)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "ok", "message": msg}
