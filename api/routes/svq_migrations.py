"""
Migrador SVQPanel → SVQPanel (BETA) — rutas del panel (solo admin).

Flujo (todo en el servidor DESTINO):
  1. POST /migrations/svq/analyze   → trae el export por SSH y analiza (no crea nada)
  2. POST /migrations/svq/import    → job: recrea la cuenta + copia datos + verifica
  3. POST /migrations/svq/{id}/resync → job: vuelve a copiar (solo ANTES del corte)
  4. POST /migrations/svq/{id}/cutover → activa y publica el DNS (+ marca el origen)
  5. POST /migrations/svq/{id}/mail-catchup → job: recoge el correo que aún llegue
     al origen (solo DESPUÉS del corte; sin borrar nada)
  6. POST /migrations/svq/{id}/ssl  → Let's Encrypt donde el DNS ya apunte aquí
  GET /migrations/svq               → migraciones y su fase

Los jobs corren en el subproceso aislado de siempre (api.cli run_migration_job).
Las credenciales SSH del origen viajan CIFRADAS en el job y se borran al acabar.
El estado vive en MigrationJob.manifest_json: {host, port, ssh_user, username,
phase: importing|imported|cutover, letsencrypt: [...], plan: {...}}.
"""

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import require_admin
from api.models.database import SessionLocal, get_db
from api.models.models_user import User

logger = logging.getLogger(__name__)
router = APIRouter()

KIND = "svq"
JOB_TIMEOUT = 12 * 3600
MIN_MARK_VERSION = (0, 281, 0)     # versión del origen que trae svq_mark_migrated


class SvqSource(BaseModel):
    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(22, ge=1, le=65535)
    ssh_user: str = Field("root", max_length=64)
    password: Optional[str] = Field(None, max_length=512)
    key: Optional[str] = Field(None, max_length=16384)
    username: str = Field(..., min_length=1, max_length=32)

    def cfg(self) -> dict:
        return {"host": self.host.strip(), "port": self.port, "user": self.ssh_user.strip() or "root",
                "password": self.password or None, "key": self.key or None}


class SvqCreds(BaseModel):
    """Solo credenciales (host/usuario los toma del job)."""
    password: Optional[str] = Field(None, max_length=512)
    key: Optional[str] = Field(None, max_length=16384)


class CutoverRequest(SvqCreds):
    mark_source: bool = True


# ── cifrado de las credenciales del job ──────────────────────────────────────
def _panel_fernet():
    from scripts.svq_export import _fernet
    f = dict(_fernet()).get("panel")
    if not f:
        raise HTTPException(500, detail="Falta PANEL_ENCRYPTION_KEY en el .env: sin ella no se "
                                        "pueden guardar las credenciales SSH del job.")
    return f


def _enc_cfg(cfg: dict) -> str:
    return _panel_fernet().encrypt(json.dumps(cfg).encode()).decode()


def _dec_cfg(token: Optional[str]) -> Optional[dict]:
    if not token:
        return None
    from scripts.svq_export import _fernet
    f = dict(_fernet()).get("panel")
    return json.loads(f.decrypt(token.encode()).decode()) if f else None


def _state(job) -> dict:
    try:
        return json.loads(job.manifest_json or "{}")
    except ValueError:
        return {}


def _save_state(job, st: dict, db):
    job.manifest_json = json.dumps(st, ensure_ascii=False)
    db.commit()


def _get_job(db, job_id: int):
    from api.models.models_migration import MigrationJob
    job = db.query(MigrationJob).filter(MigrationJob.id == job_id,
                                        MigrationJob.source_kind == KIND).first()
    if not job:
        raise HTTPException(404, detail="Migración no encontrada")
    return job


def _busy(db, username: str) -> bool:
    from api.models.models_migration import MigrationJob
    for j in db.query(MigrationJob).filter(MigrationJob.source_kind == KIND,
                                           MigrationJob.status.in_(("pending", "running"))).all():
        if _state(j).get("username") == username:
            return True
    return False


