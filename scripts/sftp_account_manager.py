"""
Gestión de cuentas SFTP adicionales (subcuentas) con jaula estricta.

Cada subcuenta:
  - Es un usuario Linux real (nologin), miembro del grupo 'sftponly' y del
    grupo primario del propietario.
  - Su HOME es la jaula /home/{owner}/.sftp-jails/{label} (root:root 755),
    así el bloque global 'Match Group sftponly' (ChrootDirectory %h) la
    enjaula automáticamente.
  - Dentro de la jaula, la carpeta destino del cliente se expone vía
    bind-mount: {jail}/{mount_name} → {target_path}. Persistente en fstab.
  - El acceso de escritura se concede con ACLs (setfacl) sobre target_path,
    sin alterar la propiedad owner:www-data que usan nginx/PHP.

Seguridad: target_path SIEMPRE debe resolverse dentro de /home/{owner}/.
"""

import logging
import os
import re
import subprocess
from typing import Dict, List, Optional, Tuple

from scripts import sftp_manager  # reutilizamos helpers de claves/password

logger = logging.getLogger(__name__)

_SYS_ENV = {
    **os.environ,
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
}

FSTAB = "/etc/fstab"
FSTAB_MARK = "# svqpanel-sftp-jail"
JAILS_SUBDIR = ".sftp-jails"
LABEL_RE = re.compile(r"^[a-z][a-z0-9_]{1,15}$")


def _run(cmd: List[str], input_text: Optional[str] = None, timeout: int = 15) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           input=input_text, timeout=timeout, env=_SYS_ENV)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError as e:
        return 127, "", str(e)
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


# ─────────────────────────────────────────────────────────────────────────────
# Rutas / validación
# ─────────────────────────────────────────────────────────────────────────────
def owner_home(owner: str) -> str:
    return f"/home/{owner}"


def make_username(owner: str, label: str) -> str:
    """usuario Linux = {owner}_{label}, recortado a 32 chars (límite Linux)."""
    base = f"{owner}_{label}"
    return base[:32]


def jail_path(owner: str, label: str) -> str:
    return os.path.join(owner_home(owner), JAILS_SUBDIR, label)


def resolve_target(owner: str, subpath: str) -> Optional[str]:
    """
    Resuelve subpath (relativo al home del cliente o absoluto) y valida que
    cae ESTRICTAMENTE dentro de /home/{owner}/. Devuelve la ruta canónica o None.
    """
    home = owner_home(owner)
    subpath = (subpath or "").strip()
    if subpath.startswith("/"):
        candidate = subpath
    else:
        candidate = os.path.join(home, subpath)
    # Normalizar resolviendo .. y symlinks
    real_home = os.path.realpath(home)
    real_cand = os.path.realpath(candidate)
    if real_cand == real_home or real_cand.startswith(real_home + os.sep):
        return real_cand
    return None


# ─────────────────────────────────────────────────────────────────────────────
# fstab / mount
# ─────────────────────────────────────────────────────────────────────────────
def _fstab_line(target: str, mountpoint: str) -> str:
    return f"{target} {mountpoint} none bind 0 0  {FSTAB_MARK}"


def _add_fstab(target: str, mountpoint: str) -> None:
    line = _fstab_line(target, mountpoint)
    try:
        with open(FSTAB) as f:
            content = f.read()
        if mountpoint in content:
            return
        with open(FSTAB, "a") as f:
            if not content.endswith("\n"):
                f.write("\n")
            f.write(line + "\n")
    except OSError as e:
        logger.warning(f"fstab add falló: {e}")


def _remove_fstab(mountpoint: str) -> None:
    try:
        with open(FSTAB) as f:
            lines = f.readlines()
        kept = [l for l in lines if not (FSTAB_MARK in l and mountpoint in l)]
        if len(kept) != len(lines):
            with open(FSTAB, "w") as f:
                f.writelines(kept)
    except OSError as e:
        logger.warning(f"fstab remove falló: {e}")


def _is_mounted(mountpoint: str) -> bool:
    rc, out, _ = _run(["mountpoint", "-q", mountpoint], timeout=6)
    return rc == 0


