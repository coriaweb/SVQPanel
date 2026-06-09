"""
ResticManager — Motor de copias de seguridad de SVQPanel basado en restic.

restic da, en CUALQUIER destino (local, SFTP, S3/compatible):
  • backups incrementales + deduplicados (solo guarda lo que cambió, una vez),
  • cifrado de extremo a extremo (el destino nunca ve los datos en claro),
  • snapshots con restauración a cualquier fecha y de archivos sueltos,
  • retención por política (forget --keep-* --prune),
  • verificación de integridad (check).

Modelo de uso en el panel:
  - Cada BackupJob apunta a un REPOSITORIO restic (una URL según el destino) y
    tiene una CONTRASEÑA de cifrado (guardada cifrada con Fernet en la BD).
  - Un backup respalda, en UN solo snapshot, lo que el job seleccione:
      files  → public_html del dominio
      db     → volcados mysqldump a un dir temporal (restic respalda archivos)
      mail   → /home/{user}/mail/{dominio} (o /var/mail/vhosts/...)
    Se etiqueta con tags (dominio, tipos) para poder filtrar e identificar.

URLs de repositorio por destino:
  local:  /backups/restic/{user}/{dominio}
  sftp:   sftp:{user}@{host}:{ruta}
  s3:     s3:{endpoint|s3.amazonaws.com}/{bucket}/{prefijo}
"""
import os
import json
import shutil
import subprocess
import tempfile
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger(__name__)

RESTIC_BIN = shutil.which("restic") or "/usr/bin/restic"


def restic_available() -> bool:
    return os.path.exists(RESTIC_BIN) or shutil.which("restic") is not None


# ─────────────────────────────────────────────────────────────────────────────
# Construcción de la URL del repositorio y del entorno restic
# ─────────────────────────────────────────────────────────────────────────────
def build_repo_url(job: Dict[str, Any], username: str, domain: str) -> str:
    """Devuelve la URL del repositorio restic según el destino del job."""
    dest = job.get("destination_type", "local")
    sub = f"{username}/{domain}".strip("/")

    if dest == "local":
        base = (job.get("local_path") or "/backups").rstrip("/")
        return f"{base}/restic/{sub}"

    if dest == "sftp":
        host = job["sftp_host"]
        user = job["sftp_user"]
        path = (job.get("sftp_path") or "/backups").rstrip("/")
        return f"sftp:{user}@{host}:{path}/restic/{sub}"

    if dest == "s3":
        endpoint = (job.get("s3_endpoint") or "s3.amazonaws.com").strip()
        endpoint = endpoint.replace("https://", "").replace("http://", "").rstrip("/")
        bucket = job["s3_bucket"]
        prefix = (job.get("s3_prefix") or "").strip("/")
        parts = [endpoint, bucket]
        if prefix:
            parts.append(prefix)
        parts.append("restic")
        parts.append(sub)
        return "s3:" + "/".join(parts)

    raise ValueError(f"Destino no soportado: {dest}")


def _build_env(job: Dict[str, Any], repo: str) -> dict:
    """Variables de entorno para restic: contraseña + credenciales del destino."""
    env = dict(os.environ)
    env["RESTIC_REPOSITORY"] = repo
    env["RESTIC_PASSWORD"] = job["restic_password"]
    # No pedir nada por consola nunca
    env["RESTIC_PROGRESS_FPS"] = "0"

    dest = job.get("destination_type", "local")
    if dest == "s3":
        env["AWS_ACCESS_KEY_ID"] = job.get("s3_access_key") or ""
        env["AWS_SECRET_ACCESS_KEY"] = job.get("s3_secret_key") or ""
        if job.get("s3_region"):
            env["AWS_DEFAULT_REGION"] = job["s3_region"]
    # Para SFTP el comando ssh (puerto/clave) va como flag `-o sftp.command=...`
    # en cada invocación restic, no por env (ver _sftp_opts / _run).
    return env


