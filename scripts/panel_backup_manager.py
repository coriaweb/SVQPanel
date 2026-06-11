"""
Backup del propio panel (red de seguridad ante corrupción de la BD).

Respalda:
  - La base de datos del panel (pg_dump comprimido): usuarios, dominios, DNS,
    correo, planes, settings, etc.
  - Los ficheros críticos de configuración: .env (SECRET_KEY, credenciales),
    /etc/svqpanel, claves DKIM de Rspamd y TSIG del cluster DNS.

Con un backup puedes restaurar el panel completo en un servidor nuevo. Los
backups se guardan en BACKUP_DIR y se rotan (se conservan los N más recientes).

Restauración (manual, por SSH — documentada en la UI):
  1. gunzip -c panel_db_FECHA.sql.gz | psql panel_db
  2. tar xzf config_FECHA.tar.gz -C /   (revisar antes de sobrescribir)
"""

import logging
import os
import re
import subprocess
import tarfile
from datetime import datetime
from urllib.parse import urlparse

from scripts.base import SystemManager

logger = logging.getLogger(__name__)

BACKUP_DIR = "/var/backups/svqpanel"
DEFAULT_RETENTION = 15  # nº de backups a conservar (configurable en Ajustes)
RESTORE_LOG = "/var/log/svqpanel-restore.log"

# Ficheros/directorios de configuración crítica a incluir en el tar.
# Se incluyen los que existan (tolerante a ausencias).
CONFIG_PATHS = [
    "/opt/svqpanel/.env",
    "/opt/svqpanel/.credentials",
    "/etc/svqpanel",
    "/etc/rspamd/dkim",            # claves DKIM por dominio
    "/etc/nginx/snippets/svqpanel-whitelist.conf",
]


def _parse_db_url(url: str) -> dict:
    """Extrae user/pass/host/port/dbname de un DATABASE_URL postgresql://."""
    p = urlparse(url)
    return {
        "user": p.username or "panel_user",
        "password": p.password or "",
        "host": p.hostname or "localhost",
        "port": str(p.port or 5432),
        "dbname": (p.path or "/panel_db").lstrip("/"),
    }