# ─────────────────────────────────────────────────────────────────────────────
# Crear / borrar subcuenta
# ─────────────────────────────────────────────────────────────────────────────
def create_account(owner: str, label: str, target_subpath: str,
                    password: Optional[str] = None) -> Tuple[bool, str, Dict]:
    """
    Crea la subcuenta completa. Devuelve (ok, msg, info).
    info incluye username, jail_path, target_path, mount_name.
    """
    if not LABEL_RE.match(label):
        return False, "label inválido (a-z, 0-9, _, empezar por letra, 2-16 chars)", {}

    target = resolve_target(owner, target_subpath)
    if not target:
        return False, "la carpeta destino debe estar dentro del espacio del cliente", {}
    if not os.path.isdir(target):
        return False, f"la carpeta destino no existe: {target_subpath}", {}

    username = make_username(owner, label)
    jail = jail_path(owner, label)
    mount_name = os.path.basename(target.rstrip("/")) or "data"

    # Asegurar grupo sftponly
    ok, msg = sftp_manager.ensure_sftp_group()
    if not ok:
        return False, f"grupo sftponly: {msg}", {}

    # 1. Crear usuario Linux (nologin, home=jail, grupo primario del owner)
    if not sftp_manager.user_exists(username):
        rc, _, err = _run([
            "useradd", "-M",                 # sin crear home (lo montamos nosotros)
            "-d", jail,
            "-s", "/usr/sbin/nologin",
            "-g", owner,                     # grupo primario = grupo del cliente
            "-G", "sftponly",
            username,
        ])
        if rc != 0:
            return False, f"useradd falló: {err.strip()}", {}

    # 2. Construir la jaula (root:root 755) + mountpoint
    #    El chroot exige que TODA la cadena hasta la jaula sea root:root y no
    #    escribible por grupo/otros. Aseguramos home y .sftp-jails (idempotente),
    #    así las subcuentas funcionan aunque el SFTP principal no esté activo.
    home = owner_home(owner)
    jails_base = os.path.join(home, JAILS_SUBDIR)
    _run(["chown", "root:root", home])
    _run(["chmod", "755", home])
    os.makedirs(jails_base, exist_ok=True)
    _run(["chown", "root:root", jails_base])
    _run(["chmod", "755", jails_base])
    os.makedirs(jail, exist_ok=True)
    _run(["chown", "root:root", jail])
    _run(["chmod", "755", jail])
    mountpoint = os.path.join(jail, mount_name)
    os.makedirs(mountpoint, exist_ok=True)
    _run(["chown", "root:root", mountpoint])
    _run(["chmod", "755", mountpoint])

    # .ssh dentro de la jaula (para authorized_keys), propiedad del subusuario
    ssh_dir = os.path.join(jail, ".ssh")
    os.makedirs(ssh_dir, exist_ok=True)
    auth = os.path.join(ssh_dir, "authorized_keys")
    if not os.path.isfile(auth):
        open(auth, "a").close()
    _run(["chown", "-R", f"{username}:{username}", ssh_dir])
    _run(["chmod", "700", ssh_dir])
    _run(["chmod", "600", auth])

    # 3. Bind-mount target → mountpoint + persistir en fstab
    if not _is_mounted(mountpoint):
        rc, _, err = _run(["mount", "--bind", target, mountpoint])
        if rc != 0:
            return False, f"mount --bind falló: {err.strip()}", {}
    _add_fstab(target, mountpoint)

    # 4. ACL: dar rwX al subusuario sobre el target (actual + por defecto)
    #    No toca owner:grupo:modo → nginx/php siguen igual.
    _run(["setfacl", "-R",  "-m", f"u:{username}:rwX", target])
    _run(["setfacl", "-R", "-d", "-m", f"u:{username}:rwX", target])
    # Permitir al subusuario atravesar la jaula hasta el mountpoint
    _run(["setfacl", "-m", f"u:{username}:rx", jail])

    # 5. Password opcional
    if password:
        sftp_manager.set_password(username, password)

    return True, "created", {
        "username": username,
        "jail_path": jail,
        "target_path": target,
        "mount_name": mount_name,
    }