def _sftp_opts(job: Dict[str, Any]) -> List[str]:
    """Flags `-o sftp.command=...` para que restic use nuestra clave/puerto SSH.
    Solo aplica al destino sftp; vacío en los demás."""
    if job.get("destination_type") != "sftp":
        return []
    port = job.get("sftp_port") or 22
    key = job.get("sftp_key_path")
    cmd = ["ssh", "-p", str(port)]
    if key and os.path.exists(key):
        cmd += ["-i", key]
    cmd += ["-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes",
            "-l", job["sftp_user"], job["sftp_host"], "-s", "sftp"]
    return ["-o", "sftp.command=" + " ".join(cmd)]


def _run(args: List[str], env: dict, timeout: int = 3600,
         input_text: str = None, global_opts: List[str] = None) -> Tuple[int, str, str]:
    """Ejecuta restic con los args dados. `global_opts` son flags que van ANTES
    del subcomando (p. ej. -o sftp.command=...). Devuelve (rc, stdout, stderr)."""
    cmd = [RESTIC_BIN] + (global_opts or []) + args
    try:
        r = subprocess.run(cmd, env=env, capture_output=True, text=True,
                           timeout=timeout, input=input_text)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"Timeout ejecutando: restic {' '.join(args)}"
    except Exception as e:
        return 1, "", str(e)


# ─────────────────────────────────────────────────────────────────────────────
# Operaciones del repositorio
# ─────────────────────────────────────────────────────────────────────────────
def ensure_repo(job: Dict[str, Any], username: str, domain: str) -> Tuple[bool, str, str]:
    """Crea el repositorio restic si no existe (idempotente).
    Devuelve (ok, repo_url, mensaje)."""
    repo = build_repo_url(job, username, domain)
    env = _build_env(job, repo)
    opts = _sftp_opts(job)

    # Para destino local hay que crear el directorio padre
    if job.get("destination_type") == "local":
        os.makedirs(repo, exist_ok=True)

    # ¿Ya existe? `cat config` responde 0 si el repo está inicializado Y la
    # contraseña es correcta.
    rc, _, cerr = _run(["cat", "config"], env, timeout=60, global_opts=opts)
    if rc == 0:
        return True, repo, "Repositorio ya inicializado"

    rc, out, err = _run(["init"], env, timeout=120, global_opts=opts)
    if rc == 0:
        return True, repo, "Repositorio inicializado"

    combined = (err or out or "")
    # El repo EXISTE pero el `cat config` falló: casi siempre es que la
    # contraseña de cifrado del job NO coincide con la del repo (el job se
    # recreó con otra password). Mensaje claro en vez del confuso "already exists".
    if "already exists" in combined or "already initialized" in combined:
        msg = ("El repositorio de backups ya existe pero la contraseña de cifrado "
               "no coincide. Probablemente el backup se recreó con otra contraseña. "
               "Borra el repositorio antiguo o usa la contraseña original.")
        if cerr and ("wrong password" in cerr.lower() or "no key" in cerr.lower()):
            msg = ("Contraseña de cifrado incorrecta para este repositorio de "
                   "backups (se creó con otra contraseña).")
        return False, repo, msg
    return False, repo, combined[:400]


# Estructura ESTABLE dentro del snapshot (para poder restaurar elementos
# concretos con restic restore --include). Todo el backup del dominio cuelga de:
#   svqpanel-backup/{domain}/web/            ← public_html
#   svqpanel-backup/{domain}/mail/{buzon}/   ← cada buzón
#   svqpanel-backup/{domain}/databases/X.sql ← cada BBDD
SNAPSHOT_BASE = "svqpanel-backup"


def _snapshot_root(domain: str) -> str:
    return f"/{SNAPSHOT_BASE}/{domain}"