class PanelBackupManager(SystemManager):
    """Gestiona los backups del propio panel (BD + config)."""

    def __init__(self):
        super().__init__(require_root=True)
        os.makedirs(BACKUP_DIR, exist_ok=True)
        os.chmod(BACKUP_DIR, 0o700)  # solo root: contiene credenciales

    # ── Crear backup ───────────────────────────────────────────────────────

    def create(self, retention: int = DEFAULT_RETENTION) -> dict:
        """
        Crea un backup (BD + config) y rota los antiguos.
        Devuelve info de los ficheros generados.
        """
        ts = datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")
        db_file = os.path.join(BACKUP_DIR, f"panel_db_{ts}.sql.gz")
        cfg_file = os.path.join(BACKUP_DIR, f"config_{ts}.tar.gz")

        self._dump_database(db_file)
        self._archive_config(cfg_file)

        # Permisos restrictivos (contienen secretos)
        for f in (db_file, cfg_file):
            try:
                os.chmod(f, 0o600)
            except OSError:
                pass

        self._rotate(retention)

        db_size = os.path.getsize(db_file) if os.path.exists(db_file) else 0
        cfg_size = os.path.getsize(cfg_file) if os.path.exists(cfg_file) else 0
        logger.info("Backup del panel creado: %s (%d B) + %s (%d B)",
                    os.path.basename(db_file), db_size, os.path.basename(cfg_file), cfg_size)
        return {
            "success": True,
            "timestamp": ts,
            "db_file": os.path.basename(db_file),
            "config_file": os.path.basename(cfg_file),
            "db_size": db_size,
            "config_size": cfg_size,
        }

    def _dump_database(self, out_gz: str) -> None:
        """pg_dump de panel_db comprimido con gzip."""
        url = os.getenv("DATABASE_URL", "postgresql://panel_user:panel_password_123@localhost/panel_db")
        db = _parse_db_url(url)

        env = os.environ.copy()
        env["PGPASSWORD"] = db["password"]
        env["PATH"] = self._SYSTEM_PATH

        # pg_dump → gzip a fichero
        with open(out_gz, "wb") as fh:
            dump = subprocess.Popen(
                ["pg_dump", "-h", db["host"], "-p", db["port"], "-U", db["user"], db["dbname"]],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
            )
            gz = subprocess.Popen(["gzip", "-9"], stdin=dump.stdout, stdout=fh)
            dump.stdout.close()
            gz.communicate()
            _, err = dump.communicate()
            if dump.returncode != 0:
                raise RuntimeError(f"pg_dump falló: {err.decode(errors='ignore').strip()}")

    def _archive_config(self, out_tar_gz: str) -> None:
        """Empaqueta los ficheros de config críticos que existan."""
        with tarfile.open(out_tar_gz, "w:gz") as tar:
            for path in CONFIG_PATHS:
                if os.path.exists(path):
                    # arcname relativo a / para restaurar con tar xzf ... -C /
                    tar.add(path, arcname=path.lstrip("/"))

    def _rotate(self, retention: int) -> None:
        """Conserva los `retention` backups más recientes de cada tipo."""
        for prefix in ("panel_db_", "config_"):
            files = sorted(
                [f for f in os.listdir(BACKUP_DIR) if f.startswith(prefix)],
                reverse=True,
            )
            for old in files[retention:]:
                try:
                    os.remove(os.path.join(BACKUP_DIR, old))
                    logger.info("Backup rotado (eliminado): %s", old)
                except OSError:
                    pass

    # ── Consultar ──────────────────────────────────────────────────────────

    def list_backups(self) -> list[dict]:
        """Lista los backups existentes (emparejando BD + config por timestamp)."""
        if not os.path.isdir(BACKUP_DIR):
            return []
        items = {}
        for f in os.listdir(BACKUP_DIR):
            m = re.match(r"^(panel_db|config)_(\d{4}-\d{2}-\d{2}_\d{6})\.(sql\.gz|tar\.gz)$", f)
            if not m:
                continue
            kind, ts = m.group(1), m.group(2)
            full = os.path.join(BACKUP_DIR, f)
            entry = items.setdefault(ts, {"timestamp": ts, "db_file": None,
                                          "config_file": None, "size": 0})
            entry["size"] += os.path.getsize(full)
            if kind == "panel_db":
                entry["db_file"] = f
            else:
                entry["config_file"] = f
        # Formatear fecha legible y ordenar desc
        out = []
        for ts, e in items.items():
            try:
                dt = datetime.strptime(ts, "%Y-%m-%d_%H%M%S")
                e["created_at"] = dt.isoformat() + "Z"
            except ValueError:
                e["created_at"] = ts
            out.append(e)
        return sorted(out, key=lambda x: x["timestamp"], reverse=True)

    def get_backup_path(self, filename: str) -> str:
        """
        Devuelve la ruta absoluta de un fichero de backup validando que el
        nombre es seguro (sin traversal) y existe en BACKUP_DIR.
        """
        if not re.match(r"^(panel_db|config)_\d{4}-\d{2}-\d{2}_\d{6}\.(sql\.gz|tar\.gz)$", filename):
            raise ValueError("Nombre de backup no válido")
        path = os.path.join(BACKUP_DIR, filename)
        if not os.path.isfile(path):
            raise FileNotFoundError("Backup no encontrado")
        return path

    # ── Restaurar (operación de rescate, destructiva) ──────────────────────────

    def restore(self, db_filename: str) -> dict:
        """
        Restaura la BD del panel desde un dump `panel_db_*.sql.gz`.

        PELIGROSO: pisa TODO el estado de panel_db. Antes de restaurar hace un
        backup de seguridad automático (red de seguridad si algo sale mal) y, al
        terminar, reinicia el panel para que tome la BD restaurada.

        Pensado para ejecutarse DETACHED desde el CLI (`restore_panel`), no en el
        proceso web: el restart del panel mataría el request a mitad. Loguea cada
        paso en RESTORE_LOG.
        """
        # Solo se restaura el dump de BD (no el tar de config, que se restaura a mano)
        if not re.match(r"^panel_db_\d{4}-\d{2}-\d{2}_\d{6}\.sql\.gz$", db_filename):
            raise ValueError("Solo se puede restaurar un dump de BD (panel_db_*.sql.gz)")
        src = self.get_backup_path(db_filename)

        def _log(msg: str) -> None:
            line = f"{datetime.utcnow().isoformat()}Z  {msg}"
            logger.info(msg)
            try:
                with open(RESTORE_LOG, "a") as fh:
                    fh.write(line + "\n")
            except OSError:
                pass

        _log(f"=== Restauración del panel desde {db_filename} ===")

        # 1) Backup de seguridad ANTES de pisar nada
        _log("Paso 1/3: backup de seguridad previo…")
        safety = self.create()
        _log(f"  ✓ backup de seguridad: {safety['db_file']}")

        # 2) Recrear el esquema y cargar el dump
        url = os.getenv("DATABASE_URL", "postgresql://panel_user:panel_password_123@localhost/panel_db")
        db = _parse_db_url(url)
        env = os.environ.copy()
        env["PGPASSWORD"] = db["password"]
        env["PATH"] = self._SYSTEM_PATH
        base_psql = ["psql", "-h", db["host"], "-p", db["port"], "-U", db["user"],
                     "-d", db["dbname"], "-v", "ON_ERROR_STOP=1"]

        _log("Paso 2/3: limpiando objetos previos y cargando el dump…")
        # El dump es SQL plano sin --clean, así que partimos de una BD limpia.
        # Usamos `DROP OWNED BY <user>` en vez de `DROP SCHEMA public` porque en
        # PostgreSQL 15+ el dueño del esquema `public` es `pg_database_owner` y
        # `panel_user` no puede dropearlo (must be owner of schema public). En
        # cambio sí puede borrar TODO lo que él posee (las tablas de la app), que
        # es justo lo que el dump volverá a crear.
        drop = subprocess.run(
            base_psql + ["-c", f'DROP OWNED BY "{db["user"]}" CASCADE;'],
            env=env, capture_output=True, text=True,
        )
        if drop.returncode != 0:
            _log(f"  ✗ error limpiando objetos previos: {drop.stderr.strip()}")
            raise RuntimeError(f"No se pudo limpiar la BD: {drop.stderr.strip()}")

        # gunzip -c dump | psql
        with subprocess.Popen(["gunzip", "-c", src], stdout=subprocess.PIPE, env=env) as gz:
            load = subprocess.run(base_psql, stdin=gz.stdout, env=env,
                                  capture_output=True, text=True)
            gz.stdout.close()
        if load.returncode != 0:
            _log(f"  ✗ error cargando el dump: {load.stderr.strip()}")
            raise RuntimeError(f"Error restaurando el dump: {load.stderr.strip()}")
        _log("  ✓ dump restaurado")

        # 3) Reiniciar el panel para que tome la BD restaurada
        _log("Paso 3/3: reiniciando svqpanel…")
        subprocess.run(["systemctl", "restart", "svqpanel"], env=env,
                       capture_output=True, text=True)
        _log("=== Restauración completada ===")
        return {"success": True, "restored_from": db_filename,
                "safety_backup": safety["db_file"]}
