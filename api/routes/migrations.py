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

# Caché de staging: el backup descargado en el ANÁLISIS (subida/URL/SSH) se
# guarda aquí y se REUTILIZA en la importación, en vez de volver a generarlo y
# traerlo. Sin esto, migrar por SSH descargaba el backup DOS veces (analyze +
# import) — con 20 GB eran 40 GB de transferencia y doble v-backup-user. Los
# tars cacheados se borran al importar o por TTL (huérfanos).
import time
import uuid

MIGRATION_CACHE_DIR = "/var/lib/svqpanel/migrations"
MIGRATION_CACHE_TTL = 6 * 3600  # 6 h: si no se importa, se considera huérfano

# Directorio para los temporales de migración (descarga del .tar, extracción del
# backup, datos de web/correo). DEBE estar en disco real, NO en /tmp: en muchos
# servidores /tmp es un tmpfs pequeño (p.ej. 2.9 GB en RAM) y un backup de varios
# GB lo llena ("No space left on device") además de competir con la memoria. /var
# vive en el disco raíz (decenas de GB libres). Todos los mkstemp/mkdtemp de la
# migración usan este dir vía migration_tmp_dir().
MIGRATION_TMP_DIR = "/var/lib/svqpanel/migration-tmp"


def _cache_dir() -> str:
    os.makedirs(MIGRATION_CACHE_DIR, mode=0o700, exist_ok=True)
    return MIGRATION_CACHE_DIR


def migration_tmp_dir() -> str:
    """Dir en disco real para los temporales de migración (no /tmp). Lo usan los
    mkstemp/mkdtemp del import. Si por lo que sea no se puede crear, cae a None
    (tempfile usará su default) para no romper la migración."""
    try:
        os.makedirs(MIGRATION_TMP_DIR, mode=0o700, exist_ok=True)
        return MIGRATION_TMP_DIR
    except OSError:
        return None


def purge_migration_tmp(max_age: int = 0) -> int:
    """Borra restos de temporales de migración (svq_hestia_*, svq_webdata_*,
    svq_maildata_*, svq_hestia_up_*.tar) más viejos que max_age segundos.

    Un OOM/SIGKILL del restore se salta el __exit__ del context manager que los
    limpia, así que quedan huérfanos (vimos 2.1 GB colgados tras una migración
    fallida). Se llama al arrancar (max_age>0 para no pisar uno en curso) y se
    puede invocar a mano. Barre TANTO el dir nuevo como /tmp (legado)."""
    import glob
    prefixes = ("svq_hestia_", "svq_webdata_", "svq_maildata_", "svq_hestia_up_")
    now = time.time()
    removed = 0
    for base in (MIGRATION_TMP_DIR, tempfile.gettempdir()):
        for pref in prefixes:
            for p in glob.glob(os.path.join(base, pref + "*")):
                try:
                    if max_age and now - os.path.getmtime(p) < max_age:
                        continue
                    if os.path.isdir(p):
                        shutil.rmtree(p, ignore_errors=True)
                    else:
                        os.remove(p)
                    removed += 1
                except OSError:
                    pass
    return removed


def _purge_stale_cache() -> None:
    """Borra los tars de staging más viejos que el TTL (análisis sin importar)."""
    try:
        now = time.time()
        for fn in os.listdir(MIGRATION_CACHE_DIR):
            p = os.path.join(MIGRATION_CACHE_DIR, fn)
            try:
                if os.path.isfile(p) and now - os.path.getmtime(p) > MIGRATION_CACHE_TTL:
                    os.remove(p)
                    logger.info(f"Migración: tar de staging huérfano eliminado: {fn}")
            except OSError:
                pass
    except FileNotFoundError:
        pass


def _stage_tar(tar_path: str) -> str:
    """Mueve el tar descargado a la caché de staging y devuelve su token."""
    _purge_stale_cache()
    token = uuid.uuid4().hex
    dest = os.path.join(_cache_dir(), f"{token}.tar")
    shutil.move(tar_path, dest)
    try:
        os.chmod(dest, 0o600)
    except OSError:
        pass
    return token