def run_backup(job: Dict[str, Any], username: str, domain: str,
               files_path: str = None, mail_path: str = None,
               databases: List[Dict] = None) -> Dict[str, Any]:
    """Ejecuta un backup restic del dominio con estructura estable (web/mail/
    databases) que permite restaurar elementos concretos. Usa un staging con
    bind-mounts (web, mail) + dumps (BBDD) para que las rutas dentro del snapshot
    sean predecibles."""
    result = {"status": "pending", "log": [], "snapshot_id": None,
              "size_bytes": 0, "files_total": 0, "db_count": 0, "error": None,
              "repo": None}

    ok, repo, msg = ensure_repo(job, username, domain)
    result["repo"] = repo
    result["log"].append(msg)
    if not ok:
        result["status"] = "failed"
        result["error"] = msg
        return result

    env = _build_env(job, repo)
    opts = _sftp_opts(job)

    # Staging estable: /var/lib/svqpanel/backup-staging/{domain}/
    staging = os.path.join("/var/lib/svqpanel/backup-staging", domain)
    mounts = []
    try:
        _rmtree_safe(staging)
        os.makedirs(staging, exist_ok=True)

        # 1) Web → staging/web (bind-mount, sin copiar datos)
        if files_path and os.path.isdir(files_path):
            dst = os.path.join(staging, "web")
            os.makedirs(dst, exist_ok=True)
            if _bind(files_path, dst):
                mounts.append(dst)

        # 2) Correo → staging/mail (bind-mount del dir del dominio)
        if mail_path and os.path.isdir(mail_path):
            dst = os.path.join(staging, "mail")
            os.makedirs(dst, exist_ok=True)
            if _bind(mail_path, dst):
                mounts.append(dst)

        # 3) BBDD → staging/databases/{nombre}.sql (dumps directos)
        if databases:
            dbdir = os.path.join(staging, "databases")
            os.makedirs(dbdir, exist_ok=True)
            for db in databases:
                name = db["db_name"]
                out_sql = os.path.join(dbdir, f"{name}.sql")
                if _dump_database(name, out_sql, result["log"]):
                    result["db_count"] += 1

        if not os.listdir(staging):
            result["status"] = "failed"
            result["error"] = "Nada que respaldar (sin archivos, correo ni BBDD)"
            return result

        # 4) Backup restic del staging. Con --json y los tags del dominio.
        #    Las rutas dentro del snapshot serán /var/lib/.../backup-staging/{domain}/...
        tags = ["svqpanel", f"domain:{domain}", f"user:{username}"]
        args = ["backup", "--json", "--tag", ",".join(tags), staging]
        rc, out, err = _run(args, env, timeout=7200, global_opts=opts)
        snap_id, added, processed_files = _parse_backup_json(out)
        result["snapshot_id"] = snap_id
        result["size_bytes"] = added
        result["files_total"] = processed_files
        if err:
            result["log"].append(err.strip()[-800:])

        if rc != 0 or not snap_id:
            result["status"] = "failed"
            result["error"] = (err or out)[:400]
            return result

        # 5) Retención
        keep = int(job.get("retention_copies") or 7)
        rc2, _, _ = _run(
            ["forget", "--tag", f"domain:{domain}", "--keep-last", str(keep),
             "--prune"], env, timeout=1800, global_opts=opts)
        if rc2 == 0:
            result["log"].append(f"Retención aplicada: conservando {keep} copias")

        result["status"] = "success"
        return result

    except Exception as exc:
        logger.exception("Error en backup restic")
        result["status"] = "failed"
        result["error"] = str(exc)
        return result
    finally:
        # Desmontar los binds y limpiar el staging
        for m in mounts:
            subprocess.run(["umount", m], capture_output=True, timeout=20)
        _rmtree_safe(staging)


def _bind(src: str, dst: str) -> bool:
    """bind-mount de solo lectura src→dst. Devuelve True si se montó."""
    r = subprocess.run(["mount", "--bind", "-o", "ro", src, dst],
                       capture_output=True, timeout=20)
    return r.returncode == 0


