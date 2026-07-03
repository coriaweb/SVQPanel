"""
Staging de WordPress (estilo Plesk/Kinsta WP Toolkit).

Clona el WordPress de un dominio a un subdominio de staging
(staging.dominio.com), permite volcar los cambios a producción ("push to
live", con copia de seguridad previa del live) y eliminar el staging.

Diseño:
  - El staging es un Domain normal del panel (subdominio solo-web, mismo
    usuario, mismo PHP) con `staging_of_domain_id` apuntando al dominio live.
  - La BD del staging es una BD MariaDB nueva del cliente (registrada en
    client_databases, colgada del Domain de staging → se borra con él).
  - La clonación de BD es mysqldump | mysql con el admin del panel, y el
    cambio de URLs se hace con `wp search-replace` (maneja los datos
    serializados de PHP que un SQL a pelo rompería).
  - Las operaciones largas (crear/push/eliminar) corren como job en
    background; el estado se consulta por polling (registro en memoria:
    si el panel se reinicia a mitad, el estado real se deriva de la BD).

wp-cli se ejecuta SIEMPRE como el usuario del dominio y con el PHP del
dominio (php{version}), no el del sistema (ver svqpanel-wp-cron-optimize).
"""

import logging
import os
import shutil
import subprocess
import threading
from datetime import datetime
from typing import Dict, List, Optional

from scripts.app_installer import _run, WPCLI_PATH, AppInstaller

logger = logging.getLogger(__name__)


class StagingError(RuntimeError):
    """Error legible de una operación de staging (el endpoint lo da como 4xx)."""


STAGING_PREFIX = "staging."
# Copias de seguridad del live previas a cada push (se conservan las 2 últimas).
BACKUP_DIR = "/var/lib/svqpanel/staging-backups"
KEEP_BACKUPS = 2


def staging_name_for(domain_name: str) -> str:
    return STAGING_PREFIX + domain_name


# ─────────────────────────────────────────────────────────────────────────────
# Registro de jobs en memoria (uno por dominio live). El estado persistente
# real (¿existe staging?) vive en la BD; esto solo refleja la operación en
# curso y su último resultado, para el polling de la UI.
# ─────────────────────────────────────────────────────────────────────────────
_JOBS: Dict[int, Dict] = {}
_JOBS_LOCK = threading.Lock()


def _job_init(live_id: int, op: str, steps: List[str]) -> None:
    with _JOBS_LOCK:
        _JOBS[live_id] = {
            "op": op, "status": "running", "steps": steps, "current": 0,
            "error": None, "started_at": datetime.utcnow().isoformat(),
            "finished_at": None,
        }


def _job_step(live_id: int, idx: int) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(live_id)
        if job:
            job["current"] = idx


def _job_end(live_id: int, error: Optional[str] = None) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(live_id)
        if job:
            job["status"] = "failed" if error else "success"
            job["error"] = error
            job["finished_at"] = datetime.utcnow().isoformat()


def job_status(live_id: int) -> Optional[Dict]:
    with _JOBS_LOCK:
        job = _JOBS.get(live_id)
        return dict(job) if job else None


def job_running(live_id: int) -> bool:
    job = job_status(live_id)
    return bool(job and job["status"] == "running")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers: wp-cli con el PHP del dominio, rsync, dump/import MariaDB
# ─────────────────────────────────────────────────────────────────────────────
def _php_bin(php_version: Optional[str]) -> Optional[str]:
    """Binario php{version} del dominio si existe; None → PHP del sistema."""
    if php_version:
        cand = f"php{php_version}"
        if shutil.which(cand):
            return cand
    return None


def _wp(docroot: str, owner: str, args: List[str], php_version: str = None,
        timeout: int = 900, skip_plugins: bool = False):
    """wp-cli como el usuario del dominio y con el PHP del dominio."""
    php = _php_bin(php_version)
    base = ([php] if php else []) + [WPCLI_PATH]
    extra = ["--skip-plugins", "--skip-themes"] if skip_plugins else []
    cmd = base + list(args) + ["--path=" + docroot] + extra
    return _run(cmd, as_user=owner, timeout=timeout)