def _staged_path(token: str) -> Optional[str]:
    """Ruta del tar cacheado si el token es válido y el fichero existe."""
    if not token:
        return None
    # token = 32 hex (uuid4). Validar para no salir del directorio.
    if len(token) != 32 or any(c not in "0123456789abcdef" for c in token.lower()):
        return None
    p = os.path.join(MIGRATION_CACHE_DIR, f"{token}.tar")
    return p if os.path.isfile(p) else None


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
    # Username único EN EL PANEL.
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=409,
            detail=f"Ya existe un usuario «{username}». Elige otro nombre o usa el cliente existente.")

    # Email único EN EL PANEL (la columna users.email es UNIQUE). Lo validamos
    # ANTES de crear el usuario del SO: si no, el insert peta con un 500 críptico
    # (UniqueViolation) y deja el usuario del sistema huérfano.
    existing_email = db.query(User).filter(User.email == email).first()
    if existing_email:
        raise HTTPException(status_code=409,
            detail=(f"El email «{email}» ya lo usa el cliente «{existing_email.username}». "
                    "Indica un email distinto para este cliente."))

    # Contraseña: la indicada (validada) o una generada que cumple la política.
    if password:
        errs = validate_password(password, load_policy(db))
        if errs:
            raise HTTPException(status_code=400,
                detail="La contraseña no cumple la política: " + "; ".join(errs))
    else:
        password = generate_password(load_policy(db))

    # Crear el usuario del sistema. Caso especial: un intento de migración
    # anterior pudo crear el usuario del SO y fallar antes de registrarlo en el
    # panel → queda HUÉRFANO (existe en el SO, no en el panel). En ese caso lo
    # REUTILIZAMOS (reseteamos su contraseña) en vez de fallar con "User already
    # exists", para que reintentar la migración sea idempotente.
    mgr = UserManager()
    try:
        if mgr.user_exists(username):
            logger.info(f"Migración: reutilizando usuario del SO huérfano «{username}» "
                        "(existe en el sistema pero no en el panel)")
            mgr.change_password(username, password)
        else:
            mgr.create_user(username, email, password)
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
    fd, tmp = tempfile.mkstemp(prefix="svq_hestia_up_", suffix=".tar",
                               dir=migration_tmp_dir())
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


