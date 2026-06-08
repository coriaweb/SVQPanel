"""
BackupManager — Motor de copias de seguridad de SVQPanel

Estrategia:
  - Archivos web : rsync con --link-dest al snapshot anterior (incrementales)
  - Bases de datos: mysqldump | zstd -3 (fallback a gzip si zstd no disponible)
  - Correo        : rsync de /var/mail/vhosts/{dominio}/ (también incremental)
  - Destino SFTP  : rsync sobre SSH al host remoto

Estructura en disco:
  {local_path}/users/{username}/{domain}/
      20260528_120000/
          files/           ← snapshot rsync
          databases/
              {db}.sql.zst ← dump comprimido
          mail/            ← snapshot buzones
          manifest.json    ← metadata del backup
      latest/              ← copia del último snapshot completo (sin hardlinks)
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from scripts.base import SystemManager

import logging
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de compresión
# ─────────────────────────────────────────────────────────────────────────────

def _has_zstd() -> bool:
    """Comprueba si zstd está disponible en el sistema."""
    return shutil.which("zstd") is not None


def _compress_ext() -> str:
    return ".zst" if _has_zstd() else ".gz"


def _mysqldump_binary() -> Optional[str]:
    """
    Devuelve la ruta al binario de volcado de MariaDB/MySQL.
    Busca rutas explícitas (systemd puede tener PATH reducido) y luego el PATH.
    """
    explicit = [
        "/usr/bin/mariadb-dump",
        "/usr/bin/mysqldump",
        "/usr/local/bin/mariadb-dump",
        "/usr/local/bin/mysqldump",
        "/opt/mariadb/bin/mariadb-dump",
    ]
    for path in explicit:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    for name in ("mariadb-dump", "mysqldump"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _mariadb_binary() -> Optional[str]:
    """Devuelve la ruta al cliente CLI de MariaDB/MySQL (para importar dumps)."""
    explicit = [
        "/usr/bin/mariadb",
        "/usr/bin/mysql",
        "/usr/local/bin/mariadb",
        "/usr/local/bin/mysql",
        "/opt/mariadb/bin/mariadb",
    ]
    for path in explicit:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    for name in ("mariadb", "mysql"):
        found = shutil.which(name)
        if found:
            return found
    return None


# ─────────────────────────────────────────────────────────────────────────────
# BackupManager
# ─────────────────────────────────────────────────────────────────────────────

class BackupManager(SystemManager):
    """Gestiona la creación de copias de seguridad de dominios."""

    def __init__(self):
        super().__init__(require_root=True)

    # ─────────────────────────────────────────────────────────────────────────
    # Punto de entrada principal
    # ─────────────────────────────────────────────────────────────────────────

    def run_backup(
        self,
        job_config: Dict[str, Any],
        username: str,
        domain_name: Optional[str],
        files_path: Optional[str] = None,
        mail_path: Optional[str] = None,
        databases: Optional[List[Dict]] = None,
        force_full: bool = False,
    ) -> Dict[str, Any]:
        """
        Ejecuta un backup completo o incremental según la configuración del job.

        Args:
            job_config   : diccionario con los campos del BackupJob
            username     : nombre del usuario del sistema
            domain_name  : nombre del dominio (None = backup global)
            files_path   : ruta absoluta de los archivos web a copiar (la calcula la ruta API)
            mail_path    : ruta absoluta de los buzones de correo a copiar
            databases    : lista de dicts con {db_name}
            force_full   : ignorar tipo del job y hacer copia completa

        Returns:
            dict con status, backup_path, size_bytes, files_transferred, db_count, log, error
        """
        result: Dict[str, Any] = {
            "status":            "success",
            "backup_path":       None,
            "size_bytes":        0,
            "files_transferred": 0,
            "files_total":       0,
            "db_count":          0,
            "is_incremental":    False,
            "log":               [],
            "error":             None,
        }

        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        dest_type = job_config.get("destination_type", "local")

        try:
            # ── Preparar directorio base ──────────────────────────────────────
            if dest_type == "local":
                base_dir = self._local_base(
                    job_config.get("local_path", "/backups"),
                    username,
                    domain_name or "global",
                )
            else:
                # Para SFTP usamos un directorio temporal local primero
                base_dir = Path(tempfile.mkdtemp(prefix="svqbak_"))

            # ── Detectar snapshot previo ANTES de crear el nuevo ──────────────
            # (si no, _find_previous_snapshot devolvería el snapshot actual)
            prev = None
            is_incremental = False
            if not force_full and job_config.get("backup_type") == "incremental":
                prev = self._find_previous_snapshot(base_dir)
                if prev:
                    is_incremental = True

            snapshot_dir = base_dir / ts
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            result["backup_path"] = str(snapshot_dir)
            if is_incremental and prev:
                result["is_incremental"] = True
                result["log"].append(f"Modo incremental basado en: {prev.name}")

            # ── Backup de archivos web ─────────────────────────────────────────
            if job_config.get("include_files", True) and files_path:
                src_path = files_path.rstrip("/") + "/"
                if os.path.isdir(src_path):
                    files_dir = snapshot_dir / "files"
                    files_dir.mkdir(exist_ok=True)
                    xf, xt, log = self._rsync_files(
                        src=src_path,
                        dst=str(files_dir) + "/",
                        link_dest=str(prev / "files") if is_incremental and prev else None,
                    )
                    result["files_transferred"] += xf
                    result["files_total"]       += xt
                    result["log"].extend(log)
                else:
                    result["log"].append(f"WARN: directorio web no encontrado: {src_path}")

            # ── Backup de bases de datos ──────────────────────────────────────
            if job_config.get("include_databases", True) and databases:
                db_dir = snapshot_dir / "databases"
                db_dir.mkdir(exist_ok=True)
                for db_info in databases:
                    ok, log = self._dump_database(db_info, str(db_dir))
                    result["log"].extend(log)
                    if ok:
                        result["db_count"] += 1

            # ── Backup de correo ──────────────────────────────────────────────
            if job_config.get("include_mail", False) and mail_path:
                mail_src = mail_path.rstrip("/") + "/"
                if os.path.isdir(mail_src):
                    mail_dir = snapshot_dir / "mail"
                    mail_dir.mkdir(exist_ok=True)
                    xf, xt, log = self._rsync_files(
                        src=mail_src,
                        dst=str(mail_dir) + "/",
                        link_dest=str(prev / "mail") if is_incremental and prev else None,
                    )
                    result["files_transferred"] += xf
                    result["files_total"]       += xt
                    result["log"].extend(log)
                else:
                    result["log"].append(f"WARN: directorio de correo no encontrado: {mail_src}")

            # ── Escribir manifest ─────────────────────────────────────────────
            manifest = {
                "timestamp":        ts,
                "domain":           domain_name,
                "username":         username,
                "is_incremental":   is_incremental,
                "include_files":    job_config.get("include_files", True),
                "include_databases":job_config.get("include_databases", True),
                "include_mail":     job_config.get("include_mail", False),
                "db_count":         result["db_count"],
                "files_transferred":result["files_transferred"],
            }
            (snapshot_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

            # ── Calcular tamaño total ─────────────────────────────────────────
            result["size_bytes"] = self._dir_size(snapshot_dir)

            # ── Subir a SFTP si destino remoto ────────────────────────────────
            if dest_type == "sftp":
                sftp_path, log = self._rsync_to_sftp(
                    local_dir=str(snapshot_dir),
                    job_config=job_config,
                    username=username,
                    domain_name=domain_name or "global",
                    ts=ts,
                )
                result["log"].extend(log)
                result["backup_path"] = sftp_path
                # Limpiar directorio temporal
                shutil.rmtree(str(base_dir), ignore_errors=True)

            # ── Subir a S3 si destino remoto ──────────────────────────────────
            elif dest_type == "s3":
                s3_uri, log, ok = self._upload_to_s3(
                    local_dir=str(snapshot_dir),
                    job_config=job_config,
                    username=username,
                    domain_name=domain_name or "global",
                    ts=ts,
                )
                result["log"].extend(log)
                result["backup_path"] = s3_uri
                if not ok:
                    result["status"] = "failed"
                # Limpiar directorio temporal
                shutil.rmtree(str(base_dir), ignore_errors=True)

            # ── Aplicar retención ─────────────────────────────────────────────
            if dest_type == "local":
                self._apply_retention(base_dir, job_config.get("retention_copies", 7))

        except Exception as exc:
            logger.exception("Error en backup")
            result["status"] = "failed"
            result["error"]  = str(exc)

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Rsync local (con soporte --link-dest para incrementales)
    # ─────────────────────────────────────────────────────────────────────────

    def _rsync_files(
        self,
        src: str,
        dst: str,
        link_dest: Optional[str] = None,
        delete: bool = True,
    ) -> Tuple[int, int, List[str]]:
        """
        Ejecuta rsync para copiar src → dst.
        Si link_dest se proporciona, usa --link-dest para hardlinks (incremental).
        Si delete=True, elimina en destino lo que no esté en origen (backup);
        en restauración se usa delete=False para superponer sin borrar.

        Returns: (files_transferred, files_total, log_lines)
        """
        cmd = [
            "rsync",
            "-aH",           # archivo, hardlinks
            "--stats",       # mostrar estadísticas al final
            "--no-human-readable",
        ]
        if delete:
            cmd.append("--delete")  # eliminar en destino lo que no esté en origen

        if link_dest and os.path.isdir(link_dest):
            cmd += [f"--link-dest={link_dest}"]

        cmd += [src, dst]

        rc, stdout, stderr = self.execute_command(cmd, check=False)

        log_lines = []
        files_transferred = 0
        files_total = 0

        if stdout:
            for line in stdout.splitlines():
                log_lines.append(line)
                # rsync moderno emite "Number of regular files transferred: N"
                if "regular files transferred:" in line:
                    try:
                        files_transferred = int(line.split(":")[-1].strip().replace(",", ""))
                    except ValueError:
                        pass
                if "Number of files:" in line:
                    try:
                        # "Number of files: 1,234 (reg: 1,000, dir: 234)"
                        part = line.split(":")[1].strip().split()[0].replace(",", "")
                        files_total = int(part)
                    except (ValueError, IndexError):
                        pass

        if rc != 0 and stderr:
            log_lines.append(f"ERROR rsync: {stderr[:500]}")

        return files_transferred, files_total, log_lines

    # ─────────────────────────────────────────────────────────────────────────
    # Dump de base de datos MariaDB
    # ─────────────────────────────────────────────────────────────────────────

    def _dump_database(
        self,
        db_info: Dict[str, str],
        dest_dir: str,
    ) -> Tuple[bool, List[str]]:
        """
        Vuelca una base de datos MariaDB con mariadb-dump/mysqldump y la comprime.

        Usa las credenciales del usuario administrador del panel (MARIADB_PANEL_USER),
        no las del cliente: las contraseñas de cliente se guardan hasheadas y no son
        recuperables. El usuario admin del panel tiene privilegios sobre todas las BDs.

        Args:
            db_info  : {db_name}
            dest_dir : directorio destino

        Returns: (success, log_lines)
        """
        db_name  = db_info["db_name"]
        ext      = _compress_ext()
        out_file = os.path.join(dest_dir, f"{db_name}.sql{ext}")
        log_lines: List[str] = []

        binary = _mysqldump_binary()
        if not binary:
            log_lines.append(
                f"ERROR dump {db_name}: cliente mariadb-dump/mysqldump no encontrado "
                "(apt install mariadb-client)"
            )
            return False, log_lines

        db_host = os.getenv("MARIADB_HOST", "localhost")
        db_user = os.getenv("MARIADB_PANEL_USER", "svqpanel_admin")
        db_pass = os.getenv("MARIADB_PANEL_PASSWORD", "")

        # Contraseña vía variable de entorno (no aparece en la línea de comandos)
        env = os.environ.copy()
        env["MYSQL_PWD"] = db_pass

        dump_cmd = [
            binary,
            "--single-transaction",
            "--routines",
            "--triggers",
            "--skip-lock-tables",
            f"--host={db_host}",
            f"--user={db_user}",
            db_name,
        ]

        try:
            dump_proc = subprocess.Popen(
                dump_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )

            if _has_zstd():
                compress_cmd = ["zstd", "-3", "-T0", "-o", out_file]
                compress_proc = subprocess.Popen(
                    compress_cmd,
                    stdin=dump_proc.stdout,
                    stderr=subprocess.PIPE,
                )
                dump_proc.stdout.close()
                _, c_err = compress_proc.communicate()
                d_err = dump_proc.stderr.read()
                rc_dump     = dump_proc.wait()
                rc_compress = compress_proc.returncode
            else:
                # Fallback gzip
                with open(out_file, "wb") as fout:
                    compress_proc = subprocess.Popen(
                        ["gzip", "-c"],
                        stdin=dump_proc.stdout,
                        stdout=fout,
                        stderr=subprocess.PIPE,
                    )
                    dump_proc.stdout.close()
                    _, c_err = compress_proc.communicate()
                    d_err = dump_proc.stderr.read()
                    rc_dump     = dump_proc.wait()
                    rc_compress = compress_proc.returncode

            if rc_dump != 0:
                msg = d_err.decode(errors="replace")[:300] if d_err else "mysqldump falló"
                log_lines.append(f"ERROR dump {db_name}: {msg}")
                return False, log_lines

            if rc_compress != 0:
                msg = c_err.decode(errors="replace")[:300] if c_err else "compresión falló"
                log_lines.append(f"ERROR compresión {db_name}: {msg}")
                return False, log_lines

            size = os.path.getsize(out_file)
            log_lines.append(f"DB {db_name}: {out_file} ({size // 1024} KB)")
            return True, log_lines

        except Exception as exc:
            log_lines.append(f"ERROR dump {db_name}: {exc}")
            return False, log_lines

    # ─────────────────────────────────────────────────────────────────────────
    # Rsync al destino SFTP remoto
    # ─────────────────────────────────────────────────────────────────────────

    def _rsync_to_sftp(
        self,
        local_dir: str,
        job_config: Dict[str, Any],
        username: str,
        domain_name: str,
        ts: str,
    ) -> Tuple[str, List[str]]:
        """
        Transfiere el snapshot al servidor SFTP remoto vía rsync+SSH.

        Returns: (remote_path, log_lines)
        """
        host      = job_config["sftp_host"]
        port      = job_config.get("sftp_port", 22)
        user      = job_config["sftp_user"]
        base_path = job_config.get("sftp_path", "/backups").rstrip("/")
        key_path  = job_config.get("sftp_key_path")

        remote_path = f"{base_path}/users/{username}/{domain_name}/{ts}/"

        ssh_opts = [
            "ssh",
            "-p", str(port),
            "-o", "StrictHostKeyChecking=no",
            "-o", "BatchMode=yes",        # sin prompts interactivos
        ]
        if key_path:
            ssh_opts += ["-i", key_path]

        cmd = [
            "rsync",
            "-aH",
            "--stats",
            "-e", " ".join(ssh_opts),
            local_dir + "/",
            f"{user}@{host}:{remote_path}",
        ]

        log_lines: List[str] = [f"Transfiriendo a SFTP {host}:{remote_path}"]
        rc, stdout, stderr = self.execute_command(cmd, check=False)

        if stdout:
            log_lines.extend(stdout.splitlines()[-10:])
        if rc != 0 and stderr:
            log_lines.append(f"ERROR SFTP: {stderr[:300]}")

        return remote_path, log_lines

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers de directorios y retención
    # ─────────────────────────────────────────────────────────────────────────

    def _local_base(self, local_path: str, username: str, domain_name: str) -> Path:
        """Devuelve (y crea) el directorio base de backups de un dominio."""
        base = Path(local_path) / "users" / username / domain_name
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _find_previous_snapshot(self, base_dir: Path) -> Optional[Path]:
        """
        Busca el snapshot más reciente en base_dir (carpetas con formato YYYYMMDD_HHMMSS).
        """
        try:
            snapshots = sorted(
                [d for d in base_dir.iterdir() if d.is_dir() and len(d.name) == 15],
                reverse=True,
            )
            return snapshots[0] if snapshots else None
        except Exception:
            return None

    def _apply_retention(self, base_dir: Path, retention_copies: int) -> None:
        """Elimina snapshots más antiguos que el límite de retención."""
        try:
            snapshots = sorted(
                [d for d in base_dir.iterdir() if d.is_dir() and len(d.name) == 15],
                reverse=True,
            )
            to_delete = snapshots[retention_copies:]
            for snap in to_delete:
                shutil.rmtree(str(snap), ignore_errors=True)
                logger.info(f"Retención: eliminado snapshot {snap}")
        except Exception as exc:
            logger.warning(f"Error aplicando retención: {exc}")

    def _dir_size(self, path: Path) -> int:
        """Calcula el tamaño en bytes de un directorio (sin seguir symlinks)."""
        total = 0
        try:
            for entry in os.scandir(path):
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
                elif entry.is_dir(follow_symlinks=False):
                    total += self._dir_size(Path(entry.path))
        except Exception:
            pass
        return total

    # ─────────────────────────────────────────────────────────────────────────
    # Test de conectividad SFTP
    # ─────────────────────────────────────────────────────────────────────────

    def test_sftp_connection(self, job_config: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Comprueba que el host SFTP es alcanzable con las credenciales del job.

        Returns: (ok, message)
        """
        host     = job_config.get("sftp_host", "")
        port     = job_config.get("sftp_port", 22)
        user     = job_config.get("sftp_user", "")
        key_path = job_config.get("sftp_key_path")

        if not host or not user:
            return False, "Host y usuario SFTP son obligatorios"

        cmd = [
            "ssh",
            "-p", str(port),
            "-o", "StrictHostKeyChecking=no",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
        ]
        if key_path and os.path.isfile(key_path):
            cmd += ["-i", key_path]

        cmd += [f"{user}@{host}", "echo OK"]

        rc, stdout, stderr = self.execute_command(cmd, check=False)
        if rc == 0 and "OK" in stdout:
            return True, "Conexión SFTP correcta"
        return False, (stderr or "No se pudo conectar")[:200]

    # ─────────────────────────────────────────────────────────────────────────
    # Destino S3 / compatible (AWS S3, Backblaze B2, Wasabi, MinIO…)
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _s3_client(job_config: Dict[str, Any]):
        """Crea un cliente boto3 S3 a partir de la config del job. boto3 es una
        dependencia opcional; si no está, lanza ImportError con mensaje claro."""
        try:
            import boto3
            from botocore.config import Config as _BotoConfig
        except ImportError:
            raise ImportError(
                "Falta la librería boto3 para subir a S3. Instálala en el venv del "
                "panel: pip install boto3")
        endpoint = (job_config.get("s3_endpoint") or "").strip() or None
        region   = (job_config.get("s3_region") or "").strip() or None
        return boto3.client(
            "s3",
            endpoint_url=("https://" + endpoint) if endpoint and not endpoint.startswith("http") else endpoint,
            region_name=region,
            aws_access_key_id=job_config.get("s3_access_key"),
            aws_secret_access_key=job_config.get("s3_secret_key"),
            config=_BotoConfig(connect_timeout=15, read_timeout=120,
                               retries={"max_attempts": 3}),
        )

    def _upload_to_s3(
        self,
        local_dir: str,
        job_config: Dict[str, Any],
        username: str,
        domain_name: str,
        ts: str,
    ) -> Tuple[str, List[str], bool]:
        """Empaqueta el snapshot en un .tar.gz y lo sube como un único objeto al
        bucket S3. Devuelve (uri, log, ok)."""
        import tarfile
        import tempfile

        bucket = job_config.get("s3_bucket")
        prefix = (job_config.get("s3_prefix") or "").strip("/")
        key = "/".join(filter(None, [prefix, "users", username, domain_name,
                                     f"{ts}.tar.gz"]))
        uri = f"s3://{bucket}/{key}"
        log: List[str] = [f"Empaquetando y subiendo a {uri}"]

        if not bucket:
            return uri, log + ["ERROR S3: falta el bucket"], False

        tmp_tar = None
        try:
            # 1) Empaquetar el snapshot a un tar.gz temporal
            fd, tmp_tar = tempfile.mkstemp(suffix=".tar.gz", prefix="svqbk-")
            os.close(fd)
            with tarfile.open(tmp_tar, "w:gz") as tar:
                tar.add(local_dir, arcname=os.path.basename(local_dir.rstrip("/")))

            # 2) Subir a S3
            client = self._s3_client(job_config)
            client.upload_file(tmp_tar, bucket, key)

            # 3) Retención remota: conservar solo las N copias más recientes
            try:
                self._apply_s3_retention(client, bucket, prefix, username,
                                         domain_name,
                                         job_config.get("retention_copies", 7), log)
            except Exception as exc:
                log.append(f"Aviso retención S3: {exc}")

            size = os.path.getsize(tmp_tar)
            log.append(f"Subido a {uri} ({size // 1024} KB)")
            return uri, log, True

        except Exception as exc:
            logger.exception("Error subiendo a S3")
            return uri, log + [f"ERROR S3: {str(exc)[:300]}"], False
        finally:
            if tmp_tar and os.path.exists(tmp_tar):
                try:
                    os.remove(tmp_tar)
                except Exception:
                    pass

    @staticmethod
    def _apply_s3_retention(client, bucket, prefix, username, domain_name,
                            retention_copies, log):
        """Borra del bucket los .tar.gz más antiguos que el límite de retención."""
        base = "/".join(filter(None, [prefix, "users", username, domain_name])) + "/"
        resp = client.list_objects_v2(Bucket=bucket, Prefix=base)
        objs = sorted(resp.get("Contents", []),
                      key=lambda o: o["Key"], reverse=True)
        for obj in objs[retention_copies:]:
            client.delete_object(Bucket=bucket, Key=obj["Key"])
            log.append(f"Retención S3: eliminado {obj['Key']}")

    def test_s3_connection(self, job_config: Dict[str, Any]) -> Tuple[bool, str]:
        """Comprueba acceso al bucket S3 con las credenciales del job."""
        bucket = job_config.get("s3_bucket")
        if not bucket or not job_config.get("s3_access_key"):
            return False, "Bucket y access key son obligatorios"
        try:
            client = self._s3_client(job_config)
            # head_bucket falla con 403/404 si no hay acceso o no existe
            client.head_bucket(Bucket=bucket)
            return True, "Conexión S3 correcta"
        except ImportError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, str(exc)[:200]

    # ─────────────────────────────────────────────────────────────────────────
    # Listar snapshots en disco
    # ─────────────────────────────────────────────────────────────────────────

    def list_local_snapshots(
        self,
        local_path: str,
        username: str,
        domain_name: str,
    ) -> List[Dict[str, Any]]:
        """Lista los snapshots locales disponibles para un dominio."""
        base = Path(local_path) / "users" / username / domain_name
        if not base.is_dir():
            return []

        result = []
        for snap in sorted(base.iterdir(), reverse=True):
            if not (snap.is_dir() and len(snap.name) == 15):
                continue
            manifest_file = snap / "manifest.json"
            manifest = {}
            if manifest_file.exists():
                try:
                    manifest = json.loads(manifest_file.read_text())
                except Exception:
                    pass
            db_dir = snap / "databases"
            has_databases = db_dir.is_dir() and any(db_dir.iterdir())
            size_bytes = self._dir_size(snap)
            result.append({
                "name":           snap.name,
                "path":           str(snap),
                "size_bytes":     size_bytes,
                "size_mb":        round(size_bytes / 1048576, 2),
                "is_incremental": manifest.get("is_incremental", False),
                "db_count":       manifest.get("db_count", 0),
                "has_files":      (snap / "files").is_dir(),
                "has_databases":  has_databases,
                "has_mail":       (snap / "mail").is_dir(),
                "manifest":       manifest,
            })
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Restauración de un snapshot
    # ─────────────────────────────────────────────────────────────────────────

    def restore_snapshot(
        self,
        snapshot_path: str,
        files_dest: Optional[str] = None,
        mail_dest: Optional[str] = None,
        restore_files: bool = True,
        restore_databases: bool = True,
        restore_mail: bool = False,
    ) -> Dict[str, Any]:
        """
        Restaura el contenido de un snapshot a sus ubicaciones originales.

        - Archivos: rsync del snapshot a files_dest (SIN --delete: superpone,
          no borra ficheros creados después de la copia).
        - Bases de datos: descomprime cada dump y lo importa en MariaDB
          (CREATE DATABASE IF NOT EXISTS + import). Sobrescribe las tablas
          incluidas en el dump.
        - Correo: rsync del snapshot a mail_dest (también superpone).

        Returns: dict con status, restored (lista), db_count, log, error.
        """
        result: Dict[str, Any] = {
            "status":   "success",
            "restored": [],
            "db_count": 0,
            "log":      [],
            "error":    None,
        }

        snap = Path(snapshot_path)
        if not snap.is_dir():
            result["status"] = "failed"
            result["error"] = f"Snapshot no encontrado: {snapshot_path}"
            return result

        try:
            # ── Restaurar archivos web ────────────────────────────────────────
            files_src = snap / "files"
            if restore_files and files_src.is_dir() and files_dest:
                os.makedirs(files_dest, exist_ok=True)
                xf, _, log = self._rsync_files(
                    src=str(files_src) + "/",
                    dst=files_dest.rstrip("/") + "/",
                    link_dest=None,
                    delete=False,
                )
                result["restored"].append("files")
                result["log"].append(f"Archivos restaurados en {files_dest} ({xf} transferidos)")
                result["log"].extend(log[-5:])

            # ── Restaurar bases de datos ──────────────────────────────────────
            db_src = snap / "databases"
            if restore_databases and db_src.is_dir():
                for dump in sorted(db_src.iterdir()):
                    if not dump.is_file():
                        continue
                    ok, log = self._restore_database(dump)
                    result["log"].extend(log)
                    if ok:
                        result["db_count"] += 1
                if result["db_count"]:
                    result["restored"].append("databases")

            # ── Restaurar correo ──────────────────────────────────────────────
            mail_src = snap / "mail"
            if restore_mail and mail_src.is_dir() and mail_dest:
                os.makedirs(mail_dest, exist_ok=True)
                xf, _, log = self._rsync_files(
                    src=str(mail_src) + "/",
                    dst=mail_dest.rstrip("/") + "/",
                    link_dest=None,
                    delete=False,
                )
                result["restored"].append("mail")
                result["log"].append(f"Correo restaurado en {mail_dest} ({xf} transferidos)")
                result["log"].extend(log[-5:])

            if not result["restored"]:
                result["status"] = "failed"
                result["error"] = "No había nada que restaurar con las opciones indicadas"

        except Exception as exc:
            logger.exception("Error en restauración")
            result["status"] = "failed"
            result["error"] = str(exc)

        return result

    def _restore_database(self, dump_file: Path) -> Tuple[bool, List[str]]:
        """
        Descomprime e importa un dump (.sql.zst / .sql.gz) en MariaDB.
        El nombre de la BD se deduce del fichero: {db}.sql.zst → {db}.
        """
        log_lines: List[str] = []
        name = dump_file.name
        # Quitar extensión de compresión y .sql → nombre de la BD
        db_name = name
        for suffix in (".zst", ".gz"):
            if db_name.endswith(suffix):
                db_name = db_name[: -len(suffix)]
                break
        if db_name.endswith(".sql"):
            db_name = db_name[: -len(".sql")]

        mariadb_bin = _mariadb_binary()
        if not mariadb_bin:
            log_lines.append(f"ERROR restore {db_name}: cliente mariadb/mysql no encontrado")
            return False, log_lines

        db_host = os.getenv("MARIADB_HOST", "localhost")
        db_user = os.getenv("MARIADB_PANEL_USER", "svqpanel_admin")
        db_pass = os.getenv("MARIADB_PANEL_PASSWORD", "")
        env = os.environ.copy()
        env["MYSQL_PWD"] = db_pass

        try:
            import subprocess
            # Asegurar que la BD existe (subprocess directo para pasar MYSQL_PWD)
            subprocess.run(
                [mariadb_bin, f"--host={db_host}", f"--user={db_user}",
                 "-e", f"CREATE DATABASE IF NOT EXISTS `{db_name}`"],
                env=env, capture_output=True, text=True, timeout=30,
            )

            # Descompresor según extensión
            if name.endswith(".zst"):
                decomp = ["zstd", "-dc", str(dump_file)]
            elif name.endswith(".gz"):
                decomp = ["gzip", "-dc", str(dump_file)]
            else:
                decomp = ["cat", str(dump_file)]

            decomp_proc = subprocess.Popen(decomp, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            import_proc = subprocess.Popen(
                [mariadb_bin, f"--host={db_host}", f"--user={db_user}", db_name],
                stdin=decomp_proc.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
            )
            decomp_proc.stdout.close()
            _, imp_err = import_proc.communicate()
            d_err = decomp_proc.stderr.read()
            rc_imp = import_proc.returncode
            rc_dec = decomp_proc.wait()

            if rc_imp != 0:
                msg = imp_err.decode(errors="replace")[:300] if imp_err else "import falló"
                log_lines.append(f"ERROR restore {db_name}: {msg}")
                return False, log_lines
            if rc_dec != 0:
                msg = d_err.decode(errors="replace")[:300] if d_err else "descompresión falló"
                log_lines.append(f"ERROR descompresión {db_name}: {msg}")
                return False, log_lines

            log_lines.append(f"BD restaurada: {db_name}")
            return True, log_lines

        except Exception as exc:
            log_lines.append(f"ERROR restore {db_name}: {exc}")
            return False, log_lines
