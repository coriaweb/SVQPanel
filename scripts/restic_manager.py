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

    # ¿Ya existe? `cat config` responde 0 si el repo está inicializado
    rc, _, _ = _run(["cat", "config"], env, timeout=60, global_opts=opts)
    if rc == 0:
        return True, repo, "Repositorio ya inicializado"

    rc, out, err = _run(["init"], env, timeout=120, global_opts=opts)
    if rc == 0:
        return True, repo, "Repositorio inicializado"
    return False, repo, (err or out)[:400]


def run_backup(job: Dict[str, Any], username: str, domain: str,
               files_path: str = None, mail_path: str = None,
               databases: List[Dict] = None) -> Dict[str, Any]:
    """Ejecuta un backup restic del dominio. Vuelca las BBDD a un dir temporal,
    y respalda files + dumps + mail en un único snapshot etiquetado."""
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
    paths_to_backup: List[str] = []
    tmp_db_dir = None

    try:
        # 1) Archivos web
        if files_path and os.path.isdir(files_path):
            paths_to_backup.append(files_path)

        # 2) Correo
        if mail_path and os.path.isdir(mail_path):
            paths_to_backup.append(mail_path)

        # 3) Bases de datos → dumps a dir temporal
        if databases:
            tmp_db_dir = tempfile.mkdtemp(prefix="svq-restic-db-")
            for db in databases:
                name = db["db_name"]
                out_sql = os.path.join(tmp_db_dir, f"{name}.sql")
                if _dump_database(name, out_sql, result["log"]):
                    result["db_count"] += 1
            if result["db_count"]:
                paths_to_backup.append(tmp_db_dir)

        if not paths_to_backup:
            result["status"] = "failed"
            result["error"] = "Nada que respaldar (sin archivos, correo ni BBDD)"
            return result

        # 4) Backup restic con tags (dominio + tipos)
        tags = ["svqpanel", f"domain:{domain}", f"user:{username}"]
        args = ["backup", "--json", "--tag", ",".join(tags)]
        for p in paths_to_backup:
            args.append(p)

        rc, out, err = _run(args, env, timeout=7200, global_opts=opts)
        # restic --json emite una línea por mensaje; la última 'summary' tiene el resumen
        snap_id, added, processed_files = _parse_backup_json(out)
        result["snapshot_id"] = snap_id
        result["size_bytes"] = added
        result["files_total"] = processed_files
        result["log"].append(err.strip()[-800:] if err else "")

        if rc != 0 or not snap_id:
            result["status"] = "failed"
            result["error"] = (err or out)[:400]
            return result

        # 5) Retención
        keep = int(job.get("retention_copies") or 7)
        rc2, out2, err2 = _run(
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
        if tmp_db_dir and os.path.isdir(tmp_db_dir):
            shutil.rmtree(tmp_db_dir, ignore_errors=True)


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


def restore(job: Dict[str, Any], username: str, domain: str,
            snapshot_id: str, target: str,
            include: str = None) -> Dict[str, Any]:
    """Restaura un snapshot (o un subpath con `include`) en `target`."""
    repo = build_repo_url(job, username, domain)
    env = _build_env(job, repo)
    os.makedirs(target, exist_ok=True)
    args = ["restore", snapshot_id or "latest", "--target", target]
    if include:
        args += ["--include", include]
    rc, out, err = _run(args, env, timeout=7200, global_opts=_sftp_opts(job))
    return {"ok": rc == 0, "message": (err or out).strip()[-600:]}


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
