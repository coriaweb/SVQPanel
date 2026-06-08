"""
SVQPanel — Jaula chroot (jailkit) para la terminal web de los CLIENTES.

Sin esto, `su - usuario` deja al cliente recorrer todo el árbol del servidor
(ver /etc, /home con los nombres de los demás clientes, versiones de software…).
Aunque no pueda LEER ficheros de otros (permisos), es fuga de información.

Solución (la misma que HestiaCP): una **jaula chroot compartida** creada con
jailkit en `/var/lib/svqpanel/jail` (propiedad root, requisito del chroot) con
solo los binarios permitidos (bash, ls, cat, nano, php, git, composer, wp…).
Para cada sesión de cliente:
  1. se bind-montea su `/home/<user>` dentro de la jaula en `/home/<user>`,
  2. se añade su línea a `<jail>/etc/passwd` (con shell /bin/bash),
  3. `jk_chrootlaunch -j <jail> -u <user> -x /bin/bash` abre la shell DENTRO de
     la jaula: el cliente ve su home como su único home y `/` es la jaula mínima.

El admin (root) NO se enjaula: tiene shell completa del servidor.
"""
import os
import re
import subprocess
import logging

logger = logging.getLogger(__name__)

JAIL_ROOT = "/var/lib/svqpanel/jail"

# Secciones de jk_init.ini a incluir en la jaula (binarios + libs).
JAIL_SECTIONS = ["basicshell", "editors", "netutils", "git", "terminfo"]

# Binarios extra que los clientes de hosting suelen necesitar (si existen).
EXTRA_BINARIES = [
    "/usr/bin/php", "/usr/bin/git", "/usr/local/bin/composer",
    "/usr/local/bin/wp", "/usr/bin/rsync", "/usr/bin/curl", "/usr/bin/unzip",
    "/usr/bin/zip", "/usr/bin/tar", "/usr/bin/less", "/usr/bin/vi",
    # Básicos de uso diario que jk_init no siempre incluye
    "/usr/bin/whoami", "/usr/bin/id", "/usr/bin/clear", "/usr/bin/find",
    "/usr/bin/head", "/usr/bin/tail", "/usr/bin/wc", "/usr/bin/du",
    "/usr/bin/df", "/usr/bin/top", "/usr/bin/which", "/usr/bin/env",
    "/usr/bin/sort", "/usr/bin/cut", "/usr/bin/awk", "/usr/bin/diff",
    "/usr/bin/md5sum", "/usr/bin/file", "/usr/bin/stat", "/usr/bin/ps",
]


def jailkit_installed() -> bool:
    return _which("jk_init") and _which("jk_chrootlaunch")


def _which(cmd: str) -> bool:
    from shutil import which
    return which(cmd) is not None


def jail_ready() -> bool:
    """True si la jaula compartida ya está creada (tiene un bash dentro)."""
    return os.path.exists(os.path.join(JAIL_ROOT, "bin", "bash"))


def ensure_jailkit_installed() -> None:
    if not jailkit_installed():
        subprocess.run(["apt-get", "install", "-y", "-qq", "jailkit"],
                       check=True, timeout=300)


def build_jail() -> dict:
    """Crea (idempotente) la jaula compartida con jk_init + binarios extra."""
    ensure_jailkit_installed()
    os.makedirs(JAIL_ROOT, exist_ok=True)

    # jk_init: estructura + binarios de las secciones
    subprocess.run(["jk_init", "-f", JAIL_ROOT, *JAIL_SECTIONS],
                   check=True, timeout=180)

    # Binarios extra que existan en el host
    present = [b for b in EXTRA_BINARIES if os.path.exists(b)]
    if present:
        subprocess.run(["jk_cp", "-j", JAIL_ROOT, *present],
                       check=False, timeout=180)

    # La jaula debe ser root:root (requisito del chroot)
    os.chown(JAIL_ROOT, 0, 0)
    os.chmod(JAIL_ROOT, 0o755)

    # Directorios de runtime dentro de la jaula
    for d in ("etc", "home", "tmp", "dev/pts", "proc"):
        p = os.path.join(JAIL_ROOT, d)
        os.makedirs(p, exist_ok=True)
    os.chmod(os.path.join(JAIL_ROOT, "tmp"), 0o1777)

    # /dev/ptmx → pts/ptmx (necesario para el pseudo-terminal interactivo).
    ptmx = os.path.join(JAIL_ROOT, "dev", "ptmx")
    if not os.path.islink(ptmx) and not os.path.exists(ptmx):
        os.symlink("pts/ptmx", ptmx)

    # /etc mínimo: resolv.conf y hosts para que funcione la red dentro de la jaula
    _copy_into_jail("/etc/resolv.conf")
    _copy_into_jail("/etc/hosts")

    # Montar /dev/pts y /proc (la shell interactiva de ttyd los necesita).
    ensure_dev_mounts()

    return {"ready": jail_ready(), "path": JAIL_ROOT}


def ensure_dev_mounts() -> None:
    """Monta /dev/pts y /proc dentro de la jaula si no lo están. Sin esto, la
    shell interactiva de ttyd no obtiene su pseudo-terminal y la sesión se cierra
    nada más abrir ('Press Enter to Reconnect'). Idempotente; tolerante a fallos.
    """
    pts = os.path.join(JAIL_ROOT, "dev", "pts")
    proc = os.path.join(JAIL_ROOT, "proc")
    os.makedirs(pts, exist_ok=True)
    os.makedirs(proc, exist_ok=True)
    try:
        if not _is_mounted(pts):
            subprocess.run(["mount", "-t", "devpts", "devpts", pts,
                            "-o", "rw,nosuid,noexec,gid=5,mode=620,ptmxmode=666"],
                           check=False, timeout=15)
        if not _is_mounted(proc):
            subprocess.run(["mount", "-t", "proc", "proc", proc],
                           check=False, timeout=15)
    except Exception as e:
        logger.warning("No se pudieron montar pts/proc en la jaula: %s", e)


