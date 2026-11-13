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


def normalize_subpath(owner: str, subpath: str) -> str:
    """Ruta relativa al home a partir de lo que escriba el cliente. Acepta:
      - web/dominio/private/x            (relativa al home, la forma «oficial»)
      - /home/{owner}/web/dominio/…      (absoluta)
      - /web/dominio/…                   (lo que enseña FileZilla: su raíz ES el home)
      - {owner}/web/dominio/…  o  ~/web/… (Chrome autorrellenaba el usuario delante)
    Solo quita prefijos: la contención en el home la sigue validando resolve_target."""
    home = owner_home(owner).rstrip("/")
    p = (subpath or "").strip().replace("\\", "/")
    if p == home or p.startswith(home + "/"):
        p = p[len(home):]
    elif p.startswith("~/") or p == "~":
        p = p[1:]
    p = p.lstrip("/")
    if (p == owner or p.startswith(owner + "/")) and \
            not os.path.isdir(os.path.join(home, owner)):
        p = p[len(owner):].lstrip("/")
    return p.rstrip("/")


def resolve_target(owner: str, subpath: str) -> Optional[str]:
    """
    Resuelve subpath (relativo al home del cliente o absoluto) y valida que
    cae ESTRICTAMENTE dentro de /home/{owner}/. Devuelve la ruta canónica o None.
    """
    home = owner_home(owner)
    candidate = os.path.join(home, normalize_subpath(owner, subpath))
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
        if any(FSTAB_MARK in l and l.split()[1:2] == [mountpoint]
               for l in content.splitlines()):
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
        # Comparar el CAMPO del punto de montaje, no una subcadena: «…/resources»
        # está contenido en «…/resources2» y se llevaría la línea de otra cuenta.
        kept = [l for l in lines
                if not (FSTAB_MARK in l and l.split()[1:2] == [mountpoint])]
        if len(kept) != len(lines):
            with open(FSTAB, "w") as f:
                f.writelines(kept)
    except OSError as e:
        logger.warning(f"fstab remove falló: {e}")


def _is_mounted(mountpoint: str) -> bool:
    rc, out, _ = _run(["mountpoint", "-q", mountpoint], timeout=6)
    return rc == 0


# ─────────────────────────────────────────────────────────────────────────────
# Escritura del owner (la web) sobre lo que crea la subcuenta
# ─────────────────────────────────────────────────────────────────────────────
def grant_owner_access(owner: str, subuser: str, target: str) -> Tuple[bool, str]:
    """
    El PHP de la web corre como el owner. Lo que sube la subcuenta SFTP es
    propiedad de la subcuenta, con el grupo (el del owner) en r-x: como el owner
    es de ese grupo, Linux le aplica la entrada del grupo y NO puede escribir,
    aunque «otros» tenga rwx (chmod 777 no lo arregla). Visto en
    social.beyuri.com: «no deja escribir en uploads/2026/11».

      - ACL por defecto u:{owner}:rwX en las carpetas (salvo las de root, como
        los logs) → lo nuevo nace escribible por la web;
      - ACL u:{owner}:rwX SOLO en lo que ya creó la subcuenta (no se amplía
        nada más: ni logs ni ficheros del sistema).
    Idempotente.
    """
    if not (target and os.path.isdir(target)):
        return False, "target inexistente"
    # Carpetas de root (logs del dominio…) fuera: no deben volverse editables
    rc1, _, e1 = _run(["find", target, "-xdev", "-type", "d", "!", "-user", "root",
                       "-exec", "setfacl", "-d", "-m", f"u:{owner}:rwX", "{}", "+"], timeout=600)
    rc2, _, e2 = _run(["find", target, "-xdev", "-user", subuser,
                       "-exec", "setfacl", "-m", f"u:{owner}:rwX", "{}", "+"], timeout=600)
    if rc1 or rc2:
        return False, (e1 or e2).strip()[-300:]
    return True, "ok"


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
        return False, ("nombre no válido: solo minúsculas, números y _ (sin guiones ni "
                       "espacios), empezando por letra, de 2 a 16 caracteres"), {}

    target, why = validate_target(owner, target_subpath)
    if not target:
        return False, why, {}

    username = make_username(owner, label)
    jail = jail_path(owner, label)
    mount_name = mount_name_for(target)

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
    #    …y que la WEB (PHP corre como el owner) pueda escribir en lo que suba
    #    la subcuenta: sin esto, sus carpetas nacen suyas con el grupo en r-x y
    #    el owner (mismo grupo) no puede escribir aunque se ponga 777.
    grant_owner_access(owner, username, target)
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