def _wp_or_fail(docroot, owner, args, php_version=None, timeout=900,
                skip_plugins=False, msg="wp-cli falló"):
    rc, out, err = _wp(docroot, owner, args, php_version, timeout, skip_plugins)
    if rc != 0:
        raise StagingError(f"{msg}: {(err or out)[:300]}")
    return out


def _wp_config_get(docroot: str, owner: str, key: str, php_version=None) -> str:
    return _wp_or_fail(docroot, owner, ["config", "get", key],
                       php_version, skip_plugins=True,
                       msg=f"No pude leer {key} de wp-config").strip()


def _site_url(docroot: str, owner: str, php_version=None) -> str:
    return _wp_or_fail(docroot, owner, ["option", "get", "siteurl"],
                       php_version, skip_plugins=True,
                       msg="No pude leer la URL del sitio").strip().rstrip("/")


def _sync_files(src: str, dst: str, owner: str, delete: bool = False,
                excludes: tuple = ()) -> None:
    """Copia src/ → dst/ con rsync preservando permisos, y chown al usuario."""
    if not os.path.isdir(src):
        raise StagingError(f"No existe el directorio de origen: {src}")
    cmd = ["rsync", "-a"]
    if delete:
        cmd.append("--delete")
    cmd += [f"--exclude={e}" for e in excludes]
    cmd += [src.rstrip("/") + "/", dst.rstrip("/") + "/"]
    rc, _out, err = _run(cmd, timeout=3600)
    if rc != 0:
        raise StagingError(f"rsync falló: {(err or '')[:300]}")
    _run(["chown", "-R", f"{owner}:{owner}", dst], timeout=600)


def _mariadb_env() -> dict:
    """Entorno con MYSQL_PWD (la contraseña no viaja en la línea de comandos)."""
    from api.routes.databases import MARIADB_PANEL_PASSWORD
    return {**os.environ, "MYSQL_PWD": MARIADB_PANEL_PASSWORD or ""}


def _dump_db(db_name: str, dest_path: str) -> None:
    """mysqldump de una BD a un .sql (con el admin MariaDB del panel)."""
    from scripts.backup_manager import _mysqldump_binary
    from api.routes.databases import MARIADB_HOST, MARIADB_PANEL_USER
    binary = _mysqldump_binary()
    if not binary:
        raise StagingError("mysqldump/mariadb-dump no encontrado en el servidor")
    cmd = [binary, "--single-transaction", "--routines", "--triggers",
           "--skip-lock-tables", f"--host={MARIADB_HOST}",
           f"--user={MARIADB_PANEL_USER}", db_name]
    try:
        with open(dest_path, "wb") as fh:
            r = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE,
                               env=_mariadb_env(), timeout=3600)
    except subprocess.TimeoutExpired:
        raise StagingError("mysqldump superó el tiempo máximo (1h)")
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace")
        raise StagingError(f"mysqldump de {db_name} falló: {err[:300]}")


def _import_db(db_name: str, sql_path: str) -> None:
    """Importa un .sql en la BD indicada (cliente CLI, admin del panel)."""
    from api.routes.databases import (_mariadb_binary, MARIADB_HOST,
                                      MARIADB_PANEL_USER)
    binary = _mariadb_binary()
    try:
        with open(sql_path, "rb") as fin:
            r = subprocess.run([binary, f"--host={MARIADB_HOST}",
                                f"--user={MARIADB_PANEL_USER}", db_name],
                               stdin=fin, capture_output=True,
                               env=_mariadb_env(), timeout=3600)
    except subprocess.TimeoutExpired:
        raise StagingError("La importación del dump superó el tiempo máximo (1h)")
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace")
        raise StagingError(f"Importación en {db_name} falló: {err[:300]}")