def _copy_into_jail(src: str) -> None:
    if not os.path.exists(src):
        return
    dst = os.path.join(JAIL_ROOT, src.lstrip("/"))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        import shutil
        shutil.copyfile(src, dst)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Preparar la sesión de un usuario (bind-mount + passwd) — idempotente
# ─────────────────────────────────────────────────────────────────────────────
def _jail_home(username: str) -> str:
    return os.path.join(JAIL_ROOT, "home", username)


def _is_mounted(path: str) -> bool:
    r = subprocess.run(["mountpoint", "-q", path])
    return r.returncode == 0


def prepare_user(username: str) -> None:
    """Deja la jaula lista para `username`: bind-mount de su home + entrada en
    el passwd de la jaula. Idempotente. Llamar antes de jk_chrootlaunch."""
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", username or ""):
        raise ValueError("Nombre de usuario inválido")

    real_home = f"/home/{username}"
    if not os.path.isdir(real_home):
        raise ValueError("El usuario no tiene home")

    jhome = _jail_home(username)
    os.makedirs(jhome, exist_ok=True)
    if not _is_mounted(jhome):
        subprocess.run(["mount", "--bind", real_home, jhome],
                       check=True, timeout=15)

    # /dev/pts y /proc se pierden al reiniciar el servidor; remontarlos aquí
    # garantiza la sesión interactiva en cada apertura de terminal.
    ensure_dev_mounts()

    _sync_jail_passwd(username)


def _sync_jail_passwd(username: str) -> None:
    """Asegura que el passwd/group de la jaula tienen al usuario con shell bash."""
    jail_passwd = os.path.join(JAIL_ROOT, "etc", "passwd")
    jail_group = os.path.join(JAIL_ROOT, "etc", "group")

    # Línea del usuario en el passwd real, forzando shell /bin/bash
    line = None
    with open("/etc/passwd") as f:
        for ln in f:
            if ln.startswith(username + ":"):
                parts = ln.rstrip("\n").split(":")
                parts[6] = "/bin/bash"
                line = ":".join(parts) + "\n"
                break
    if not line:
        raise ValueError("Usuario no encontrado en /etc/passwd")

    _ensure_line(jail_passwd, username + ":", line, header="root:x:0:0:root:/root:/bin/bash\n")

    # Grupo del usuario
    gid = line.split(":")[3]
    grp_line = None
    with open("/etc/group") as f:
        for ln in f:
            flds = ln.split(":")
            if len(flds) > 2 and flds[2] == gid:
                grp_line = ln if ln.endswith("\n") else ln + "\n"
                break
    if grp_line:
        gname = grp_line.split(":")[0]
        _ensure_line(jail_group, gname + ":", grp_line, header="root:x:0:\n")


def _ensure_line(path: str, key_prefix: str, line: str, header: str) -> None:
    """Garantiza que `line` (identificada por key_prefix) está en `path`."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existing = ""
    if os.path.exists(path):
        with open(path) as f:
            existing = f.read()
    out_lines = [l for l in existing.splitlines(keepends=True)
                 if not l.startswith(key_prefix)]
    if not any(l.startswith("root:") for l in out_lines):
        out_lines.insert(0, header)
    out_lines.append(line)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.writelines(out_lines)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def chroot_command(username: str) -> str:
    """Devuelve el comando (string para `exec` en bash) que abre la shell
    enjaulada del usuario.

    Usamos `chroot --userspec` en vez de `jk_chrootlaunch`: este último no
    conecta bien el pseudo-terminal de ttyd (la sesión se cerraba al instante,
    "Press Enter to Reconnect"). chroot directo SÍ mantiene la shell interactiva.
    Arranca bash de login (-l) y nos posicionamos en el home del usuario.
    """
    grp = _user_group(username)
    # cd al home dentro de la jaula y abrir bash de login interactivo.
    inner = f"cd /home/{username} 2>/dev/null; exec /bin/bash -l"
    return (f"chroot --userspec={username}:{grp} {JAIL_ROOT} "
            f"/bin/bash -lc {shlex_quote(inner)}")


def _user_group(username: str) -> str:
    """Grupo primario del usuario (nombre o gid)."""
    with open("/etc/passwd") as f:
        for ln in f:
            if ln.startswith(username + ":"):
                return ln.split(":")[3]
    return username


def shlex_quote(s: str) -> str:
    import shlex
    return shlex.quote(s)


if __name__ == "__main__":
    # Uso por el launcher del terminal: `python -m scripts.terminal_jail <user>`.
    # Prepara la jaula del usuario e imprime el comando chroot a stdout (una
    # línea, que el launcher ejecuta con `eval`/`exec`). Si algo falla, no imprime
    # nada (el launcher cierra la sesión por seguridad).
    import sys
    try:
        if len(sys.argv) < 2:
            sys.exit(1)
        user = sys.argv[1]
        if not jail_ready():
            build_jail()
        prepare_user(user)
        print(chroot_command(user))
    except Exception as e:
        logger.error("terminal_jail: %s", e)
        sys.exit(1)