def _rmtree_safe(path: str):
    """Borra un dir tras desmontar lo que cuelgue (evita borrar datos reales
    montados)."""
    if not os.path.isdir(path):
        return
    # Desmontar cualquier bind dentro
    try:
        with open("/proc/mounts") as f:
            for line in f:
                mp = line.split()[1] if len(line.split()) > 1 else ""
                if mp.startswith(path):
                    subprocess.run(["umount", mp], capture_output=True, timeout=20)
    except Exception:
        pass
    shutil.rmtree(path, ignore_errors=True)


def list_snapshots(job: Dict[str, Any], username: str, domain: str) -> List[Dict]:
    """Lista los snapshots del repositorio (para la 'máquina del tiempo')."""
    repo = build_repo_url(job, username, domain)
    env = _build_env(job, repo)
    rc, out, err = _run(["snapshots", "--json", "--tag", f"domain:{domain}"],
                        env, timeout=120, global_opts=_sftp_opts(job))
    if rc != 0:
        return []
    try:
        snaps = json.loads(out)
    except Exception:
        return []
    res = []
    for s in snaps:
        res.append({
            "id": s.get("short_id") or s.get("id", "")[:8],
            "time": s.get("time"),
            "paths": s.get("paths", []),
            "tags": s.get("tags", []),
            "hostname": s.get("hostname"),
        })
    return res


def list_snapshot_contents(job: Dict[str, Any], username: str, domain: str,
                           snapshot_id: str) -> Dict[str, Any]:
    """Inspecciona un snapshot y devuelve qué se puede restaurar:
    {web: bool, mail: [buzones], databases: [nombres]}."""
    repo = build_repo_url(job, username, domain)
    env = _build_env(job, repo)
    # Las rutas dentro del snapshot son /var/lib/svqpanel/backup-staging/{domain}/...
    base = f"/var/lib/svqpanel/backup-staging/{domain}"
    out_data = {"web": False, "mail": [], "databases": [], "legacy": False}

    rc, out, err = _run(["ls", snapshot_id, "--json"], env, timeout=120,
                        global_opts=_sftp_opts(job))
    if rc != 0:
        return out_data
    web_base = base + "/web"
    mail_base = base + "/mail"
    db_base = base + "/databases"
    seen_mail = set()
    has_new_structure = False
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            node = json.loads(line)
        except Exception:
            continue
        path = node.get("path", "")
        if path == web_base or path.startswith(web_base + "/"):
            out_data["web"] = True
            has_new_structure = True
        elif path.startswith(mail_base + "/"):
            has_new_structure = True
            rest = path[len(mail_base) + 1:]
            top = rest.split("/")[0]
            if top and top not in seen_mail:
                seen_mail.add(top)
                out_data["mail"].append(top)
        elif path.startswith(db_base + "/") and path.endswith(".sql"):
            has_new_structure = True
            out_data["databases"].append(os.path.basename(path)[:-4])

    # Copias ANTIGUAS (antes de la estructura estable 0.63.0): no tienen
    # web/mail/databases/ predecibles. No se puede granular, pero SÍ restaurar
    # completas. Marcamos legacy para que la UI ofrezca "restaurar todo".
    if not has_new_structure:
        out_data["legacy"] = True
    return out_data


def restore(job: Dict[str, Any], username: str, domain: str,
            snapshot_id: str, target: str,
            includes: List[str] = None) -> Dict[str, Any]:
    """Restaura un snapshot a `target`. `includes` = lista de rutas (dentro del
    staging) a restaurar; None = todo. Devuelve también la ruta base del staging
    restaurado para que el caller copie a su sitio si es modo sobrescribir."""
    repo = build_repo_url(job, username, domain)
    env = _build_env(job, repo)
    os.makedirs(target, exist_ok=True)
    args = ["restore", snapshot_id or "latest", "--target", target]
    for inc in (includes or []):
        args += ["--include", inc]
    rc, out, err = _run(args, env, timeout=7200, global_opts=_sftp_opts(job))
    staging_in_target = os.path.join(
        target, "var/lib/svqpanel/backup-staging", domain)
    return {"ok": rc == 0, "message": (err or out).strip()[-600:],
            "staging": staging_in_target}


