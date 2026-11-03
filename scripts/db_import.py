"""
SVQPanel — importación de bases de datos grandes (sin phpMyAdmin).

phpMyAdmin importa dentro de UNA petición web: choca con el tamaño de subida de
PHP, el max_execution_time y los timeouts de nginx, y si se corta hay que
empezar de cero. Aquí:

  1. El fichero (.sql, .sql.gz, .gz o .zip) llega a ~/imports del dueño de la
     BD: subido por SFTP, o desde el panel EN TROZOS (append_chunk), que se
     reanuda donde se quedó si se corta. Mientras sube se llama
     .{nombre}.{tamaño}.part y se renombra al completarse.
  2. El import corre como unidad transitoria de systemd (como apt_runner):
     fuera del cgroup del panel, sin límite de tiempo y sobrevive a reinicios
     del panel. Descomprime al vuelo y lo pasa al cliente `mariadb`.
  3. El estado se escribe en STATE_DIR/{db_id}.json y la UI lo consulta.

Seguridad:
  - Se importa con el USUARIO DE ESA BD, nunca con el admin del panel: un
    .sql no puede tocar otras BDs (USE otra / INSERT INTO otra.tabla fallan).
  - El panel corre como root y la carpeta es del cliente: todo se abre con
    O_NOFOLLOW relativo al fd de la carpeta y se exige fichero regular cuyo
    dueño sea el cliente (si no, un symlink a /etc/shadow acabaría en su BD).
  - Se quitan los DEFINER=… (fallan sin SUPER; el objeto pasa a ser del
    usuario de la BD) y las líneas CREATE DATABASE / USE `x` de los volcados
    hechos con --databases.
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import logging

logger = logging.getLogger(__name__)

IMPORTS_DIRNAME = "imports"
STATE_DIR = "/var/lib/svqpanel/db-imports"
ALLOWED_EXT = (".sql", ".sql.gz", ".gz", ".zip")
MAX_CHUNK = 64 * 1024 * 1024
READ_BLOCK = 4 * 1024 * 1024
DISK_MARGIN = 1024 * 1024 * 1024   # deja 1 GB libre en el disco como mínimo

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,180}$")
_DEFINER_RE = re.compile(
    rb"DEFINER\s*=\s*(?:`[^`]*`|'[^']*'|[^\s@]+)@(?:`[^`]*`|'[^']*'|[^\s*]+)\s*")
_DBSTMT_RE = re.compile(rb"(?m)^(?:CREATE DATABASE\b|USE\s+`)[^\n]*$")


class ImportError_(Exception):
    """Error con mensaje para el usuario (la API lo devuelve como 4xx)."""


# ─────────────────────────────────────────────────────────────────────────────
# Carpeta ~/imports
# ─────────────────────────────────────────────────────────────────────────────
def valid_name(name: str) -> bool:
    return bool(name and _NAME_RE.match(name) and ".." not in name
                and name.lower().endswith(ALLOWED_EXT))


def _owner(username: str):
    import pwd   # solo existe en Linux (los tests corren también en Windows)
    try:
        pw = pwd.getpwnam(username)
    except KeyError:
        raise ImportError_(f"El usuario del sistema {username} no existe")
    return pw.pw_uid, pw.pw_gid, pw.pw_dir


def imports_path(username: str) -> str:
    return os.path.join(_owner(username)[2], IMPORTS_DIRNAME)


def open_imports_dir(username: str, create: bool = True) -> int:
    """fd de ~/imports (O_NOFOLLOW), creándola si falta. Exige que sea del cliente."""
    uid, gid, home = _owner(username)
    path = os.path.join(home, IMPORTS_DIRNAME)
    if create and not os.path.lexists(path):
        os.mkdir(path, 0o750)
        os.chown(path, uid, gid)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    st = os.fstat(fd)
    if st.st_uid != uid:
        os.close(fd)
        raise ImportError_(f"{path} no pertenece a {username}")
    return fd


def _open_owned(dfd: int, name: str, uid: int, flags=os.O_RDONLY) -> int:
    fd = os.open(name, flags | os.O_NOFOLLOW, dir_fd=dfd)
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_uid != uid:
        os.close(fd)
        raise ImportError_("El fichero no es válido (debe ser un fichero normal de tu cuenta)")
    return fd


def list_files(username: str) -> dict:
    """Ficheros importables y subidas a medias de ~/imports."""
    uid = _owner(username)[0]
    dfd = open_imports_dir(username)
    files, partial = [], []
    try:
        for e in os.scandir(dfd):
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode) or st.st_uid != uid:
                continue
            m = re.match(r"^\.(.+)\.(\d+)\.part$", e.name)
            if m and valid_name(m.group(1)):
                partial.append({"name": m.group(1), "size": int(m.group(2)),
                                "received": st.st_size, "mtime": int(st.st_mtime)})
            elif valid_name(e.name):
                files.append({"name": e.name, "size": st.st_size,
                              "mtime": int(st.st_mtime)})
    finally:
        os.close(dfd)
    files.sort(key=lambda f: -f["mtime"])
    return {"path": imports_path(username), "files": files, "partial": partial}


def delete_file(username: str, name: str, size: int | None = None) -> None:
    """Borra un fichero de ~/imports (o la subida a medias si se da size)."""
    if not valid_name(name):
        raise ImportError_("Nombre de fichero no válido")
    target = f".{name}.{int(size)}.part" if size is not None else name
    uid = _owner(username)[0]
    dfd = open_imports_dir(username)
    try:
        os.close(_open_owned(dfd, target, uid))
        os.unlink(target, dir_fd=dfd)
    except FileNotFoundError:
        pass
    finally:
        os.close(dfd)


# ─────────────────────────────────────────────────────────────────────────────
# Subida por trozos (reanudable)
# ─────────────────────────────────────────────────────────────────────────────
def upload_offset(username: str, name: str, size: int) -> int:
    """Bytes ya recibidos de esa subida (0 si no hay nada a medias)."""
    if not valid_name(name):
        raise ImportError_("Nombre de fichero no válido (.sql, .sql.gz, .gz o .zip)")
    uid = _owner(username)[0]
    dfd = open_imports_dir(username)
    try:
        fd = _open_owned(dfd, f".{name}.{int(size)}.part", uid)
        n = os.fstat(fd).st_size
        os.close(fd)
        return n
    except FileNotFoundError:
        return 0
    finally:
        os.close(dfd)


def check_space(username: str, size: int, quota_mb: int, used_mb: int) -> None:
    """Antes de aceptar una subida: hueco en el disco y en la cuota del cliente.
    (El panel escribe como root y root no respeta la cuota: hay que mirarla.)"""
    free = shutil.disk_usage(_owner(username)[2]).free
    if size + DISK_MARGIN > free:
        raise ImportError_(
            f"No hay espacio en el servidor: el fichero ocupa {size // 2**20} MB "
            f"y quedan {free // 2**20} MB libres")
    if quota_mb and quota_mb > 0 and used_mb + size // 2**20 > quota_mb:
        raise ImportError_(
            f"El fichero ({size // 2**20} MB) no cabe en tu cuota de disco "
            f"({used_mb} de {quota_mb} MB usados)")


def append_chunk(username: str, name: str, size: int, offset: int, data: bytes) -> dict:
    """Añade un trozo. offset debe coincidir con lo ya recibido (si no, se
    devuelve el bueno para que el navegador siga desde ahí)."""
    if not valid_name(name):
        raise ImportError_("Nombre de fichero no válido (.sql, .sql.gz, .gz o .zip)")
    if len(data) > MAX_CHUNK:
        raise ImportError_("Trozo demasiado grande")
    if offset + len(data) > size:
        raise ImportError_("El trozo se sale del tamaño declarado")
    uid, gid, _ = _owner(username)
    part = f".{name}.{int(size)}.part"
    dfd = open_imports_dir(username)
    try:
        try:
            fd = _open_owned(dfd, part, uid, os.O_WRONLY | os.O_APPEND)
        except FileNotFoundError:
            if offset != 0:
                return {"offset": 0, "done": False, "mismatch": True}
            fd = os.open(part, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_EXCL
                         | os.O_NOFOLLOW, 0o640, dir_fd=dfd)
            os.fchown(fd, uid, gid)
        try:
            cur = os.fstat(fd).st_size
            if cur != offset:
                return {"offset": cur, "done": False, "mismatch": True}
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            cur += len(data)
        finally:
            os.close(fd)
        done = cur == size
        if done:
            os.replace(part, name, src_dir_fd=dfd, dst_dir_fd=dfd)
        return {"offset": cur, "done": done}
    finally:
        os.close(dfd)


# ─────────────────────────────────────────────────────────────────────────────
# Trabajo de import (unidad systemd) y su estado
# ─────────────────────────────────────────────────────────────────────────────
def _state_path(db_id: int) -> str:
    return os.path.join(STATE_DIR, f"{int(db_id)}.json")


def _read_state(db_id: int) -> dict:
    try:
        with open(_state_path(db_id)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write_state(db_id: int, st: dict) -> None:
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    tmp = _state_path(db_id) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, _state_path(db_id))


def _unit_active(unit: str) -> bool:
    if not unit:
        return False
    try:
        r = subprocess.run(["systemctl", "is-active", unit],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() in ("active", "activating")
    except Exception:  # noqa: BLE001
        return False


def _alive(st: dict) -> bool:
    if st.get("unit"):
        return _unit_active(st["unit"])
    pid = int(st.get("pid") or 0)
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def status(db_id: int) -> dict:
    st = _read_state(db_id)
    if not st:
        return {"exists": False, "running": False}
    if st.get("state") in ("starting", "running") and not _alive(st):
        # La unidad murió sin cerrar el estado: cancelada o el servidor se reinició.
        st["state"] = "error"
        st["error"] = st.get("error") or "La importación se interrumpió (cancelada o reinicio del servidor)."
        st["finished"] = st.get("finished") or int(time.time())
        _write_state(db_id, st)
    st["exists"] = True
    st["running"] = st.get("state") in ("starting", "running")
    st.pop("pid", None)
    return st


def start(db_id: int, filename: str, force: bool = False,
          delete_after: bool = False) -> dict:
    if status(db_id).get("running"):
        raise ImportError_("Ya hay una importación en curso en esta base de datos")
    unit = f"svqpanel-dbimport-{int(db_id)}-{int(time.time())}"
    cmd = [sys.executable, "-m", "api.cli", "db_import", str(int(db_id)), filename]
    if force:
        cmd.append("--force")
    if delete_after:
        cmd.append("--delete-after")
    st = {"state": "starting", "file": filename, "unit": unit,
          "started": int(time.time()), "force": force, "delete_after": delete_after}
    _write_state(db_id, st)
    rc = 1
    try:
        r = subprocess.run(
            ["systemd-run", f"--unit={unit}", "--collect", "--quiet",
             f"--working-directory={os.getcwd()}",
             "-p", "Nice=10", "-p", "IOSchedulingClass=best-effort",
             "-p", "IOSchedulingPriority=7", *cmd],
            capture_output=True, text=True, timeout=30)
        rc = r.returncode
        if rc != 0:
            logger.warning("db_import: systemd-run falló (%s): %s", rc, r.stderr.strip())
    except Exception as e:  # noqa: BLE001
        logger.warning("db_import: systemd-run no disponible: %s", e)
    if rc != 0:
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        st["unit"] = None
        st["pid"] = p.pid
        _write_state(db_id, st)
    return status(db_id)


def cancel(db_id: int) -> dict:
    st = _read_state(db_id)
    if st.get("unit"):
        subprocess.run(["systemctl", "stop", st["unit"]], capture_output=True, timeout=30)
    elif st.get("pid"):
        try:
            os.killpg(int(st["pid"]), 15)
        except OSError:
            pass
    if st.get("state") in ("starting", "running"):
        st.update(state="error", error="Importación cancelada.", finished=int(time.time()))
        _write_state(db_id, st)
    return status(db_id)


# ─────────────────────────────────────────────────────────────────────────────
# El import en sí (corre dentro de la unidad, vía `api.cli db_import`)
# ─────────────────────────────────────────────────────────────────────────────
def filter_sql(chunk: bytes) -> bytes:
    if b"DEFINER" in chunk:
        chunk = _DEFINER_RE.sub(b"", chunk)
    if b"CREATE DATABASE" in chunk or b"USE `" in chunk:
        chunk = _DBSTMT_RE.sub(b"-- svqpanel: omitido (se importa en la BD elegida)", chunk)
    return chunk


def _open_source(raw, name: str):
    """Devuelve (stream descomprimido, función de progreso 0..1, tamaño a mostrar)."""
    import gzip
    import zipfile
    total = os.fstat(raw.fileno()).st_size or 1
    low = name.lower()
    if low.endswith(".zip"):
        zf = zipfile.ZipFile(raw)
        sqls = [i for i in zf.infolist() if i.filename.lower().endswith(".sql")
                and not i.is_dir()]
        if not sqls:
            raise ImportError_("El .zip no contiene ningún fichero .sql")
        member = max(sqls, key=lambda i: i.file_size)
        stream = zf.open(member)
        done = [0]

        class _Counted:
            def read(self, n):
                b = stream.read(n)
                done[0] += len(b)
                return b
        return _Counted(), lambda: done[0] / (member.file_size or 1)
    if low.endswith(".gz"):
        return gzip.GzipFile(fileobj=raw), lambda: raw.tell() / total
    return raw, lambda: raw.tell() / total


def _clean_err(text: str) -> str:
    lines = [ln for ln in text.splitlines()
             if "Using a password" not in ln and "Deprecated program name" not in ln]
    return "\n".join(lines)[-3000:].strip()


def run_import(db_id: int, filename: str, force: bool = False,
               delete_after: bool = False) -> int:
    from api.models.database import SessionLocal, load_all_models
    load_all_models()
    from api.models.models_client_db import ClientDatabase
    from api.models.models_user import User
    from api.routes.databases import (_decrypt_password, _mariadb_binary,
                                      MARIADB_HOST)

    st = _read_state(db_id) or {"file": filename, "started": int(time.time())}
    st.update(state="running", file=filename, pid=os.getpid(), done=0, progress=0.0)
    _write_state(db_id, st)

    def fail(msg: str) -> int:
        st.update(state="error", error=msg, finished=int(time.time()))
        _write_state(db_id, st)
        return 1

    db = SessionLocal()
    try:
        cdb = db.query(ClientDatabase).filter(ClientDatabase.id == db_id).first()
        owner = cdb and db.query(User).filter(User.id == cdb.user_id).first()
        if not cdb or not owner:
            return fail("La base de datos ya no existe")
        db_name, db_user, username = cdb.db_name, cdb.db_user, owner.username
        password = _decrypt_password(cdb.db_password_enc or "")
    finally:
        db.close()
    if not password:
        return fail("El panel no tiene guardada la contraseña de esta BD. "
                    "Cámbiala desde el panel y vuelve a intentarlo.")

    try:
        uid = _owner(username)[0]
        dfd = open_imports_dir(username, create=False)
        try:
            fd = _open_owned(dfd, filename, uid)
        finally:
            os.close(dfd)
    except FileNotFoundError:
        return fail(f"No existe {filename} en la carpeta imports")
    except (ImportError_, OSError) as e:
        return fail(str(e))

    raw = os.fdopen(fd, "rb", buffering=READ_BLOCK)
    st["total"] = os.fstat(fd).st_size
    try:
        src, progress = _open_source(raw, filename)
    except Exception as e:  # noqa: BLE001
        raw.close()
        return fail(f"No se puede leer el fichero: {e}")

    cmd = [_mariadb_binary(), f"--host={MARIADB_HOST}", f"--user={db_user}",
           "--default-character-set=utf8mb4", "--max-allowed-packet=1G"]
    if force:
        cmd.append("--force")
    cmd.append(db_name)
    err_path = os.path.join(STATE_DIR, f"{int(db_id)}.err")
    with open(err_path, "wb") as errf:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=errf, env={**os.environ, "MYSQL_PWD": password})
        broken = False
        try:
            proc.stdin.write(b"SET FOREIGN_KEY_CHECKS=0;\n")
            rest, last = b"", 0.0
            while True:
                block = src.read(READ_BLOCK)
                if not block:
                    break
                block = rest + block
                cut = block.rfind(b"\n") + 1
                if cut == 0:
                    rest = block
                    continue
                rest = block[cut:]
                proc.stdin.write(filter_sql(block[:cut]))
                now = time.time()
                if now - last > 2:
                    last = now
                    st["progress"] = round(min(progress(), 1.0), 4)
                    _write_state(db_id, st)
            if rest:
                proc.stdin.write(filter_sql(rest))
            proc.stdin.write(b"\nSET FOREIGN_KEY_CHECKS=1;\n")
        except BrokenPipeError:
            broken = True   # mariadb se paró por un error: lo cuenta su stderr
        except Exception as e:  # noqa: BLE001
            proc.kill()
            raw.close()
            return fail(f"Error leyendo el fichero: {e}")
        finally:
            try:
                proc.stdin.close()
            except BrokenPipeError:
                pass
        rc = proc.wait()
    raw.close()
    try:
        with open(err_path, "rb") as f:
            err = _clean_err(f.read().decode("utf-8", "replace"))
        os.unlink(err_path)
    except OSError:
        err = ""

    # Con --force mariadb sigue tras cada error y acaba con rc≠0 si hubo alguno:
    # eso es un import terminado con avisos, no un fallo.
    if broken or (rc != 0 and not force):
        return fail(err or f"mariadb terminó con código {rc}")
    st.update(state="done", progress=1.0, finished=int(time.time()),
              warnings=err or None)
    if delete_after:
        try:
            delete_file(username, filename)
            st["deleted"] = True
        except Exception as e:  # noqa: BLE001
            logger.warning("db_import: no se pudo borrar %s: %s", filename, e)
    _write_state(db_id, st)
    return 0