def _remote_cleanup(sshb, remote, remote_tar, env, _sub):
    """Borra el .tar generado en el servidor remoto (no dejar basura en /backup/).
    Best-effort: si falla, solo se loguea."""
    import subprocess, shlex
    if not remote_tar or "/backup/" not in remote_tar:
        return  # solo borramos dentro de /backup/, nunca otra cosa
    try:
        cmd, env2 = _sub(sshb + [remote, f"rm -f {shlex.quote(remote_tar)}"], env)
        subprocess.run(cmd, capture_output=True, text=True, env=env2, timeout=60)
        logger.info(f"Backup remoto eliminado: {remote_tar}")
    except Exception as e:
        logger.warning(f"No se pudo borrar el backup remoto {remote_tar}: {e}")


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

    # Opciones comunes (sin el flag de puerto: ssh usa -p, pero scp usa -P).
    common_opts = ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                   "-o", "ConnectTimeout=15"]

    def ssh_prefix(binary):
        # El flag de puerto difiere: ssh => -p, scp => -P (en scp, -p significa
        # "preservar timestamps", y pasarle el número de puerto como -p hacía que
        # scp interpretara el "22" como una ruta → error "Not a directory").
        port_flag = "-P" if binary == "scp" else "-p"
        opts = common_opts + [port_flag, port]
        env = dict(os.environ)
        if key:
            base = [binary] + opts + ["-i", "__KEYFILE__"]
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

    fd, tmp = tempfile.mkstemp(prefix="svq_hestia_up_", suffix=".tar",
                               dir=migration_tmp_dir())
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
            from scripts.migration_helpers import explain_backup_error
            raise HTTPException(status_code=502,
                detail=explain_backup_error(r.stderr, r.stdout, hestia_user))

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
            # Limpiar el .tar del remoto aunque el scp falle (no dejar basura).
            _remote_cleanup(sshb, remote, remote_tar, env, _sub)
            raise HTTPException(status_code=502,
                detail=f"scp del backup falló: {(r.stderr or r.stdout)[:300]}")

        # 4) Borrar el .tar generado en el remoto: lo generamos nosotros y ya lo
        #    tenemos local; si no, /backup/ del Hestia origen acumularía basura.
        _remote_cleanup(sshb, remote, remote_tar, env, _sub)
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
    scope: str = Form("web,db,mail,dns,cron"),
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

    # NS de ESTE servidor (nssvq1/nssvq2…) para mostrarlos en la propuesta DNS.
    panel_ns = []
    try:
        from scripts.dns_manager import get_panel_nameservers
        ns1, ns2 = get_panel_nameservers(db)
        panel_ns = [n for n in (ns1, ns2) if n]
    except Exception:
        pass

    tar_path = await _receive_backup(file, path, url, ssh)
    downloaded = _is_temp_upload(tar_path)  # subido/URL/SSH → es nuestro temporal
    try:
        # config_only: el análisis solo necesita los .conf, no los datos pesados.
        with open_backup(source_panel, tar_path, config_only=True) as backup:
            manifest = backup.analyze()
            conflicts = find_conflicts(manifest, db, scope_list)
            # Propuesta DNS por zona (clasifica reescrituras) — dentro del with
            # porque necesita los _records antes de limpiar el tmp.
            dns_proposals = {}
            for z in manifest["dns"]:
                dns_proposals[z["domain"]] = build_dns_proposal(
                    z, server_ipv4, server_ipv6, z.get("ip"), panel_ns=panel_ns)
    except (HestiaImportError, CpanelImportError) as e:
        if downloaded and os.path.exists(tar_path):
            os.remove(tar_path)
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        if downloaded and os.path.exists(tar_path):
            os.remove(tar_path)
        logger.exception("Error analizando backup")
        raise HTTPException(status_code=500, detail=f"Error analizando el backup: {e}")

    # Reutilización: si el backup lo hemos DESCARGADO nosotros (subida/URL/SSH),
    # lo movemos a la caché de staging y devolvemos un token para que la
    # importación NO lo vuelva a traer. Los backups por 'path' (ruta local del
    # usuario) no se cachean: ya están en el servidor y no se tocan.
    cache_token = None
    if downloaded and os.path.exists(tar_path):
        try:
            cache_token = _stage_tar(tar_path)
        except Exception as e:
            logger.warning(f"No se pudo cachear el tar de migración: {e}")
            if os.path.exists(tar_path):
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
            "cron": manifest.get("cron", []),
            "conflicts": conflicts,
            "importable": len(conflicts) == 0,
            "warnings": warnings,
            # Token del backup ya descargado: la importación lo reutiliza para no
            # volver a traerlo. None si el origen es una ruta local del servidor.
            "cache_token": cache_token,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Importación (background) — solo si el preflight de conflictos pasa
# ─────────────────────────────────────────────────────────────────────────────
def run_migration_job_inproc(job_id: int):
    """Ejecuta la importación leyendo todos sus datos del MigrationJob.

    Es el cuerpo real del import. Lo invoca el subproceso aislado
    (`python -m api.cli run_migration_job <id>`), NO el proceso del panel: así
    un pico de RAM / OOM durante el restore mata solo a este hijo y el panel
    (uvicorn) sigue vivo. El .tar, el flag de limpieza y los registros DNS se
    leen del propio job (los persistió migration_import)."""
    import json
    from scripts.hestia_import import run_import
    from api.models.models_migration import MigrationJob

    db = SessionLocal()
    tar_path = None
    cleanup_tar = False
    try:
        job = db.query(MigrationJob).filter(MigrationJob.id == job_id).first()
        if not job:
            return
        tar_path = job.tar_path
        cleanup_tar = bool(job.cleanup_tar)
        dns_records = json.loads(job.dns_records_json) if job.dns_records_json else None
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
        raise
    finally:
        db.close()
        if cleanup_tar and tar_path and os.path.exists(tar_path):
            try:
                os.remove(tar_path)
            except OSError:
                pass


