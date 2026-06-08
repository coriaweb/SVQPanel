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

    # La plantilla debe ser root:root (requisito del chroot)
    os.chown(JAIL_ROOT, 0, 0)
    os.chmod(JAIL_ROOT, 0o755)

    # La plantilla solo aporta binarios; los homes, /dev, /proc y /etc van por
    # usuario en su propia jaula (ver prepare_user). Aun así dejamos un /etc con
    # la red por si algún binario la necesita al copiarse.
    _copy_into_jail("/etc/resolv.conf")
    _copy_into_jail("/etc/hosts")

    return {"ready": jail_ready(), "path": JAIL_ROOT}


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
# Jaula POR USUARIO (cada cliente ve SOLO su home, nunca a los demás)
# ─────────────────────────────────────────────────────────────────────────────
# La plantilla compartida (JAIL_ROOT) tiene solo los binarios (read-only). Cada
# usuario tiene su propia jaula en USER_JAILS/<user> que monta la plantilla
# (bin/lib/usr… en ro) + únicamente SU home. Así es imposible que un cliente vea
# el nombre de otro en /home.
USER_JAILS = "/var/lib/svqpanel/jails"

# Subdirectorios de la plantilla que se exponen (solo lectura) en cada jaula.
_TEMPLATE_DIRS = ["bin", "lib", "lib64", "usr", "sbin"]


def _user_jail(username: str) -> str:
    return os.path.join(USER_JAILS, username)


def _is_mounted(path: str) -> bool:
    r = subprocess.run(["mountpoint", "-q", path])
    return r.returncode == 0


def prepare_user(username: str) -> str:
    """Prepara (idempotente) la jaula PROPIA de `username` y devuelve su ruta.

    Estructura de la jaula del usuario:
      <jail>/bin,lib,lib64,usr,sbin → bind ro de la plantilla (binarios)
      <jail>/home/<user>            → bind de SU /home/<user> (solo el suyo)
      <jail>/dev/pts, /proc         → montados (terminal interactivo)
      <jail>/etc/passwd,group       → solo root + este usuario
    """
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", username or ""):
        raise ValueError("Nombre de usuario inválido")
    real_home = f"/home/{username}"
    if not os.path.isdir(real_home):
        raise ValueError("El usuario no tiene home")
    if not jail_ready():
        build_jail()

    jail = _user_jail(username)
    os.makedirs(jail, exist_ok=True)

    # 1) Binarios de la plantilla (read-only) por bind-mount
    for d in _TEMPLATE_DIRS:
        src = os.path.join(JAIL_ROOT, d)
        if not os.path.exists(src):
            continue
        dst = os.path.join(jail, d)
        os.makedirs(dst, exist_ok=True)
        if not _is_mounted(dst):
            subprocess.run(["mount", "--bind", "-o", "ro", src, dst],
                           check=True, timeout=15)

    # 2) Solo SU home
    jhome = os.path.join(jail, "home", username)
    os.makedirs(jhome, exist_ok=True)
    if not _is_mounted(jhome):
        subprocess.run(["mount", "--bind", real_home, jhome], check=True, timeout=15)

    # 3) /dev (null, tty, urandom, pts) y /proc
    _ensure_user_dev(jail)

    # 4) /etc mínimo con SOLO root + este usuario
    _write_user_etc(jail, username)

    # 5) /tmp propio
    jtmp = os.path.join(jail, "tmp")
    os.makedirs(jtmp, exist_ok=True)
    os.chmod(jtmp, 0o1777)

    return jail


def _ensure_user_dev(jail: str) -> None:
    """Crea /dev (con nodos básicos) + /dev/pts + /proc en la jaula del usuario."""
    dev = os.path.join(jail, "dev")
    os.makedirs(os.path.join(dev, "pts"), exist_ok=True)
    os.makedirs(os.path.join(jail, "proc"), exist_ok=True)
    # Nodos básicos por bind-mount desde el /dev real (no requiere mknod)
    for node in ("null", "zero", "tty", "urandom", "random"):
        src = f"/dev/{node}"
        dst = os.path.join(dev, node)
        if os.path.exists(src):
            if not os.path.exists(dst):
                open(dst, "w").close()
            if not _is_mounted(dst):
                subprocess.run(["mount", "--bind", src, dst], check=False, timeout=10)
    # ptmx → pts/ptmx
    ptmx = os.path.join(dev, "ptmx")
    if not os.path.islink(ptmx) and not os.path.exists(ptmx):
        os.symlink("pts/ptmx", ptmx)
    # pts y proc
    pts = os.path.join(dev, "pts")
    if not _is_mounted(pts):
        subprocess.run(["mount", "-t", "devpts", "devpts", pts,
                        "-o", "rw,nosuid,noexec,gid=5,mode=620,ptmxmode=666"],
                       check=False, timeout=10)
    proc = os.path.join(jail, "proc")
    if not _is_mounted(proc):
        subprocess.run(["mount", "-t", "proc", "proc", proc], check=False, timeout=10)


def _write_user_etc(jail: str, username: str) -> None:
    """Escribe <jail>/etc con passwd/group de SOLO root + este usuario, y red."""
    etc = os.path.join(jail, "etc")
    os.makedirs(etc, exist_ok=True)

    # passwd del usuario (shell forzada a bash)
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
    with open(os.path.join(etc, "passwd"), "w") as f:
        f.write("root:x:0:0:root:/root:/bin/bash\n")
        f.write(line)

    # group del usuario
    gid = line.split(":")[3]
    grp_line = ""
    with open("/etc/group") as f:
        for ln in f:
            flds = ln.split(":")
            if len(flds) > 2 and flds[2] == gid:
                grp_line = ln if ln.endswith("\n") else ln + "\n"
                break
    with open(os.path.join(etc, "group"), "w") as f:
        f.write("root:x:0:\n")
        if grp_line:
            f.write(grp_line)

    # Red dentro de la jaula
    for fname in ("resolv.conf", "hosts", "nsswitch.conf"):
        src = f"/etc/{fname}"
        if os.path.exists(src):
            try:
                import shutil
                shutil.copyfile(src, os.path.join(etc, fname))
            except Exception:
                pass


def chroot_command(username: str) -> str:
    """Comando (string para eval+exec) que abre la shell enjaulada del usuario
    en SU PROPIA jaula. chroot directo (no jk_chrootlaunch, que no conecta bien
    el pty de ttyd). Arranca bash de login en su home."""
    grp = _user_group(username)
    jail = _user_jail(username)
    inner = f"cd /home/{username} 2>/dev/null; exec /bin/bash -l"
    return (f"chroot --userspec={username}:{grp} {jail} "
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