def apply_restore(job: Dict[str, Any], username: str, domain: str,
                  snapshot_id: str, selection: Dict[str, Any],
                  overwrite: bool) -> Dict[str, Any]:
    """Restaura los elementos seleccionados de un snapshot.

    selection = {"web": bool, "mail": [buzones], "databases": [nombres]}
    overwrite=False → deja todo en /home/{user}/restore/{snap}/ (carpeta segura).
    overwrite=True  → aplica EN VIVO: web→public_html, buzón→su maildir, BD→import.

    Devuelve {ok, message, target}.
    """
    import tempfile
    log = []
    base = f"/var/lib/svqpanel/backup-staging/{domain}"

    # Copia ANTIGUA (sin estructura estable): no se puede granular ni sobrescribir
    # de forma fiable. La restauramos COMPLETA a la carpeta de recuperación.
    if selection.get("legacy"):
        tmp = tempfile.mkdtemp(prefix="svq-restore-")
        res = restore(job, username, domain, snapshot_id, tmp, includes=None)
        if not res["ok"]:
            _rmtree_safe(tmp)
            return {"ok": False, "message": "Fallo al descargar la copia: " + res["message"]}
        dest = f"/home/{username}/restore/{snapshot_id}"
        _rmtree_safe(dest)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(tmp, dest)
        _chown_r(dest, username)
        return {"ok": True, "target": dest,
                "message": f"Copia (formato antiguo) restaurada completa en {dest}."}

    # 1) Qué rutas del snapshot incluir según la selección
    includes = []
    if selection.get("web"):
        includes.append(base + "/web")
    for buz in selection.get("mail", []):
        includes.append(base + "/mail/" + buz)
    for dbn in selection.get("databases", []):
        includes.append(base + "/databases/" + dbn + ".sql")
    if not includes:
        return {"ok": False, "message": "No has seleccionado nada que restaurar"}

    # 2) Restaurar a un temporal
    tmp = tempfile.mkdtemp(prefix="svq-restore-")
    res = restore(job, username, domain, snapshot_id, tmp, includes=includes)
    if not res["ok"]:
        _rmtree_safe(tmp)
        return {"ok": False, "message": "Fallo al descargar la copia: " + res["message"]}
    src = res["staging"]  # .../tmp/var/lib/.../backup-staging/{domain}

    if not overwrite:
        # Modo carpeta segura: mover el contenido a ~/restore/{snap}/
        dest = f"/home/{username}/restore/{snapshot_id}"
        _rmtree_safe(dest)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(src, dest)
        _rmtree_safe(tmp)
        _chown_r(dest, username)
        return {"ok": True, "target": dest,
                "message": f"Restaurado en {dest} (revisa y copia lo que necesites)."}

    # 3) Modo SOBRESCRIBIR: snapshot de seguridad + aplicar a su sitio
    try:
        # Web → public_html
        if selection.get("web") and os.path.isdir(os.path.join(src, "web")):
            web_dest = f"/home/{username}/web/{domain}/public_html"
            if os.path.isdir(web_dest):
                _rsync(os.path.join(src, "web") + "/", web_dest + "/", log)
                _chown_r(web_dest, username)
                log.append("Web restaurada en public_html")

        # Buzones → maildir del dominio
        for buz in selection.get("mail", []):
            mbsrc = os.path.join(src, "mail", buz)
            if os.path.isdir(mbsrc):
                mbdst = f"/home/{username}/mail/{domain}/{buz}"
                os.makedirs(mbdst, exist_ok=True)
                _rsync(mbsrc + "/", mbdst + "/", log)
                _chown_r(f"/home/{username}/mail/{domain}", username)
                log.append(f"Buzón {buz} restaurado")

        # BBDD → importar con mysql
        for dbn in selection.get("databases", []):
            sql = os.path.join(src, "databases", dbn + ".sql")
            if os.path.isfile(sql):
                if _import_database(dbn, sql, log):
                    log.append(f"Base de datos {dbn} restaurada")

        _rmtree_safe(tmp)
        return {"ok": True, "target": None,
                "message": "Restauración aplicada. " + " · ".join(log[-5:])}
    except Exception as e:
        _rmtree_safe(tmp)
        return {"ok": False, "message": f"Error aplicando la restauración: {e}"}