def delete_account(owner: str, username: str, jail: str, target: str, mount_name: str) -> Tuple[bool, str]:
    """Desmonta, limpia fstab, borra usuario y jaula, y quita ACLs."""
    mountpoint = os.path.join(jail, mount_name)

    # 1. Desmontar
    if _is_mounted(mountpoint):
        rc, _, err = _run(["umount", mountpoint])
        if rc != 0:
            # intento lazy
            _run(["umount", "-l", mountpoint])
    _remove_fstab(mountpoint)

    # 2. Quitar ACL del subusuario sobre el target
    if target and os.path.isdir(target):
        _run(["setfacl", "-R", "-x", f"u:{username}", target])
        _run(["setfacl", "-R", "-d", "-x", f"u:{username}", target])

    # 3. Borrar usuario del sistema (-f por si una sesión SFTP recién cerrada
    #    dejó un proceso efímero que haría fallar a userdel sin forzar)
    if sftp_manager.user_exists(username):
        rc, _, err = _run(["userdel", "-f", username])
        if rc != 0:
            logger.warning(f"userdel -f {username} rc={rc}: {err.strip()}")

    # 4. Borrar la jaula (ya desmontada; rm normal, NO recursivo sobre el mount)
    import shutil
    if os.path.isdir(jail) and not _is_mounted(mountpoint):
        shutil.rmtree(jail, ignore_errors=True)

    return True, "deleted"


# ─────────────────────────────────────────────────────────────────────────────
# Claves SSH / password de subcuenta (envoltorio sobre sftp_manager con jaula)
# ─────────────────────────────────────────────────────────────────────────────
def _authorized_keys_path(jail: str) -> str:
    return os.path.join(jail, ".ssh", "authorized_keys")


def list_keys(jail: str, username: str) -> List[Dict[str, str]]:
    path = _authorized_keys_path(jail)
    if not os.path.isfile(path):
        return []
    out = []
    try:
        with open(path) as f:
            for line in f:
                parsed = sftp_manager._parse_key_line(line)
                if parsed:
                    out.append({"type": parsed["type"], "comment": parsed["comment"],
                                "fingerprint": parsed["fingerprint"]})
    except OSError:
        pass
    return out


def add_key(jail: str, username: str, public_key: str) -> Tuple[bool, str, Optional[str]]:
    parsed = sftp_manager._parse_key_line(public_key)
    if not parsed:
        return False, "clave pública no válida", None
    for k in list_keys(jail, username):
        if k["fingerprint"] == parsed["fingerprint"]:
            return False, "esa clave ya está añadida", parsed["fingerprint"]
    ssh_dir = os.path.join(jail, ".ssh")
    os.makedirs(ssh_dir, exist_ok=True)
    path = _authorized_keys_path(jail)
    line = f'{parsed["type"]} {parsed["key_b64"]}'
    if parsed["comment"]:
        line += f' {parsed["comment"]}'
    with open(path, "a") as f:
        f.write(line + "\n")
    _run(["chown", "-R", f"{username}:{username}", ssh_dir])
    _run(["chmod", "700", ssh_dir])
    _run(["chmod", "600", path])
    return True, "added", parsed["fingerprint"]


def remove_key(jail: str, username: str, fingerprint: str) -> Tuple[bool, str]:
    path = _authorized_keys_path(jail)
    if not os.path.isfile(path):
        return False, "no hay claves"
    kept, removed = [], False
    with open(path) as f:
        for line in f:
            parsed = sftp_manager._parse_key_line(line)
            if parsed and parsed["fingerprint"] == fingerprint:
                removed = True
                continue
            kept.append(line)
    if not removed:
        return False, "fingerprint no encontrado"
    with open(path, "w") as f:
        f.writelines(kept)
    _run(["chmod", "600", path])
    return True, "removed"


def set_password(username: str, password: str) -> Tuple[bool, str]:
    return sftp_manager.set_password(username, password)
