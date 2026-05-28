"""
Gestión SFTP por usuario:

  - Habilitar/deshabilitar SFTP (chroot via sshd Match Group sftponly)
  - Cambiar password Linux del usuario (chpasswd)
  - Gestionar claves SSH públicas en ~/.ssh/authorized_keys

Diseño de chroot:
  /home/{user}                  → owned root:root 755 (requisito del chroot)
    web/                        → user:www-data 750 (donde están los dominios)
    .ssh/authorized_keys        → user:user 600 (sshd lee como root)
    files/                      → user:user 750 (espacio writeable adicional)

Cuando se desactiva SFTP, revertimos el chown a {user}:{user} para no
romper el modelo original de SVQPanel.
"""

import base64
import hashlib
import logging
import os
import re
import subprocess
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SFTP_GROUP = "sftponly"
SSHD_SNIPPET_PATH = "/etc/ssh/sshd_config.d/svqpanel-sftponly.conf"
SSHD_SNIPPET_CONTENT = """# SVQPanel — Match Group para usuarios SFTP-only (chroot al home)
# Generado por install.sh; no editar a mano (se sobrescribe).
Match Group sftponly
    ChrootDirectory %h
    ForceCommand internal-sftp
    AllowTcpForwarding no
    X11Forwarding no
    PermitTunnel no
    AllowAgentForwarding no
    PasswordAuthentication yes
    PubkeyAuthentication yes
"""

VALID_KEY_TYPES = {
    "ssh-rsa", "ssh-dss", "ssh-ed25519",
    "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521",
}

# El servicio systemd del panel arranca con PATH=venv/bin; forzamos un PATH
# completo para que se resuelvan groupadd, usermod, chpasswd, chown, etc.
_SYS_ENV = {
    **os.environ,
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
}


# ─────────────────────────────────────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────────────────────────────────────
def _run(cmd: List[str], input_text: Optional[str] = None, timeout: int = 10) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            input=input_text, timeout=timeout, env=_SYS_ENV,
        )
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError as e:
        return 127, "", str(e)
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


