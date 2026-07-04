"""
Jobs en memoria para la emisión de certificados SSL (web del dominio y webmail).

Antes la emisión era una llamada HTTP síncrona: certbot tardaba ~30s y la UI
solo podía enseñar un spinner sin información. Ahora el POST lanza el job en
background y la UI hace polling (~2s): fases reales, última línea de certbot
en vivo, y si falla, el error exacto en el paso donde ocurrió.

Mismo patrón que los jobs de staging WP (scripts/wp_staging.py): el estado
persistente (¿hay cert?) vive en disco/BD; esto solo refleja la operación en
curso y su último resultado. Un job por (kind, domain_id).
"""

import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Cuántas líneas de salida de certbot conservamos para enseñar en caso de error.
_LOG_TAIL = 25

_JOBS: Dict[str, Dict] = {}
_LOCK = threading.Lock()


def _key(kind: str, domain_id: int) -> str:
    return f"{kind}:{domain_id}"


def job_init(kind: str, domain_id: int, steps: List[str]) -> None:
    with _LOCK:
        _JOBS[_key(kind, domain_id)] = {
            "kind": kind, "status": "running", "steps": steps, "current": 0,
            "detail": None, "log": [], "error": None,
            "started_at": datetime.utcnow().isoformat(), "finished_at": None,
        }


def job_step(kind: str, domain_id: int, idx: int) -> None:
    with _LOCK:
        job = _JOBS.get(_key(kind, domain_id))
        if job:
            job["current"] = idx
            job["detail"] = None


def job_line(kind: str, domain_id: int, line: str) -> None:
    """Registra una línea de salida de certbot (detalle en vivo + cola de log)."""
    line = (line or "").strip()
    if not line:
        return
    with _LOCK:
        job = _JOBS.get(_key(kind, domain_id))
        if job:
            job["detail"] = line
            job["log"] = (job["log"] + [line])[-_LOG_TAIL:]


def job_end(kind: str, domain_id: int, error: Optional[str] = None) -> None:
    with _LOCK:
        job = _JOBS.get(_key(kind, domain_id))
        if job:
            job["status"] = "failed" if error else "success"
            job["error"] = error
            job["detail"] = None
            job["finished_at"] = datetime.utcnow().isoformat()


def job_status(kind: str, domain_id: int) -> Optional[Dict]:
    with _LOCK:
        job = _JOBS.get(_key(kind, domain_id))
        return dict(job) if job else None


def job_running(kind: str, domain_id: int) -> bool:
    job = job_status(kind, domain_id)
    return bool(job and job["status"] == "running")


def _err_text(e: Exception) -> str:
    """Mensaje legible: para HTTPException usa .detail, para el resto str()."""
    return str(getattr(e, "detail", None) or e)


# ─────────────────────────────────────────────────────────────────────────────
# Runners (corren como BackgroundTask de FastAPI, fuera de la petición HTTP)
# ─────────────────────────────────────────────────────────────────────────────

def web_steps(domain_name: str) -> List[str]:
    return [
        f"Comprobar que {domain_name} resuelve en DNS",
        "Solicitar el certificado a Let's Encrypt",
        "Instalar el certificado y activar HTTPS",
    ]


def webmail_steps(domain_name: str) -> List[str]:
    return [
        f"Comprobar que webmail.{domain_name} resuelve en DNS",
        "Emitir el certificado con Let's Encrypt",
        "Activar HTTPS en el webmail",
    ]


def run_web_issue(domain_id: int, email: str, hsts: bool = False) -> None:
    """Emite el cert del dominio, actualiza la BD y regenera el vhost."""
    kind = "web"
    from api.models.database import SessionLocal
    from api.models.models_domain import Domain
    from scripts.ssl_manager import SSLManager

    db = SessionLocal()
    try:
        domain = db.query(Domain).filter(Domain.id == domain_id).first()
        if not domain:
            job_end(kind, domain_id, "Dominio no encontrado")
            return
        mgr = SSLManager()

        # Paso 0: DNS del dominio (la variante www la decide certbot dentro)
        job_step(kind, domain_id, 0)
        mgr._validate_dns(domain.domain_name)

        # Paso 1: certbot, con su salida en vivo
        job_step(kind, domain_id, 1)
        mgr.create_ssl_with_email(
            domain.domain_name, email,
            line_cb=lambda l: job_line(kind, domain_id, l))

        # Paso 2: BD + vhost. Al emitir por primera vez se activa force_https
        # (el formulario de emisión no ofrece esa opción; se ajusta después
        # desde las opciones SSL del cert activo).
        job_step(kind, domain_id, 2)
        domain.ssl_enabled    = True
        domain.ssl_expires    = datetime.utcnow() + timedelta(days=90)
        domain.ssl_renewed_at = datetime.utcnow()
        domain.force_https    = True
        domain.hsts_enabled   = bool(hsts)
        db.commit()
        db.refresh(domain)

        from api.routes.domains import _regenerate_from_domain
        _regenerate_from_domain(domain, db)

        job_end(kind, domain_id)
        logger.info(f"SSL issue job OK: {domain.domain_name}")
    except Exception as e:
        logger.error(f"SSL issue job failed (domain_id={domain_id}): {e}")
        try:
            db.rollback()
        except Exception:
            pass
        job_end(kind, domain_id, _err_text(e))
    finally:
        db.close()


def run_webmail_issue(domain_id: int, domain_name: str, email: str) -> None:
    """Emite/expande el cert para webmail.{dominio} y regenera su vhost."""
    kind = "webmail"
    from scripts.ssl_manager import SSLManager
    from scripts.webmail_manager import WebmailManager
    try:
        mgr = SSLManager()
        webmail_host = f"webmail.{domain_name}"

        job_step(kind, domain_id, 0)
        mgr._validate_dns(webmail_host)

        job_step(kind, domain_id, 1)
        mgr.expand_for_webmail(
            domain_name, email,
            line_cb=lambda l: job_line(kind, domain_id, l))

        job_step(kind, domain_id, 2)
        ok, msg = WebmailManager().enable(domain_name, ssl=True)
        if not ok:
            raise RuntimeError(msg or "No se pudo regenerar el vhost del webmail")

        job_end(kind, domain_id)
        logger.info(f"Webmail SSL issue job OK: {webmail_host}")
    except Exception as e:
        logger.error(f"Webmail SSL issue job failed ({domain_name}): {e}")
        job_end(kind, domain_id, _err_text(e))
