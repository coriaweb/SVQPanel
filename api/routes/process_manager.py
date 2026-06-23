"""
Administrador de procesos del sistema (solo admin).

  GET    /api/processes              → lista procesos (CPU/RAM/usuario)
  DELETE /api/processes/{pid}        → termina un proceso (SIGTERM; ?force=1 → SIGKILL)

Protege procesos críticos (panel, BD, webserver, sshd, systemd…): no se pueden
matar desde el panel para evitar tumbar el servidor por error.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import require_admin
from api.models.models_user import User
from scripts import process_manager

router = APIRouter()


@router.get("/processes")
async def list_processes(
    sort_by: str = Query("cpu", pattern="^(cpu|mem)$"),
    limit: int = Query(200, ge=10, le=500),
    current_user: User = Depends(require_admin),
):
    """[Admin] Lista los procesos del sistema ordenados por CPU o memoria."""
    return process_manager.list_processes(limit=limit, sort_by=sort_by)


@router.delete("/processes/{pid}")
async def kill_process(
    pid: int,
    force: bool = Query(False),
    current_user: User = Depends(require_admin),
):
    """[Admin] Termina un proceso (SIGTERM; force=1 → SIGKILL). Rechaza críticos."""
    ok, msg = process_manager.kill_process(pid, force=force)
    if not ok:
        # 403 si es protegido, 404/400 si no existe o PID inválido
        code = 403 if "protegido" in msg else 400
        raise HTTPException(status_code=code, detail=msg)
    return {"status": "ok", "message": msg}