def _sh(cmd: List[str]) -> None:
    """subprocess.run con PATH completo, errores ignorados (chown/chmod)."""
    try:
        subprocess.run(cmd, check=False, env=_SYS_ENV,
                       capture_output=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def user_exists(username: str) -> bool:
    rc, _, _ = _run(["id", username], timeout=4)
    return rc == 0


def home_dir(username: str) -> str:
    return f"/home/{username}"


# ─────────────────────────────────────────────────────────────────────────────
# Setup global (grupo + sshd snippet)
# ─────────────────────────────────────────────────────────────────────────────
def ensure_sftp_group() -> Tuple[bool, str]:
    """Crea el grupo sftponly si no existe."""
    rc, _, _ = _run(["getent", "group", SFTP_GROUP], timeout=4)
    if rc == 0:
        return True, "exists"
    rc, _, err = _run(["groupadd", SFTP_GROUP], timeout=6)
    if rc != 0:
        return False, err.strip() or "groupadd falló"
    return True, "created"


def ensure_sshd_snippet() -> Tuple[bool, str]:
    """Escribe /etc/ssh/sshd_config.d/svqpanel-sftponly.conf y recarga sshd."""
    needs_write = True
    if os.path.isfile(SSHD_SNIPPET_PATH):
        with open(SSHD_SNIPPET_PATH) as f:
            if f.read() == SSHD_SNIPPET_CONTENT:
                needs_write = False
    if needs_write:
        with open(SSHD_SNIPPET_PATH, "w") as f:
            f.write(SSHD_SNIPPET_CONTENT)
        # validar config antes de reload
        rc, _, err = _run(["sshd", "-t"], timeout=6)
        if rc != 0:
            return False, f"sshd -t falló: {err.strip()}"
        rc, _, err = _run(["systemctl", "reload", "ssh"], timeout=6)
        if rc != 0:
            # algunos distros llaman al servicio 'sshd' en lugar de 'ssh'
            rc, _, err = _run(["systemctl", "reload", "sshd"], timeout=6)
            if rc != 0:
                return False, f"reload sshd falló: {err.strip()}"
        return True, "updated"
    return True, "unchanged"


# ─────────────────────────────────────────────────────────────────────────────
# Enable / disable SFTP por usuario
# ─────────────────────────────────────────────────────────────────────────────
def _prepare_chroot_home(username: str) -> None:
    """
    chown root:root 755 al home del usuario (requisito chroot sshd).
    Asegura que .ssh/, web/, files/ existen con ownership correcto del user.
    """
    h = home_dir(username)
    if not os.path.isdir(h):
        return
    # /home/{user} a root:root 755
    _sh(["chown", "root:root", h])
    _sh(["chmod", "755", h])

    # .ssh propiedad del user 700
    ssh_dir = os.path.join(h, ".ssh")
    os.makedirs(ssh_dir, exist_ok=True)
    _sh(["chown", f"{username}:{username}", ssh_dir])
    _sh(["chmod", "700", ssh_dir])

    auth_file = os.path.join(ssh_dir, "authorized_keys")
    if not os.path.isfile(auth_file):
        open(auth_file, "a").close()
    _sh(["chown", f"{username}:{username}", auth_file])
    _sh(["chmod", "600", auth_file])

    # files/ writeable area del cliente
    files_dir = os.path.join(h, "files")
    os.makedirs(files_dir, exist_ok=True)
    _sh(["chown", f"{username}:{username}", files_dir])
    _sh(["chmod", "750", files_dir])


def _revert_chroot_home(username: str) -> None:
    """Restaura /home/{user} a {user}:{user} 750 (estado antes de SFTP-only)."""
    h = home_dir(username)
    if not os.path.isdir(h):
        return
    _sh(["chown", f"{username}:{username}", h])
    _sh(["chmod", "750", h])


def enable_sftp(username: str) -> Tuple[bool, str]:
    """Activa SFTP para un usuario: lo mete en el grupo sftponly y prepara chroot."""
    if not user_exists(username):
        return False, f"usuario del sistema '{username}' no existe"
    ok, msg = ensure_sftp_group()
    if not ok:
        return False, msg
    # Añadir al grupo
    rc, _, err = _run(["usermod", "-aG", SFTP_GROUP, username], timeout=6)
    if rc != 0:
        return False, err.strip() or "usermod falló"
    try:
        _prepare_chroot_home(username)
    except Exception as e:
        return False, f"prepare_chroot: {e}"
    return True, "enabled"


def disable_sftp(username: str) -> Tuple[bool, str]:
    """Quita el usuario del grupo sftponly y revierte el chown."""
    rc, _, err = _run(["gpasswd", "-d", username, SFTP_GROUP], timeout=6)
    # 'gpasswd -d' devuelve != 0 si el user no estaba en el grupo; ignorable

    # No revertir el home si hay subcuentas: sus jaulas exigen /home/{user}
    # propiedad de root para que el chroot de OpenSSH funcione.
    jails = os.path.join(home_dir(username), ".sftp-jails")
    has_subaccounts = os.path.isdir(jails) and bool(os.listdir(jails))
    if not has_subaccounts:
        _revert_chroot_home(username)
    return True, "disabled"


# ─────────────────────────────────────────────────────────────────────────────
# Password
# ─────────────────────────────────────────────────────────────────────────────
def set_password(username: str, new_password: str) -> Tuple[bool, str]:
    """Cambia el password Linux del usuario via chpasswd."""
    if not user_exists(username):
        return False, "usuario no existe"
    if not new_password or len(new_password) < 8:
        return False, "password mínimo 8 caracteres"
    rc, _, err = _run(["chpasswd"], input_text=f"{username}:{new_password}\n", timeout=6)
    if rc != 0:
        return False, err.strip() or "chpasswd falló"
    return True, "ok"


# ─────────────────────────────────────────────────────────────────────────────
# SSH keys
# ─────────────────────────────────────────────────────────────────────────────
def _authorized_keys_path(username: str) -> str:
    return os.path.join(home_dir(username), ".ssh", "authorized_keys")


def _parse_key_line(line: str) -> Optional[Dict[str, str]]:
    """Parsea una línea authorized_keys → {type, key_b64, comment, fingerprint}."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    parts = line.split(None, 2)
    if len(parts) < 2:
        return None
    key_type, key_b64 = parts[0], parts[1]
    if key_type not in VALID_KEY_TYPES:
        return None
    comment = parts[2] if len(parts) == 3 else ""
    try:
        raw = base64.b64decode(key_b64, validate=True)
        digest = hashlib.sha256(raw).digest()
        fp = "SHA256:" + base64.b64encode(digest).decode().rstrip("=")
    except Exception:
        return None
    return {
        "type":        key_type,
        "key_b64":     key_b64,
        "comment":     comment,
        "fingerprint": fp,
    }


def list_ssh_keys(username: str) -> List[Dict[str, str]]:
    """Lista las claves SSH del usuario (sin exponer la clave entera)."""
    path = _authorized_keys_path(username)
    if not os.path.isfile(path):
        return []
    out = []
    try:
        with open(path) as f:
            for line in f:
                parsed = _parse_key_line(line)
                if parsed:
                    out.append({
                        "type":        parsed["type"],
                        "comment":     parsed["comment"],
                        "fingerprint": parsed["fingerprint"],
                    })
    except OSError:
        pass
    return out


def add_ssh_key(username: str, public_key: str) -> Tuple[bool, str, Optional[str]]:
    """Añade una clave pública. Devuelve (ok, msg, fingerprint)."""
    if not user_exists(username):
        return False, "usuario no existe", None
    parsed = _parse_key_line(public_key)
    if not parsed:
        return False, "clave pública no válida (formato OpenSSH esperado)", None

    # Asegurar que existen el dir y el fichero
    ssh_dir = os.path.join(home_dir(username), ".ssh")
    os.makedirs(ssh_dir, exist_ok=True)
    _sh(["chown", f"{username}:{username}", ssh_dir])
    _sh(["chmod", "700", ssh_dir])

    path = _authorized_keys_path(username)
    # Evitar duplicados por fingerprint
    for existing in list_ssh_keys(username):
        if existing["fingerprint"] == parsed["fingerprint"]:
            return False, "esa clave ya está añadida", parsed["fingerprint"]

    line = f'{parsed["type"]} {parsed["key_b64"]}'
    if parsed["comment"]:
        line += f' {parsed["comment"]}'
    line += "\n"
    with open(path, "a") as f:
        f.write(line)
    _sh(["chown", f"{username}:{username}", path])
    _sh(["chmod", "600", path])
    return True, "added", parsed["fingerprint"]


def remove_ssh_key(username: str, fingerprint: str) -> Tuple[bool, str]:
    """Borra una clave por su fingerprint SHA256."""
    path = _authorized_keys_path(username)
    if not os.path.isfile(path):
        return False, "no hay claves"
    kept = []
    removed = False
    with open(path) as f:
        for line in f:
            parsed = _parse_key_line(line)
            if parsed and parsed["fingerprint"] == fingerprint:
                removed = True
                continue
            kept.append(line)
    if not removed:
        return False, "fingerprint no encontrado"
    with open(path, "w") as f:
        f.writelines(kept)
    _sh(["chown", f"{username}:{username}", path])
    _sh(["chmod", "600", path])
    return True, "removed"