def _rsync(src: str, dst: str, log: list):
    r = subprocess.run(["rsync", "-a", "--delete", src, dst],
                       capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        log.append("rsync warn: " + r.stderr[-200:])


def _chown_r(path: str, username: str):
    subprocess.run(["chown", "-R", f"{username}:{username}", path],
                   capture_output=True, timeout=120)


def _import_database(db_name: str, sql_path: str, log: list) -> bool:
    binary = shutil.which("mariadb") or shutil.which("mysql") or "/usr/bin/mariadb"
    user = os.getenv("MARIADB_ROOT_USER", "root")
    password = os.getenv("MARIADB_ROOT_PASSWORD", "")
    cmd = [binary, f"-u{user}"]
    if password:
        cmd.append(f"-p{password}")
    cmd.append(db_name)
    try:
        with open(sql_path, "rb") as f:
            r = subprocess.run(cmd, stdin=f, capture_output=True, timeout=1800)
        if r.returncode != 0:
            log.append(f"ERROR import {db_name}: {r.stderr.decode()[:200]}")
            return False
        return True
    except Exception as e:
        log.append(f"ERROR import {db_name}: {e}")
        return False


def check_repo(job: Dict[str, Any], username: str, domain: str) -> Tuple[bool, str]:
    """Verifica la integridad del repositorio."""
    repo = build_repo_url(job, username, domain)
    env = _build_env(job, repo)
    rc, out, err = _run(["check"], env, timeout=1800, global_opts=_sftp_opts(job))
    return rc == 0, (out + err).strip()[-400:]


def test_connection(job: Dict[str, Any], username: str, domain: str) -> Tuple[bool, str]:
    """Comprueba que se puede acceder/crear el repositorio (para 'Probar conexión')."""
    if not restic_available():
        return False, "restic no está instalado en el servidor."
    try:
        ok, repo, msg = ensure_repo(job, username, domain)
        return ok, msg
    except Exception as e:
        return False, str(e)[:300]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _dump_database(db_name: str, out_sql: str, log: List[str]) -> bool:
    """Vuelca una BBDD MariaDB/MySQL a un .sql (restic deduplica/comprime él)."""
    binary = (shutil.which("mariadb-dump") or shutil.which("mysqldump")
              or "/usr/bin/mariadb-dump")
    user = os.getenv("MARIADB_ROOT_USER", "root")
    password = os.getenv("MARIADB_ROOT_PASSWORD", "")
    cmd = [binary, "--single-transaction", "--quick", "--routines",
           "--triggers", f"-u{user}"]
    if password:
        cmd.append(f"-p{password}")
    cmd.append(db_name)
    try:
        with open(out_sql, "wb") as f:
            r = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, timeout=1800)
        if r.returncode != 0:
            log.append(f"ERROR dump {db_name}: {r.stderr.decode()[:200]}")
            return False
        return True
    except Exception as e:
        log.append(f"ERROR dump {db_name}: {e}")
        return False


def _parse_backup_json(out: str) -> Tuple[Optional[str], int, int]:
    """Extrae (snapshot_id, bytes_added, files_processed) del JSON de `backup`."""
    snap_id, added, files = None, 0, 0
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        if msg.get("message_type") == "summary":
            snap_id = msg.get("snapshot_id", "")[:8] or None
            added = int(msg.get("data_added", 0))
            files = int(msg.get("total_files_processed", 0))
    return snap_id, added, files