def _cfg_with(job, creds: SvqCreds) -> dict:
    st = _state(job)
    if not (creds.password or creds.key):
        raise HTTPException(400, detail="Indica la contraseña o la clave SSH del servidor de origen.")
    return {"host": st["host"], "port": st.get("port", 22), "user": st.get("ssh_user", "root"),
            "password": creds.password or None, "key": creds.key or None}


def _new_job(db, st: dict, cfg: dict, scope: str):
    from api.models.models_migration import MigrationJob
    job = MigrationJob(source_type="ssh", source_kind=KIND, status="pending", scope=scope,
                       manifest_json=json.dumps(st, ensure_ascii=False),
                       ssh_cfg_enc=_enc_cfg(cfg))
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _spawn(job_id: int):
    from api.routes.migrations import _spawn_import_subprocess
    _spawn_import_subprocess(job_id, timeout=JOB_TIMEOUT)


# ── endpoints ────────────────────────────────────────────────────────────────
@router.post("/migrations/svq/analyze")
def svq_analyze(body: SvqSource, db: Session = Depends(get_db),
                current_user: User = Depends(require_admin)):
    """Trae el export del origen y analiza. No crea nada en ningún servidor.
    Síncrono a propósito (def): SSH + export tardan segundos y así no bloquea
    el event loop del único worker."""
    from scripts.svq_import import fetch_export, plan_import, SvqImportError
    if not (body.password or body.key):
        raise HTTPException(400, detail="Indica la contraseña o la clave SSH del servidor de origen.")
    try:
        data = fetch_export(body.cfg(), body.username.strip())
        plan = plan_import(data, db)
    except SvqImportError as e:
        raise HTTPException(422, detail=str(e))
    plan["source_version"] = data.get("panel_version")
    plan["source_hostname"] = data.get("hostname")
    return {"status": "success", "data": plan}