def mount_name_for(target: str) -> str:
    """Nombre de la carpeta que ve la subcuenta dentro de su jaula."""
    name = os.path.basename(target.rstrip("/")) or "data"
    return "data" if name == ".ssh" else name   # .ssh es de la jaula (authorized_keys)


def validate_target(owner: str, subpath: str) -> Tuple[Optional[str], str]:
    """(ruta canónica, "") o (None, motivo). Dentro del home y fuera de las jaulas."""
    target = resolve_target(owner, subpath)
    if not target:
        return None, "la carpeta destino debe estar dentro del espacio del cliente"
    jails = os.path.realpath(os.path.join(owner_home(owner), JAILS_SUBDIR))
    if target == jails or target.startswith(jails + os.sep):
        return None, "no se puede apuntar a la carpeta interna de las jaulas SFTP"
    if not os.path.isdir(target):
        return None, (f"la carpeta destino no existe: {target} "
                      "(se escribe desde tu home, p. ej. web/midominio.com/private/carpeta)")
    return target, ""


def _mount_into(target: str, mountpoint: str) -> Tuple[bool, str]:
    os.makedirs(mountpoint, exist_ok=True)
    _run(["chown", "root:root", mountpoint])
    _run(["chmod", "755", mountpoint])
    if not _is_mounted(mountpoint):
        rc, _, err = _run(["mount", "--bind", target, mountpoint])
        if rc != 0:
            return False, err.strip() or f"rc={rc}"
    _add_fstab(target, mountpoint)
    return True, "ok"


def _grant_subuser(owner: str, username: str, jail: str, target: str) -> None:
    _run(["setfacl", "-R",  "-m", f"u:{username}:rwX", target])
    _run(["setfacl", "-R", "-d", "-m", f"u:{username}:rwX", target])
    grant_owner_access(owner, username, target)
    _run(["setfacl", "-m", f"u:{username}:rx", jail])


def _revoke_subuser(username: str, target: str) -> None:
    if target and os.path.isdir(target):
        _run(["setfacl", "-R", "-x", f"u:{username}", target])
        _run(["setfacl", "-R", "-d", "-x", f"u:{username}", target])


def change_target(owner: str, username: str, jail: str, old_target: str,
                  old_mount_name: str, new_subpath: str) -> Tuple[bool, str, Dict]:
    """
    Re-enjaula una subcuenta en otra carpeta SIN recrearla (conserva usuario,
    contraseña y claves): desmonta la carpeta vieja, actualiza fstab, monta la
    nueva y mueve las ACL. Si el montaje nuevo falla, vuelve a montar la vieja.

    Por qué hace falta: el bind-mount persiste en fstab con la RUTA. Si el
    cliente mueve la carpeta con mv, la cuenta la sigue viendo hasta el próximo
    reinicio y entonces fstab monta la ruta vieja (vacía o inexistente).
    """
    new_target, why = validate_target(owner, new_subpath)
    if not new_target:
        return False, why, {}
    if not os.path.isdir(jail):
        return False, "la jaula de la subcuenta no existe en el disco", {}

    old_mp = os.path.join(jail, old_mount_name)
    new_mount = mount_name_for(new_target)
    new_mp = os.path.join(jail, new_mount)
    info = {"target_path": new_target, "mount_name": new_mount}

    if new_target == old_target and new_mp == old_mp and _is_mounted(old_mp):
        return True, "sin cambios", info

    # 1. Soltar la carpeta vieja (lazy si hay una sesión SFTP abierta dentro)
    if _is_mounted(old_mp):
        rc, _, err = _run(["umount", old_mp])
        if rc != 0:
            _run(["umount", "-l", old_mp])
        if _is_mounted(old_mp):
            return False, f"no se pudo desmontar la carpeta actual: {err.strip()}", {}
    _remove_fstab(old_mp)
    if old_mp != new_mp:
        try:
            os.rmdir(old_mp)          # solo si está vacío: nunca recursivo
        except OSError:
            pass

    # 2. Montar la nueva; si falla, restaurar la vieja
    ok, err = _mount_into(new_target, new_mp)
    if not ok:
        if old_target and os.path.isdir(old_target):
            _mount_into(old_target, old_mp)
        return False, f"mount --bind falló: {err}", {}

    # 3. Permisos: fuera de la vieja (antes de dar los nuevos, por si se solapan)
    if old_target != new_target:
        _revoke_subuser(username, old_target)
    _grant_subuser(owner, username, jail, new_target)
    return True, "changed", info


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

    # 2. Quitar ACL del subusuario sobre el target. La del owner (la web) se
    #    deja: es el propio dueño de la web y lo que subió la subcuenta sigue
    #    teniendo que ser escribible por ella.
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