def _clone_db(src_db: str, dst_db: str, workdir: str) -> None:
    """Clona src_db → dst_db vía dump temporal en disco (no en /tmp: tmpfs)."""
    os.makedirs(workdir, mode=0o700, exist_ok=True)
    dump = os.path.join(workdir, f"{src_db}.clone.sql")
    try:
        _dump_db(src_db, dump)
        _import_db(dst_db, dump)
    finally:
        if os.path.exists(dump):
            os.remove(dump)


def _drop_db_and_user(db_name: str, db_user: str) -> None:
    """DROP de la BD y el usuario MariaDB del staging (best-effort)."""
    from api.routes.databases import _run_mariadb
    safe_name = db_name.replace("`", "``")
    safe_user = db_user.replace("'", "''")
    for sql in (f"DROP DATABASE IF EXISTS `{safe_name}`;",
                f"DROP USER IF EXISTS '{safe_user}'@'localhost';",
                "FLUSH PRIVILEGES;"):
        try:
            _run_mariadb(sql)
        except Exception as e:
            logger.warning(f"Staging: limpieza MariaDB '{sql[:40]}…': {e}")


def _search_replace(docroot: str, owner: str, old_url: str, new_url: str,
                    php_version=None) -> None:
    """Cambia las URLs con wp search-replace (respeta datos serializados).
    Se reemplazan ambas variantes de esquema para no dejar mixed content."""
    old_host = old_url.split("://", 1)[-1]
    for old in (f"https://{old_host}", f"http://{old_host}"):
        rc, out, err = _wp(docroot, owner,
                           ["search-replace", old, new_url, "--all-tables"],
                           php_version, timeout=1800, skip_plugins=True)
        if rc != 0:
            raise StagingError(f"search-replace falló: {(err or out)[:300]}")


# ─────────────────────────────────────────────────────────────────────────────
# Consulta de estado (para el endpoint GET)
# ─────────────────────────────────────────────────────────────────────────────
def get_status(live_domain, db) -> Dict:
    """Estado del staging de un dominio live: si existe, sus datos y el job."""
    from api.models.models_domain import Domain
    staging = (db.query(Domain)
                 .filter(Domain.staging_of_domain_id == live_domain.id)
                 .first())
    data = {
        "exists": staging is not None,
        "staging": None,
        "job": job_status(live_domain.id),
        "staging_name": staging_name_for(live_domain.domain_name),
    }
    if staging:
        scheme = "https" if staging.ssl_enabled else "http"
        data["staging"] = {
            "id": staging.id,
            "domain_name": staging.domain_name,
            "url": f"{scheme}://{staging.domain_name}",
            "ssl_enabled": bool(staging.ssl_enabled),
            "created_at": staging.created_at.isoformat() if staging.created_at else None,
        }
    return data


# ─────────────────────────────────────────────────────────────────────────────
# CREAR STAGING (job en background)
# ─────────────────────────────────────────────────────────────────────────────
CREATE_STEPS = [
    "Creando el subdominio de staging",
    "Copiando los archivos del sitio",
    "Clonando la base de datos",
    "Emitiendo el certificado SSL",
    "Configurando el WordPress de staging",
]


def run_create(live_domain_id: int) -> None:
    """Job: clona el WP del dominio live a staging.{dominio}. Con rollback."""
    from api.models.database import SessionLocal, load_all_models
    load_all_models()
    db = SessionLocal()

    created = {"system": False, "row": None, "dns": False,
               "db_name": None, "db_user": None}
    try:
        _do_create(db, live_domain_id, created)
        _job_end(live_domain_id)
    except Exception as e:
        logger.exception(f"Staging: fallo creando staging del dominio {live_domain_id}")
        _rollback_create(db, created)
        msg = str(e) if isinstance(e, StagingError) else f"Error inesperado: {e}"
        _job_end(live_domain_id, error=msg)
    finally:
        db.close()