def _spawn_import_subprocess(job_id: int):
    """Lanza la importación en un subproceso AISLADO y vigila su salida.

    Corre como background task del panel, pero es ligero: solo arranca el hijo
    (`python -m api.cli run_migration_job <id>`) y espera. Si el hijo muere sin
    dejar el job en estado terminal (p.ej. OOM-killer → SIGKILL), marcamos el
    job como failed aquí, para que la UI no se quede en "Importando…"."""
    import subprocess, sys, shutil
    from api.models.models_migration import MigrationJob

    python = sys.executable
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    base = [python, "-m", "api.cli", "run_migration_job", str(job_id)]

    # Aislar el restore en su PROPIO cgroup con systemd-run --scope: el servicio
    # svqpanel tiene MemoryMax en el unit, y un subproceso normal heredaría ese
    # cgroup → un pico del restore podría disparar el OOM-killer contra uvicorn.
    # Con un scope propio (límite generoso, sin tope de swap) un OOM mata solo al
    # restore. Fallback a subprocess directo si systemd-run no está (dev/local).
    is_root = hasattr(os, "geteuid") and os.geteuid() == 0
    if shutil.which("systemd-run") and is_root:
        cmd = ["systemd-run", "--scope", "--quiet",
               "-p", "MemoryMax=2G", "-p", "MemorySwapMax=1G"] + base
    else:
        cmd = base
    try:
        proc = subprocess.run(
            cmd, cwd=root, capture_output=True, text=True, timeout=7200)
        rc = proc.returncode
        stderr = (proc.stderr or "")[-2000:]
    except subprocess.TimeoutExpired:
        rc, stderr = -1, "La importación superó el tiempo máximo (2h) y se abortó."
    except Exception as e:
        rc, stderr = -1, f"No se pudo lanzar el subproceso de importación: {e}"

    # Si el subproceso terminó OK, él mismo dejó el job en success/failed. Solo
    # intervenimos si murió de forma anómala dejando el job colgado en running.
    if rc == 0:
        return
    db = SessionLocal()
    try:
        job = db.query(MigrationJob).filter(MigrationJob.id == job_id).first()
        if job and job.status in ("pending", "running"):
            job.status = "failed"
            msg = ("La importación se interrumpió (el proceso terminó de forma "
                   "anómala, posible falta de memoria).")
            if stderr.strip():
                msg += f" Detalle: {stderr.strip()[-300:]}"
            job.error = msg
            job.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


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
    scope: str = Form("web,db,mail,dns,cron"),
    dns_records: Optional[str] = Form(None),
    source_panel: str = Form("hestia"),
    # Token del backup ya descargado en el análisis: si viene y el tar sigue en
    # caché, se reutiliza (no se vuelve a generar/descargar).
    cache_token: Optional[str] = Form(None),
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

    # Reutilizar el backup ya descargado en el análisis si hay token válido. Así
    # NO se vuelve a generar/descargar (clave con backups grandes por SSH).
    staged = _staged_path(cache_token)
    if staged:
        tar_path = staged
        cleanup_tar = True   # es nuestro (caché de staging); el job lo borra
        logger.info(f"Migración: reutilizando backup cacheado {cache_token}")
    else:
        ssh = _ssh_from_form(ssh_host, ssh_user, ssh_password, ssh_key, ssh_port, hestia_user)
        tar_path = await _receive_backup(file, path, url, ssh)
        cleanup_tar = _is_temp_upload(tar_path)

    # Preflight: analizar y comprobar conflictos SOLO de lo que se importa.
    # config_only: el preflight no necesita extraer los datos pesados; el job de
    # importación (en background) reabre el backup y extrae todo.
    scope_list = [s for s in (scope or "").split(",") if s]
    try:
        with open_backup(source_panel, tar_path, config_only=True) as backup:
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

    # Crear el job persistiendo lo que el subproceso aislado necesita (tar_path,
    # cleanup_tar, dns_records): el import corre fuera del proceso del panel para
    # que un pico de RAM / OOM mate solo al hijo, no a uvicorn.
    job = MigrationJob(
        source_type="upload" if cleanup_tar else "path",
        source_kind=manifest.get("system") or "hestia",
        target_user_id=target_user_id,
        status="pending",
        scope=scope,
        tar_path=tar_path,
        cleanup_tar=1 if cleanup_tar else 0,
        dns_records_json=json.dumps(dns_records_parsed) if dns_records_parsed else None,
        manifest_json=json.dumps({"system": manifest["system"],
                                  "web": len(manifest["web"]),
                                  "db": len(manifest["db"]),
                                  "mail": len(manifest["mail"]),
                                  "dns": len(manifest["dns"])}),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(_spawn_import_subprocess, job.id)
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
