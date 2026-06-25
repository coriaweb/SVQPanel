"""
Migración / importación de backups de otros paneles a SVQPanel.

Fase 1: HestiaCP. Endpoint de ANÁLISIS (no toca el sistema): recibe el .tar
(subido, o por ruta local del servidor), lo extrae a un tmp seguro, parsea su
contenido y devuelve un manifiesto (webs/BDs/correo/DNS) + los conflictos
detectados contra el panel. La importación real se añade en fases siguientes.
"""

import os
import shutil
import tempfile
import logging
from typing import Optional

from datetime import datetime

from fastapi import (APIRouter, Depends, HTTPException, UploadFile, File, Form,
                     BackgroundTasks)
from sqlalchemy.orm import Session

from api.models.database import get_db, SessionLocal
from api.models.models_user import User
from api.dependencies import require_admin

logger = logging.getLogger(__name__)
router = APIRouter()

# Límite de tamaño del backup subido (configurable a futuro).
MAX_BACKUP_MB = 5120  # 5 GB


def _create_target_user(db: Session, username: str, email: str,
                        password: Optional[str]) -> User:
    """Crea el cliente destino de la migración (sistema + BD) a partir de los
    datos del backup. Si no se da contraseña, se genera una que cumple la
    política. Devuelve el User ya persistido."""
    from scripts.user_manager import UserManager
    from scripts.utils import validate_username, validate_email
    from scripts.password_policy import generate_password, load_policy, validate_password

    username = (username or "").strip().lower()
    email = (email or "").strip()
    if not username or not validate_username(username):
        raise HTTPException(status_code=400,
            detail="Nombre de usuario del cliente no válido (a-z, 0-9, sin espacios).")
    if not email or not validate_email(email):
        # El backup puede no traer email; usamos uno placeholder del propio panel.
        email = f"{username}@local.invalid"
    # Username único.
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=409,
            detail=f"Ya existe un usuario «{username}». Elige otro nombre o usa el cliente existente.")

    # Contraseña: la indicada (validada) o una generada que cumple la política.
    if password:
        errs = validate_password(password, load_policy(db))
        if errs:
            raise HTTPException(status_code=400,
                detail="La contraseña no cumple la política: " + "; ".join(errs))
    else:
        password = generate_password(load_policy(db))

    try:
        UserManager().create_user(username, email, password)
    except Exception as e:
        raise HTTPException(status_code=500,
            detail=f"No se pudo crear el usuario del sistema: {e}")

    db_user = User(username=username, email=email, role="user",
                   is_admin=False, domains_limit=10)
    db_user.set_password(password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    logger.info(f"Migración: cliente destino «{username}» creado desde el backup")
    return db_user


# ─────────────────────────────────────────────────────────────────────────────
# Obtención del .tar según el origen (upload / path local). URL y SSH: fase 6.
# ─────────────────────────────────────────────────────────────────────────────
async def _receive_backup(upload: Optional[UploadFile], local_path: Optional[str],
                          url: Optional[str] = None, ssh: Optional[dict] = None
                          ) -> str:
    """Deja el .tar en un fichero temporal del servidor y devuelve su ruta.

    Orígenes soportados:
      - upload:     UploadFile (subida del navegador)
      - local_path: ruta ya presente en el servidor (p. ej. /backups/user.tar)
      - url:        http(s) desde donde descargar el .tar
      - ssh:        {host, user, password|key, hestia_user} → ejecuta
                    v-backup-user en el Hestia remoto y trae el .tar por scp
    El llamador es responsable de borrar los temporales (los que empiezan por
    el prefijo svq_hestia_up_).
    """
    if upload is not None and upload.filename:
        fd, tmp = tempfile.mkstemp(prefix="svq_hestia_up_", suffix=".tar")
        os.close(fd)
        max_bytes = MAX_BACKUP_MB * 1024 * 1024
        written = 0
        try:
            with open(tmp, "wb") as fh:
                while chunk := await upload.read(4 * 1024 * 1024):
                    written += len(chunk)
                    if written > max_bytes:
                        raise HTTPException(status_code=413,
                            detail=f"El backup supera el límite de {MAX_BACKUP_MB} MB")
                    fh.write(chunk)
        except HTTPException:
            os.path.exists(tmp) and os.remove(tmp)
            raise
        return tmp

    if url:
        return _download_url(url)

    if ssh:
        return _fetch_via_ssh(ssh)

    if local_path:
        if not os.path.isfile(local_path):
            raise HTTPException(status_code=404,
                detail=f"No existe el archivo en el servidor: {local_path}")
        return local_path  # NO se borra (es del usuario); el analyze no lo mueve

    raise HTTPException(status_code=400,
        detail="Indica un archivo de backup (súbelo, da una ruta, una URL o SSH).")


def _download_url(url: str) -> str:
    """Descarga un .tar desde una URL http(s) a un temporal."""
    import urllib.request
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="La URL debe ser http(s).")
    fd, tmp = tempfile.mkstemp(prefix="svq_hestia_up_", suffix=".tar")
    os.close(fd)
    max_bytes = MAX_BACKUP_MB * 1024 * 1024
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SVQPanel-Migrator"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as fh:
            written = 0
            while True:
                chunk = resp.read(4 * 1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(status_code=413,
                        detail=f"El backup supera el límite de {MAX_BACKUP_MB} MB")
                fh.write(chunk)
        return tmp
    except HTTPException:
        os.path.exists(tmp) and os.remove(tmp)
        raise
    except Exception as e:
        os.path.exists(tmp) and os.remove(tmp)
        raise HTTPException(status_code=502, detail=f"No pude descargar el backup: {e}")


def _fetch_via_ssh(cfg: dict) -> str:
    """Genera el backup en un Hestia remoto y lo trae por scp.

    cfg: {host, port?, user, password?, key?, hestia_user}. Ejecuta
    `v-backup-user <hestia_user>` por SSH y descarga el .tar resultante de
    /backup/ en el remoto. Usa ssh/scp por subprocess (patrón de dns_cluster);
    si hay password, requiere sshpass instalado.
    """
    import subprocess, shlex
    host = (cfg.get("host") or "").strip()
    user = (cfg.get("user") or "root").strip()
    port = str(cfg.get("port") or 22)
    password = cfg.get("password")
    key = cfg.get("key")
    hestia_user = (cfg.get("hestia_user") or "").strip()
    if not host or not hestia_user:
        raise HTTPException(status_code=400,
            detail="Para SSH indica al menos host y usuario de Hestia a exportar.")

    opts = ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=15", "-p", port]

    def ssh_prefix(binary):
        base = []
        env = dict(os.environ)
        if key:
            opts2 = opts + ["-i", "__KEYFILE__"]
            base = [binary] + opts2
        elif password:
            env["SSHPASS"] = password
            base = ["sshpass", "-e", binary] + opts
        else:
            base = [binary] + opts
        return base, env

    keyfile = None
    if key:
        kfd, keyfile = tempfile.mkstemp(prefix="svq_sshkey_")
        with os.fdopen(kfd, "w") as f:
            f.write(key)
        os.chmod(keyfile, 0o600)

    def _sub(lst, env):
        return [keyfile if x == "__KEYFILE__" else x for x in lst], env

    fd, tmp = tempfile.mkstemp(prefix="svq_hestia_up_", suffix=".tar")
    os.close(fd)
    try:
        # 1) Generar el backup en el remoto.
        #    SSH no interactivo NO carga /etc/profile, así que el PATH es mínimo y
        #    los binarios de Hestia (/usr/local/hestia/bin) no están. Usamos la
        #    ruta absoluta del comando, con fallback al PATH si estuviera en otra
        #    ubicación (instalaciones antiguas o forks tipo VestaCP).
        sshb, env = ssh_prefix("ssh")
        remote = f"{user}@{host}"
        hu = shlex.quote(hestia_user)
        remote_gen = (
            "if [ -x /usr/local/hestia/bin/v-backup-user ]; then "
            f"/usr/local/hestia/bin/v-backup-user {hu}; "
            "elif [ -x /usr/local/vesta/bin/v-backup-user ]; then "
            f"/usr/local/vesta/bin/v-backup-user {hu}; "
            f"else PATH=\"$PATH:/usr/local/hestia/bin:/usr/local/vesta/bin\" v-backup-user {hu}; fi"
        )
        gen_cmd, env = _sub(sshb + [remote, remote_gen], env)
        r = subprocess.run(gen_cmd, capture_output=True, text=True, env=env, timeout=1800)
        if r.returncode != 0:
            msg = (r.stderr or r.stdout or "").strip()[:300]
            if "command not found" in msg or "No such file" in msg:
                msg += (" — ¿es este servidor realmente HestiaCP/VestaCP? "
                        "No se encontró v-backup-user.")
            raise HTTPException(status_code=502,
                detail=f"v-backup-user falló en el remoto: {msg}")

        # 2) Localizar el .tar más reciente del usuario en /backup/
        find_cmd, env = _sub(sshb + [remote,
            f"ls -t /backup/{shlex.quote(hestia_user)}.*.tar 2>/dev/null | head -1"], env)
        r = subprocess.run(find_cmd, capture_output=True, text=True, env=env, timeout=60)
        remote_tar = (r.stdout or "").strip().splitlines()[0] if r.stdout.strip() else ""
        if not remote_tar:
            raise HTTPException(status_code=502,
                detail="No encontré el .tar generado en /backup/ del servidor remoto.")

        # 3) Traerlo por scp
        scpb, env = ssh_prefix("scp")
        scp_cmd, env = _sub(scpb + [f"{remote}:{remote_tar}", tmp], env)
        r = subprocess.run(scp_cmd, capture_output=True, text=True, env=env, timeout=1800)
        if r.returncode != 0:
            raise HTTPException(status_code=502,
                detail=f"scp del backup falló: {(r.stderr or r.stdout)[:300]}")
        return tmp
    except HTTPException:
        os.path.exists(tmp) and os.remove(tmp)
        raise
    except FileNotFoundError as e:
        os.path.exists(tmp) and os.remove(tmp)
        raise HTTPException(status_code=500,
            detail=f"Falta una herramienta (ssh/scp/sshpass): {e}")
    finally:
        if keyfile and os.path.exists(keyfile):
            os.remove(keyfile)


def _is_temp_upload(path: str) -> bool:
    return os.path.basename(path).startswith("svq_hestia_up_")


def _ssh_from_form(host, user, password, key, port, hestia_user) -> Optional[dict]:
    """Construye el dict ssh si se aportaron los datos mínimos, o None."""
    if host and hestia_user:
        return {"host": host, "user": user or "root", "password": password or None,
                "key": key or None, "port": port or 22, "hestia_user": hestia_user}
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Análisis (preflight) — NO toca el sistema
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/migrations/analyze")
async def migration_analyze(
    file: Optional[UploadFile] = File(None),
    path: Optional[str] = Form(None),
    url: Optional[str] = Form(None),
    ssh_host: Optional[str] = Form(None),
    ssh_user: Optional[str] = Form(None),
    ssh_password: Optional[str] = Form(None),
    ssh_key: Optional[str] = Form(None),
    ssh_port: Optional[int] = Form(None),
    hestia_user: Optional[str] = Form(None),
    scope: str = Form("web,db,mail,dns"),
    source_panel: str = Form("hestia"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Analiza un backup (Hestia o cPanel) y devuelve manifiesto + conflictos.

    No crea nada en el sistema; solo lee el backup y compara con la BD del panel.
    Los conflictos se comprueban SOLO para lo que se va a importar (`scope`).
    """
    from scripts.hestia_import import (
        open_backup, find_conflicts, HestiaImportError, has_zstd, build_dns_proposal)
    from scripts.cpanel_import import CpanelImportError

    scope_list = [s for s in scope.split(",") if s]
    ssh = _ssh_from_form(ssh_host, ssh_user, ssh_password, ssh_key, ssh_port, hestia_user)

    # IPs de ESTE servidor (destino de las reescrituras de A/AAAA). Reusa el
    # helper de dns.py que, si no está en Settings, la autodetecta del sistema.
    server_ipv4 = server_ipv6 = None
    try:
        from api.routes.dns import _get_server_ipv4
        server_ipv4 = _get_server_ipv4(db) or None
    except Exception:
        pass
    try:
        from api.models.models_settings import Settings as _S
        _s = db.query(_S).filter(_S.id == 1).first()
        if _s:
            server_ipv6 = getattr(_s, "server_ipv6", None) or None
    except Exception:
        pass

    tar_path = await _receive_backup(file, path, url, ssh)
    cleanup = _is_temp_upload(tar_path)
    try:
        with open_backup(source_panel, tar_path) as backup:
            manifest = backup.analyze()
            conflicts = find_conflicts(manifest, db, scope_list)
            # Propuesta DNS por zona (clasifica reescrituras) — dentro del with
            # porque necesita los _records antes de limpiar el tmp.
            dns_proposals = {}
            for z in manifest["dns"]:
                dns_proposals[z["domain"]] = build_dns_proposal(
                    z, server_ipv4, server_ipv6, z.get("ip"))
    except (HestiaImportError, CpanelImportError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Error analizando backup")
        raise HTTPException(status_code=500, detail=f"Error analizando el backup: {e}")
    finally:
        if cleanup and os.path.exists(tar_path):
            os.remove(tar_path)

    # ¿Hay datos comprimidos en zst y no tenemos soporte? Avisar (no bloquea analyze).
    warnings = []
    needs_zst = any(
        (w.get("_data_tar") or "").endswith((".zst", ".zstd")) for w in manifest["web"]
    ) or any((d.get("_dump") or "").endswith((".zst", ".zstd")) for d in manifest["db"])
    if needs_zst and not has_zstd():
        warnings.append("El backup usa compresión zstd y el servidor no tiene "
                        "soporte (instala el paquete 'zstd'). La importación de "
                        "esos datos fallará hasta instalarlo.")

    # Limpiar campos internos (_data_tar, _conf_dir…) antes de enviar al cliente.
    def _clean(items):
        return [{k: v for k, v in it.items() if not k.startswith("_")} for it in items]

    return {
        "status": "success",
        "data": {
            "system": manifest["system"],
            "user": manifest["user"],
            "web": _clean(manifest["web"]),
            "db": _clean(manifest["db"]),
            "mail": [{**{k: v for k, v in m.items() if not k.startswith("_")},
                      "accounts_count": len(m["accounts"])} for m in manifest["mail"]],
            "dns": [{**{k: v for k, v in z.items() if not k.startswith("_")},
                     "old_ip": z.get("ip"),
                     "server_ipv4": server_ipv4,
                     "proposed_records": dns_proposals.get(z["domain"], [])}
                    for z in manifest["dns"]],
            "conflicts": conflicts,
            "importable": len(conflicts) == 0,
            "warnings": warnings,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Importación (background) — solo si el preflight de conflictos pasa
# ─────────────────────────────────────────────────────────────────────────────
def _run_import_job(job_id: int, tar_path: str, cleanup_tar: bool,
                    dns_records: dict = None):
    """Ejecuta la importación en segundo plano y actualiza el MigrationJob."""
    import json
    from scripts.hestia_import import run_import
    from api.models.models_migration import MigrationJob

    db = SessionLocal()
    try:
        job = db.query(MigrationJob).filter(MigrationJob.id == job_id).first()
        if not job:
            return
        job.status = "running"
        job.started_at = datetime.utcnow()
        db.commit()

        scope = [s for s in (job.scope or "").split(",") if s]
        report = run_import(tar_path, job.target_user_id, scope, db,
                            dns_records=dns_records,
                            source_panel=job.source_kind or "hestia")

        job.report_json = json.dumps(report, ensure_ascii=False)
        job.status = "failed" if report["summary"]["errors"] and not report["summary"]["created"] else "success"
        job.finished_at = datetime.utcnow()
        db.commit()
    except Exception as e:
        logger.exception("Error en job de importación Hestia")
        try:
            job = db.query(MigrationJob).filter(MigrationJob.id == job_id).first()
            if job:
                job.status = "failed"
                job.error = str(e)
                job.finished_at = datetime.utcnow()
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
        if cleanup_tar and os.path.exists(tar_path):
            try:
                os.remove(tar_path)
            except OSError:
                pass


@router.post("/migrations/import")
async def migration_import(
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(None),
    path: Optional[str] = Form(None),
    url: Optional[str] = Form(None),
    ssh_host: Optional[str] = Form(None),
    ssh_user: Optional[str] = Form(None),
    ssh_password: Optional[str] = Form(None),
    ssh_key: Optional[str] = Form(None),
    ssh_port: Optional[int] = Form(None),
    hestia_user: Optional[str] = Form(None),
    target_user_id: Optional[int] = Form(None),
    # Crear el cliente destino SOBRE LA MARCHA desde el backup (en vez de elegir
    # uno existente). Si create_new=true, se crea con estos datos.
    create_new: Optional[bool] = Form(False),
    new_username: Optional[str] = Form(None),
    new_email: Optional[str] = Form(None),
    new_password: Optional[str] = Form(None),
    scope: str = Form("web,db,mail,dns"),
    dns_records: Optional[str] = Form(None),
    source_panel: str = Form("hestia"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Importa un backup (Hestia o cPanel) al usuario destino (en segundo plano).

    Hace el preflight de conflictos: si hay alguno, ABORTA con 409 (no toca nada).
    Si no, crea un MigrationJob y lanza la importación en background; devuelve el
    job_id para hacer polling de su estado.

    `dns_records`: JSON `{dominio: [registros aprobados]}` con la edición que el
    admin hizo en la UI. Si falta una zona, se usa la propuesta automática.
    """
    import json
    from scripts.hestia_import import open_backup, find_conflicts, HestiaImportError
    from scripts.cpanel_import import CpanelImportError
    from api.models.models_migration import MigrationJob

    # Parsear los registros DNS aprobados (si vienen de la UI).
    dns_records_parsed = None
    if dns_records:
        try:
            dns_records_parsed = json.loads(dns_records)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="dns_records no es un JSON válido")

    # Resolver el usuario destino: o se crea uno nuevo desde el backup, o se usa
    # uno existente.
    if create_new:
        target = _create_target_user(db, new_username, new_email, new_password)
        target_user_id = target.id
    else:
        if not target_user_id:
            raise HTTPException(status_code=400,
                detail="Indica un cliente destino o marca «crear cliente nuevo».")
        target = db.query(User).filter(User.id == target_user_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="Usuario destino no encontrado")
        if target.role == "admin" or target.is_admin:
            raise HTTPException(status_code=403,
                detail="El destino debe ser una cuenta de cliente, no un administrador.")

    ssh = _ssh_from_form(ssh_host, ssh_user, ssh_password, ssh_key, ssh_port, hestia_user)
    tar_path = await _receive_backup(file, path, url, ssh)
    cleanup_tar = _is_temp_upload(tar_path)

    # Preflight: analizar y comprobar conflictos SOLO de lo que se importa.
    scope_list = [s for s in (scope or "").split(",") if s]
    try:
        with open_backup(source_panel, tar_path) as backup:
            manifest = backup.analyze()
            conflicts = find_conflicts(manifest, db, scope_list)
    except (HestiaImportError, CpanelImportError) as e:
        if cleanup_tar and os.path.exists(tar_path):
            os.remove(tar_path)
        raise HTTPException(status_code=422, detail=str(e))

    if conflicts:
        if cleanup_tar and os.path.exists(tar_path):
            os.remove(tar_path)
        raise HTTPException(status_code=409, detail={
            "message": "La importación se ha cancelado: hay recursos que ya existen.",
            "conflicts": conflicts,
        })

    # Crear el job y lanzar en background.
    job = MigrationJob(
        source_type="upload" if cleanup_tar else "path",
        source_kind=manifest.get("system") or "hestia",
        target_user_id=target_user_id,
        status="pending",
        scope=scope,
        manifest_json=json.dumps({"system": manifest["system"],
                                  "web": len(manifest["web"]),
                                  "db": len(manifest["db"]),
                                  "mail": len(manifest["mail"]),
                                  "dns": len(manifest["dns"])}),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(_run_import_job, job.id, tar_path, cleanup_tar,
                              dns_records_parsed)
    return {"status": "success", "data": {"job_id": job.id, "status": "pending"}}


@router.get("/migrations/jobs/{job_id}")
async def migration_job_status(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Estado y, si terminó, informe de un job de importación."""
    import json
    from api.models.models_migration import MigrationJob
    job = db.query(MigrationJob).filter(MigrationJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return {"status": "success", "data": {
        "id": job.id,
        "status": job.status,
        "scope": job.scope,
        "target_user_id": job.target_user_id,
        "manifest": json.loads(job.manifest_json) if job.manifest_json else None,
        "report": json.loads(job.report_json) if job.report_json else None,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }}
