"""
Rutas del tuner de MariaDB/MySQL (Fase 21). Solo admin.

  GET  /api/db-tuner/status   → diagnóstico (métricas + recomendaciones) + config actual
  PUT  /api/db-tuner/config   → escribe directivas (allowlist) en el drop-in del panel
  POST /api/db-tuner/restart  → reinicia el servicio MariaDB para aplicar cambios

La config de MariaDB (host/usuario/pass admin) se reutiliza de databases.py para
no duplicar el .env.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import require_admin
from api.models.models_user import User
from api.routes.databases import (
    MARIADB_ENABLED, MARIADB_HOST, MARIADB_PANEL_USER, MARIADB_PANEL_PASSWORD,
)
from scripts import mysql_tuner

router = APIRouter()


def _check_enabled():
    if not MARIADB_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MariaDB no está habilitado en este servidor (MARIADB_ENABLED=true en .env)",
        )


@router.get("/db-tuner/status")
async def db_tuner_status(current_user: User = Depends(require_admin)):
    """
    [Admin] Diagnóstico del servidor MariaDB: métricas clave, recomendaciones de
    optimización (estilo mysqltuner) y la config actual del drop-in del panel.
    """
    _check_enabled()
    tuner = mysql_tuner.MySQLTuner(MARIADB_HOST, MARIADB_PANEL_USER, MARIADB_PANEL_PASSWORD)
    try:
        status_vars = tuner.get_status()
        variables = tuner.get_variables()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No pude consultar MariaDB: {e}")

    ram = tuner.get_system_ram_bytes()
    dataset = tuner.get_innodb_dataset_bytes()
    # RAM ya comprometida por el resto del stack (panel/nginx/correo/SO + PHP-FPM)
    reserved = mysql_tuner._BASE_RESERVE_MB * 1024**2 + mysql_tuner.estimate_php_fpm_ram_bytes()
    analysis = mysql_tuner.analyze(status_vars, variables, ram,
                                   dataset_bytes=dataset, reserved_bytes=reserved)

    # Valores actuales de las directivas editables (mezcla servidor + drop-in),
    # formateados de forma legible (96M en vez de 100663296, 10 en vez de 10.000000).
    current_dropin = mysql_tuner.read_current_dropin()
    current_values = {}
    for name in mysql_tuner.TUNABLE_DIRECTIVES:
        raw = current_dropin.get(name, variables.get(name))
        current_values[name] = mysql_tuner.format_directive_value(name, raw)

    return {
        "enabled":      True,
        "overall":      analysis["overall"],
        "metrics":      analysis["metrics"],
        "recommendations": analysis["recommendations"],
        "directives":   mysql_tuner.TUNABLE_DIRECTIVES,
        "current":      current_values,
        "dropin":       current_dropin,        # solo lo gestionado por el panel
        "dropin_path":  mysql_tuner.dropin_path(),
        "server_version": variables.get("version", "?"),
    }


@router.put("/db-tuner/config")
async def db_tuner_set_config(payload: dict, current_user: User = Depends(require_admin)):
    """
    [Admin] Escribe directivas en el drop-in del panel. Body: {"directives": {...}}.
    Solo se aceptan directivas de la allowlist (TUNABLE_DIRECTIVES). NO reinicia
    el servicio (algunas variables son dinámicas, otras requieren reinicio: el
    admin decide cuándo con /db-tuner/restart).
    """
    _check_enabled()
    directives = payload.get("directives")
    if not isinstance(directives, dict) or not directives:
        raise HTTPException(status_code=400, detail="Falta 'directives' (objeto no vacío)")

    # Filtrar vacíos
    directives = {k: str(v).strip() for k, v in directives.items() if str(v).strip() != ""}

    ok, res = mysql_tuner.write_dropin(directives)
    if not ok:
        raise HTTPException(status_code=400, detail=res)

    return {
        "status":  "ok",
        "message": "Configuración escrita. Reinicia MariaDB para aplicar los cambios que lo requieran.",
        "dropin_path": res,
        "directives":  directives,
    }


@router.post("/db-tuner/restart")
async def db_tuner_restart(current_user: User = Depends(require_admin)):
    """[Admin] Reinicia el servicio MariaDB para aplicar la nueva config."""
    _check_enabled()
    ok, msg = mysql_tuner.restart_service()
    if not ok:
        raise HTTPException(status_code=500, detail=f"No pude reiniciar MariaDB: {msg}")
    return {"status": "ok", "message": msg}