def _do_create(db, live_domain_id: int, created: dict) -> None:
    from api.models.models_domain import Domain
    from api.models.models_user import User
    from scripts.domain_manager import DomainManager
    from scripts.utils import get_domain_root

    live = db.query(Domain).filter(Domain.id == live_domain_id).first()
    if not live:
        raise StagingError("Dominio live no encontrado")
    owner = db.query(User).filter(User.id == live.user_id).first()
    if not owner:
        raise StagingError("El dominio no tiene propietario")

    username = owner.username
    stg_name = staging_name_for(live.domain_name)
    live_docroot = (live.custom_docroot
                    or get_domain_root(username, live.domain_name) + "/public_html")
    stg_docroot = get_domain_root(username, stg_name) + "/public_html"
    php_version = live.php_version or "8.2"

    # ── 1. Subdominio (sistema + fila Domain + DNS) ──────────────────────────
    _job_step(live_domain_id, 0)
    DomainManager().create_domain(username, stg_name, php_version)
    created["system"] = True

    row = Domain(
        user_id=owner.id,
        domain_name=stg_name,
        php_version=php_version,
        public_html=stg_docroot,
        ipv4=live.ipv4,
        is_subdomain=True,
        parent_domain=live.parent_domain or live.domain_name,
        canonical_domain="none",
        staging_of_domain_id=live.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    created["row"] = row.id

    # DNS: A/AAAA en la zona padre si está gestionada (best-effort; si el DNS
    # del dominio vive fuera del panel, el cliente crea el registro él mismo).
    try:
        from api.routes.dns import apply_subdomain_dns
        res = apply_subdomain_dns(db, stg_name, ipv4=live.ipv4, ipv6=None)
        created["dns"] = (res == "parent")
    except Exception as e:
        logger.warning(f"Staging: DNS del subdominio {stg_name}: {e}")

    # ── 2. Archivos ──────────────────────────────────────────────────────────
    _job_step(live_domain_id, 1)
    # Quitar el index.html placeholder del alta para que no tape a WordPress.
    for ph in ("index.html", "index.nginx-debian.html"):
        p = os.path.join(stg_docroot, ph)
        if os.path.exists(p):
            os.remove(p)
    _sync_files(live_docroot, stg_docroot, username)

    # ── 3. Base de datos ─────────────────────────────────────────────────────
    _job_step(live_domain_id, 2)
    from api.routes.databases import _run_mariadb, MARIADB_ENABLED
    if not MARIADB_ENABLED:
        raise StagingError("MariaDB no está habilitado en este servidor")

    live_db_name = _wp_config_get(live_docroot, username, "DB_NAME", php_version)
    dbinfo = AppInstaller(run_sql=_run_mariadb)._create_db(username, "stg")
    created["db_name"] = dbinfo["db_name"]
    created["db_user"] = dbinfo["db_user"]
    _register_client_db(db, owner.id, row.id, dbinfo)
    _clone_db(live_db_name, dbinfo["db_name"],
              workdir=os.path.join(BACKUP_DIR, "tmp"))

    # ── 4. SSL (best-effort: puede fallar si el DNS aún no propaga) ─────────
    _job_step(live_domain_id, 3)
    ssl_ok = _issue_ssl(db, row, owner)

    # ── 5. Configurar el WP de staging ──────────────────────────────────────
    _job_step(live_domain_id, 4)
    live_url = _site_url(live_docroot, username, php_version)
    stg_url = f"{'https' if ssl_ok else 'http'}://{stg_name}"

    for key, val in (("DB_NAME", dbinfo["db_name"]),
                     ("DB_USER", dbinfo["db_user"]),
                     ("DB_PASSWORD", dbinfo["db_pass"])):
        _wp_or_fail(stg_docroot, username, ["config", "set", key, val],
                    php_version, skip_plugins=True,
                    msg=f"No pude fijar {key} en el wp-config de staging")

    _search_replace(stg_docroot, username, live_url, stg_url, php_version)

    # El staging no debe indexarse ni depender del cron de sistema del live.
    _wp(stg_docroot, username, ["option", "update", "blog_public", "0"],
        php_version, skip_plugins=True)
    _wp(stg_docroot, username, ["config", "delete", "DISABLE_WP_CRON"],
        php_version, skip_plugins=True)
    _wp(stg_docroot, username, ["cache", "flush"], php_version)


def _register_client_db(db, user_id: int, domain_id: int, dbinfo: dict) -> None:
    """Registra la BD clonada en client_databases (colgada del Domain staging)."""
    from api.models.models_client_db import ClientDatabase
    from api.routes.databases import _hash_password, _encrypt_password
    name, user_, pw = dbinfo["db_name"], dbinfo["db_user"], dbinfo["db_pass"]
    row = ClientDatabase(
        user_id=user_id,
        domain_id=domain_id,
        db_name=name,
        db_name_suffix=name.split("_", 1)[-1] if "_" in name else name,
        db_user=user_,
        db_user_suffix=user_.split("_", 1)[-1] if "_" in user_ else user_,
        db_password_hash=_hash_password(pw),
        db_password_enc=_encrypt_password(pw),
        is_active=True,
    )
    db.add(row)
    db.commit()


def _issue_ssl(db, staging_row, owner) -> bool:
    """Intenta emitir Let's Encrypt para el staging. True si hay cert activo."""
    email = (owner.email or "").strip()
    if not email or "@" not in email or email.endswith("local.invalid"):
        return False
    try:
        from scripts.ssl_manager import SSLManager
        from datetime import timedelta
        SSLManager().create_ssl_with_email(staging_row.domain_name, email)
        staging_row.ssl_enabled = True
        staging_row.ssl_expires = datetime.utcnow() + timedelta(days=90)
        staging_row.ssl_renewed_at = datetime.utcnow()
        staging_row.force_https = True
        db.commit()
        _regen_vhost(staging_row, owner.username)
        return True
    except Exception as e:
        logger.info(f"Staging: SSL de {staging_row.domain_name} no emitido "
                    f"(seguirá en HTTP): {e}")
        return False


def _regen_vhost(domain_row, username: str) -> None:
    """Regenera el vhost del staging con su estado actual (tras emitir SSL)."""
    from scripts.domain_manager import DomainManager
    from scripts import php_ini_manager as phpini
    php_sock = (phpini.pool_socket_path(domain_row.domain_name)
                if phpini.has_pool(domain_row.domain_name) else None)
    DomainManager().regenerate_vhost(
        username=username,
        domain_name=domain_row.domain_name,
        php_version=domain_row.php_version or "8.2",
        ssl_enabled=domain_row.ssl_enabled,
        ipv4=domain_row.ipv4,
        php_socket_override=php_sock,
        force_https=domain_row.force_https,
        canonical_domain="none",
        is_subdomain=True,
    )


def _rollback_create(db, created: dict) -> None:
    """Deshace lo creado por un create fallido (best-effort, en orden inverso)."""
    from api.models.models_domain import Domain
    from api.models.models_client_db import ClientDatabase
    from api.models.models_user import User

    if created.get("db_name"):
        _drop_db_and_user(created["db_name"], created["db_user"] or "")
        try:
            db.query(ClientDatabase).filter(
                ClientDatabase.db_name == created["db_name"]).delete()
            db.commit()
        except Exception:
            db.rollback()

    row = None
    if created.get("row"):
        row = db.query(Domain).filter(Domain.id == created["row"]).first()

    if created.get("dns") and row:
        try:
            from api.routes.dns import remove_subdomain_dns
            remove_subdomain_dns(db, row.domain_name)
        except Exception as e:
            logger.warning(f"Staging rollback DNS: {e}")

    if created.get("system") and row:
        try:
            owner = db.query(User).filter(User.id == row.user_id).first()
            from scripts.domain_manager import DomainManager
            DomainManager().delete_domain(row.domain_name,
                                          username=owner.username if owner else None)
        except Exception as e:
            logger.warning(f"Staging rollback sistema: {e}")

    if row:
        try:
            db.delete(row)
            db.commit()
        except Exception:
            db.rollback()


# ─────────────────────────────────────────────────────────────────────────────
# PUSH TO LIVE (job en background)
# ─────────────────────────────────────────────────────────────────────────────
PUSH_STEPS = [
    "Copia de seguridad del sitio live",
    "Sincronizando archivos al live",
    "Volcando la base de datos",
    "Ajustando las URLs",
    "Limpiando cachés",
]


def run_push(live_domain_id: int) -> None:
    """Job: vuelca archivos+BD del staging a producción, con backup previo."""
    from api.models.database import SessionLocal, load_all_models
    load_all_models()
    db = SessionLocal()
    try:
        _do_push(db, live_domain_id)
        _job_end(live_domain_id)
    except Exception as e:
        logger.exception(f"Staging: fallo en push del dominio {live_domain_id}")
        msg = str(e) if isinstance(e, StagingError) else f"Error inesperado: {e}"
        _job_end(live_domain_id, error=msg)
    finally:
        db.close()


def _do_push(db, live_domain_id: int) -> None:
    from api.models.models_domain import Domain
    from api.models.models_user import User
    from scripts.utils import get_domain_root

    live = db.query(Domain).filter(Domain.id == live_domain_id).first()
    staging = (db.query(Domain)
                 .filter(Domain.staging_of_domain_id == live_domain_id).first())
    if not live or not staging:
        raise StagingError("No hay un staging para este dominio")
    owner = db.query(User).filter(User.id == live.user_id).first()
    username = owner.username

    php_version = live.php_version or "8.2"
    live_docroot = (live.custom_docroot
                    or get_domain_root(username, live.domain_name) + "/public_html")
    stg_docroot = get_domain_root(username, staging.domain_name) + "/public_html"

    live_db_name = _wp_config_get(live_docroot, username, "DB_NAME", php_version)
    stg_db_name = _wp_config_get(stg_docroot, username, "DB_NAME",
                                 staging.php_version or php_version)
    if live_db_name == stg_db_name:
        raise StagingError("El staging usa la MISMA base de datos que el live; "
                           "push abortado para no corromper el sitio.")

    # Estado del live a preservar tras el volcado (el push no debe des-indexar
    # el sitio de producción por heredar el blog_public=0 del staging).
    live_url = _site_url(live_docroot, username, php_version)
    rc, live_blog_public, _ = _wp(live_docroot, username,
                                  ["option", "get", "blog_public"],
                                  php_version, skip_plugins=True)
    live_blog_public = live_blog_public.strip() if rc == 0 else "1"
    stg_url = _site_url(stg_docroot, username, staging.php_version or php_version)

    # ── 1. Backup previo del live (tar + dump) ───────────────────────────────
    _job_step(live_domain_id, 0)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    bdir = os.path.join(BACKUP_DIR, live.domain_name, stamp)
    os.makedirs(bdir, mode=0o700, exist_ok=True)
    rc, _out, err = _run(["tar", "-czf", os.path.join(bdir, "files.tar.gz"),
                          "-C", live_docroot, "."], timeout=3600)
    if rc != 0:
        raise StagingError(f"Backup de archivos del live falló: {(err or '')[:300]}")
    _dump_db(live_db_name, os.path.join(bdir, "database.sql"))
    _run(["gzip", "-f", os.path.join(bdir, "database.sql")], timeout=1800)
    _prune_backups(live.domain_name)

    # ── 2. Archivos staging → live (el live conserva su wp-config.php) ──────
    _job_step(live_domain_id, 1)
    _sync_files(stg_docroot, live_docroot, username, delete=True,
                excludes=("wp-config.php",))

    # ── 3. BD staging → BD del live ─────────────────────────────────────────
    _job_step(live_domain_id, 2)
    _clone_db(stg_db_name, live_db_name,
              workdir=os.path.join(BACKUP_DIR, "tmp"))

    # ── 4. URLs de vuelta a producción ───────────────────────────────────────
    _job_step(live_domain_id, 3)
    _search_replace(live_docroot, username, stg_url, live_url, php_version)
    _wp(live_docroot, username,
        ["option", "update", "blog_public", live_blog_public or "1"],
        php_version, skip_plugins=True)

    # ── 5. Cachés ────────────────────────────────────────────────────────────
    _job_step(live_domain_id, 4)
    _wp(live_docroot, username, ["cache", "flush"], php_version)
    _wp(live_docroot, username, ["rewrite", "flush"], php_version)


def _prune_backups(domain_name: str) -> None:
    """Conserva solo las KEEP_BACKUPS copias más recientes del dominio."""
    base = os.path.join(BACKUP_DIR, domain_name)
    try:
        dirs = sorted(d for d in os.listdir(base)
                      if os.path.isdir(os.path.join(base, d)))
        for old in dirs[:-KEEP_BACKUPS]:
            shutil.rmtree(os.path.join(base, old), ignore_errors=True)
    except FileNotFoundError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# ELIMINAR STAGING (job en background)
# ─────────────────────────────────────────────────────────────────────────────
DELETE_STEPS = [
    "Eliminando la base de datos de staging",
    "Eliminando el subdominio de staging",
]


def run_delete(live_domain_id: int) -> None:
    """Job: borra BD + subdominio + DNS + fila del staging."""
    from api.models.database import SessionLocal, load_all_models
    load_all_models()
    db = SessionLocal()
    try:
        _do_delete(db, live_domain_id)
        _job_end(live_domain_id)
    except Exception as e:
        logger.exception(f"Staging: fallo eliminando staging del dominio {live_domain_id}")
        msg = str(e) if isinstance(e, StagingError) else f"Error inesperado: {e}"
        _job_end(live_domain_id, error=msg)
    finally:
        db.close()


def _do_delete(db, live_domain_id: int) -> None:
    from api.models.models_domain import Domain
    from api.models.models_user import User
    from api.models.models_client_db import ClientDatabase
    from scripts.domain_manager import DomainManager

    staging = (db.query(Domain)
                 .filter(Domain.staging_of_domain_id == live_domain_id).first())
    if not staging:
        raise StagingError("No hay un staging para este dominio")
    owner = db.query(User).filter(User.id == staging.user_id).first()
    username = owner.username if owner else None

    # 1. BDs del staging (MariaDB + registro del panel)
    _job_step(live_domain_id, 0)
    for cdb in (db.query(ClientDatabase)
                  .filter(ClientDatabase.domain_id == staging.id).all()):
        _drop_db_and_user(cdb.db_name, cdb.db_user)

    # 2. Subdominio: vhost + pool + dirs + DNS (misma secuencia que DELETE /domains)
    _job_step(live_domain_id, 1)
    DomainManager().delete_domain(staging.domain_name, username=username)
    try:
        from scripts import php_ini_manager as phpini
        from scripts.utils import remove_fastcgi_cache_zone
        phpini.remove_pool(staging.domain_name)
        remove_fastcgi_cache_zone(staging.domain_name)
    except Exception as e:
        logger.warning(f"Staging: limpieza pool/cache de {staging.domain_name}: {e}")
    try:
        from api.routes.dns import remove_subdomain_dns
        remove_subdomain_dns(db, staging.domain_name)
    except Exception as e:
        logger.warning(f"Staging: DNS de {staging.domain_name}: {e}")

    # La fila Domain (cascade borra sus client_databases del panel)
    db.delete(staging)
    db.commit()