@router.post("/migrations/svq/import")
def svq_import(body: SvqSource, background_tasks: BackgroundTasks,
               db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    username = body.username.strip()
    if _busy(db, username):
        raise HTTPException(409, detail="Ya hay una migración en marcha para esa cuenta.")
    if not (body.password or body.key):
        raise HTTPException(400, detail="Indica la contraseña o la clave SSH del servidor de origen.")
    st = {"host": body.host.strip(), "port": body.port, "ssh_user": body.ssh_user or "root",
          "username": username, "phase": "importing"}
    job = _new_job(db, st, body.cfg(), "svq-import")
    background_tasks.add_task(_spawn, job.id)
    return {"status": "success", "data": {"job_id": job.id, "status": "pending"}}


@router.post("/migrations/svq/{job_id}/resync")
def svq_resync(job_id: int, creds: SvqCreds, background_tasks: BackgroundTasks,
               db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    job = _get_job(db, job_id)
    st = _state(job)
    if st.get("phase") == "cutover":
        raise HTTPException(409, detail="Ya se hizo el corte: el servidor nuevo es el bueno y "
                                        "resincronizar machacaría lo que ha cambiado aquí. Usa "
                                        "«Recoger correo» para traer el que aún llegue al origen.")
    if st.get("phase") != "imported":
        raise HTTPException(409, detail="La importación aún no ha terminado bien.")
    if _busy(db, st["username"]):
        raise HTTPException(409, detail="Ya hay un trabajo en marcha para esa cuenta.")
    child = _new_job(db, {**st, "parent_job": job.id}, _cfg_with(job, creds), "svq-resync")
    background_tasks.add_task(_spawn, child.id)
    return {"status": "success", "data": {"job_id": child.id, "status": "pending"}}


@router.post("/migrations/svq/{job_id}/mail-catchup")
def svq_mail_catchup(job_id: int, creds: SvqCreds, background_tasks: BackgroundTasks,
                     db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    job = _get_job(db, job_id)
    st = _state(job)
    if st.get("phase") != "cutover":
        raise HTTPException(409, detail="Recoger correo es para después del corte; antes, usa "
                                        "«Resincronizar».")
    if _busy(db, st["username"]):
        raise HTTPException(409, detail="Ya hay un trabajo en marcha para esa cuenta.")
    child = _new_job(db, {**st, "parent_job": job.id}, _cfg_with(job, creds), "svq-mail")
    background_tasks.add_task(_spawn, child.id)
    return {"status": "success", "data": {"job_id": child.id, "status": "pending"}}


def _mark_source(cfg: dict, username: str, me: str) -> dict:
    """svq_mark_migrated en el ORIGEN por SSH. Bloqueante."""
    import shlex
    import subprocess
    from scripts.svq_copy import Remote
    from scripts.svq_import import _ver
    with Remote(cfg) as r:
        v = subprocess.run(r.ssh("cat /opt/svqpanel/VERSION"), capture_output=True, text=True,
                           env=r.env(), timeout=60)
        if _ver(v.stdout) < MIN_MARK_VERSION:
            return {"ok": False, "error": f"el origen tiene SVQPanel {v.stdout.strip() or '?'}; "
                    "actualízalo para poder marcar la cuenta (no es imprescindible)"}
        cmd = ("cd /opt/svqpanel && /opt/svqpanel/venv/bin/python -m api.cli svq_mark_migrated "
               f"{shlex.quote(username)} --to {shlex.quote(me)}")
        res = subprocess.run(r.ssh(cmd), capture_output=True, text=True, env=r.env(), timeout=300)
        if res.returncode != 0:
            return {"ok": False, "error": (res.stderr or res.stdout).strip()[-300:]}
        try:
            return {"ok": True, "changed": json.loads(res.stdout)}
        except ValueError:
            return {"ok": True, "changed": res.stdout.strip()[-300:]}


@router.post("/migrations/svq/{job_id}/cutover")
def svq_cutover(job_id: int, body: CutoverRequest, db: Session = Depends(get_db),
                current_user: User = Depends(require_admin)):
    """Activa y publica el DNS de la cuenta. Síncrono (def): publicar zonas va por
    SSH al cluster y tarda unos segundos."""
    import socket
    from scripts.svq_cutover import cutover
    job = _get_job(db, job_id)
    st = _state(job)
    if st.get("phase") not in ("imported", "cutover"):
        raise HTTPException(409, detail="La importación aún no ha terminado bien.")
    if _busy(db, st["username"]):
        raise HTTPException(409, detail="Hay un trabajo en marcha para esa cuenta: espera a que acabe.")
    try:
        res = cutover(db, st["username"])
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    st["phase"] = "cutover"
    st["cutover_at"] = datetime.utcnow().isoformat() + "Z"
    if body.mark_source and (body.password or body.key):
        try:
            res["source"] = _mark_source(_cfg_with(job, body), st["username"], socket.getfqdn())
        except Exception as e:
            res["source"] = {"ok": False, "error": str(e)[:300]}
    st["cutover"] = res
    _save_state(job, st, db)
    return {"status": "success", "data": res}


def _run_ssl(job_id: int, email: str):
    from scripts.svq_cutover import ssl_after_cutover
    from scripts.svq_export import _server_ips
    db = SessionLocal()
    try:
        job = _get_job(db, job_id)
        st = _state(job)
        st["ssl"] = {"running": True}
        _save_state(job, st, db)
        try:
            res = ssl_after_cutover(db, st["username"], st.get("letsencrypt", []), email,
                                    _server_ips().get("ipv4"))
        except Exception as e:
            res = {"error": str(e)[:300]}
        try:
            from api.routes.mail import _rebuild_mail_tls
            _rebuild_mail_tls(db)
        except Exception:
            pass
        st = _state(_get_job(db, job_id))
        st["ssl"] = {**res, "running": False, "at": datetime.utcnow().isoformat() + "Z"}
        _save_state(_get_job(db, job_id), st, db)
    finally:
        db.close()


@router.post("/migrations/svq/{job_id}/ssl")
def svq_ssl(job_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db),
            current_user: User = Depends(require_admin)):
    job = _get_job(db, job_id)
    st = _state(job)
    if st.get("phase") != "cutover":
        raise HTTPException(409, detail="Primero haz el corte del DNS.")
    if (st.get("ssl") or {}).get("running"):
        raise HTTPException(409, detail="Ya se están emitiendo los certificados.")
    owner = db.query(User).filter(User.username == st["username"]).first()
    email = (owner.email if owner and owner.email and "invalid" not in owner.email
             else current_user.email) or ""
    background_tasks.add_task(_run_ssl, job_id, email)
    return {"status": "success", "data": {"started": True}}


@router.get("/migrations/svq")
def svq_list(db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    """Migraciones SVQPanel→SVQPanel (la importación inicial de cada cuenta) con
    su fase, para los botones de la UI. Sin secretos."""
    from api.models.models_migration import MigrationJob
    out = []
    for j in (db.query(MigrationJob).filter(MigrationJob.source_kind == KIND,
                                            MigrationJob.scope == "svq-import")
              .order_by(MigrationJob.id.desc()).limit(50).all()):
        st = _state(j)
        out.append({"id": j.id, "status": j.status, "username": st.get("username"),
                    "host": st.get("host"), "phase": st.get("phase"),
                    "cutover": st.get("cutover"), "ssl": st.get("ssl"),
                    "busy": _busy(db, st.get("username")),
                    "created_at": j.created_at.isoformat() if j.created_at else None})
    return {"status": "success", "data": out}


# ── cuerpo del job (lo ejecuta el subproceso: api.cli run_migration_job) ─────
def run_svq_job_inproc(job_id: int):
    from api.models.models_migration import MigrationJob
    from api.routes.migrations import _JobProgress
    from scripts.hestia_import import ImportReport
    from scripts.svq_import import fetch_export, apply_import
    from scripts.svq_copy import run_copy, Remote, copy_mail_catchup
    db = SessionLocal()
    prog = None
    try:
        job = db.query(MigrationJob).filter(MigrationJob.id == job_id).first()
        if not job:
            return
        st = _state(job)
        cfg = _dec_cfg(job.ssh_cfg_enc)
        if not cfg:
            raise RuntimeError("Faltan las credenciales SSH del origen.")
        job.status, job.started_at = "running", datetime.utcnow()
        db.commit()
        prog = _JobProgress(job_id)
        report = ImportReport()
        username = st["username"]

        if job.scope == "svq-mail":
            prog.set_percent(10, "Recogiendo el correo que siga en el origen…")
            with Remote(cfg) as r:
                res = copy_mail_catchup(r, username)
            report.ok("mail-catchup", username, f"{res.get('files') or 0} correo(s) recogidos")
            out = report.to_dict()
        else:
            prog.set_percent(2, "Leyendo la cuenta en el servidor de origen…")
            data = fetch_export(cfg, username)
            out = {}
            if job.scope == "svq-import":
                prog.set_percent(8, "Creando la cuenta en este servidor…")
                out = apply_import(data, db, report=report, progress=prog)
                st["letsencrypt"] = sorted(c["name"] for c in data.get("ssl") or []
                                           if c.get("source") == "letsencrypt")
            prog.set_percent(40, "Copiando webs, correo y bases de datos…")
            out["copy"] = run_copy(cfg, data, report, progress=prog)
            out.update(report.to_dict())
            del data            # secretos: fuera de memoria cuanto antes

        failed_core = job.scope == "svq-import" and any(
            e["type"] in ("user", "copy-home") for e in report.errors)
        job.report_json = json.dumps(out, ensure_ascii=False, default=str)
        job.status = "failed" if failed_core else "success"
        if job.scope == "svq-import":
            st["phase"] = "imported" if job.status == "success" else "failed"
        job.manifest_json = json.dumps(st, ensure_ascii=False)
        job.progress, job.progress_detail, job.finished_at = 100, None, datetime.utcnow()
        db.commit()
    except Exception as e:
        logger.exception("migración SVQPanel→SVQPanel")
        job = db.query(MigrationJob).filter(MigrationJob.id == job_id).first()
        if job:
            job.status, job.error, job.finished_at = "failed", str(e)[:2000], datetime.utcnow()
            st = _state(job)
            if job.scope == "svq-import":
                st["phase"] = "failed"
                job.manifest_json = json.dumps(st, ensure_ascii=False)
            db.commit()
        raise
    finally:
        try:                    # las credenciales no se quedan en la BD
            job = db.query(MigrationJob).filter(MigrationJob.id == job_id).first()
            if job and job.ssh_cfg_enc:
                job.ssh_cfg_enc = None
                db.commit()
        except Exception:
            db.rollback()
        if prog:
            prog.close()
        db.close()
