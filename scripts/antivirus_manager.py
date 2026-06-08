"""
SVQPanel — Gestión del antivirus de correo (ClamAV).

El antivirus de adjuntos se puede aplicar por dos métodos según lo que soporte
el servidor:

  • **rspamd**  — ClamAV vía el módulo antivirus de Rspamd. Permite control
                  POR DOMINIO (rechazo selectivo con mapa+Lua). Requiere que la
                  CPU tenga SSSE3 (Rspamd 4.x lo necesita para parsear multipart;
                  sin él no ve los adjuntos). Es el método preferido.
  • **milter**  — ClamAV vía `clamav-milter` conectado a Postfix directamente.
                  NO depende de Rspamd ni de SSSE3, así que funciona en CPUs sin
                  esas instrucciones (p. ej. VMs KVM con CPU genérica). Es GLOBAL
                  (on/off a nivel servidor, sin granularidad por dominio).
  • **none**    — ClamAV no instalado / no disponible.

`detect_method()` decide el método disponible. La capa de API expone el estado
para que la UI muestre el control por dominio (rspamd) o un único interruptor
global (milter).

Gestión de firmas: clamav-freshclam (servicio) las actualiza solas 24×/día;
`signatures_status()` lee fecha/versión y `update_signatures()` fuerza un
`freshclam` puntual (lo usa el botón "Actualizar ahora" del panel).
"""
import os
import re
import shutil
import subprocess
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

CLAMD_SOCKET        = "/var/run/clamav/clamd.ctl"
CLAMAV_DB_DIR       = "/var/lib/clamav"
MILTER_CONF         = "/etc/clamav/clamav-milter.conf"
MILTER_TCP          = "inet:7357@127.0.0.1"
MILTER_POSTFIX_ADDR = "inet:localhost:7357"
RSPAMD_MILTER_ADDR  = "inet:localhost:11332"


# ─────────────────────────────────────────────────────────────────────────────
# CPU / método disponible
# ─────────────────────────────────────────────────────────────────────────────
def cpu_has_ssse3() -> bool:
    """True si la CPU expone SSSE3 (necesario para el antivirus vía Rspamd 4.x)."""
    try:
        with open("/proc/cpuinfo") as f:
            return "ssse3" in f.read()
    except Exception:
        return False


def clamav_available() -> bool:
    """True si clamd está disponible (socket presente o servicio activo)."""
    if os.path.exists(CLAMD_SOCKET):
        return True
    try:
        r = subprocess.run(["systemctl", "is-active", "clamav-daemon"],
                           capture_output=True, text=True, timeout=4)
        return r.stdout.strip() == "active"
    except Exception:
        return False


def rspamd_available() -> bool:
    return os.path.exists("/etc/rspamd")


def detect_method() -> str:
    """Devuelve el método de antivirus que debe usar este servidor:
    'rspamd' (por dominio), 'milter' (global) o 'none'.
    """
    if not clamav_available():
        return "none"
    # Con SSSE3 + Rspamd → método por dominio (preferido).
    if cpu_has_ssse3() and rspamd_available():
        return "rspamd"
    # Sin SSSE3 (o sin Rspamd) pero con ClamAV → milter global.
    return "milter"


# ─────────────────────────────────────────────────────────────────────────────
# clamav-milter (modo global, sin dependencia de SSSE3)
# ─────────────────────────────────────────────────────────────────────────────
def _milter_installed() -> bool:
    return shutil.which("clamav-milter") is not None or os.path.exists(MILTER_CONF)


def write_milter_config() -> None:
    """Escribe la config del clamav-milter (TCP, conectado a clamd, OnInfected
    Reject). TCP en vez de socket unix porque Postfix corre chrooted y no ve
    /var/run/clamav."""
    content = f"""# SVQPanel — clamav-milter. Generado automáticamente. NO editar a mano.
PidFile /var/run/clamav/clamav-milter.pid
MilterSocket {MILTER_TCP}
FixStaleSocket true
User clamav
ClamdSocket unix:{CLAMD_SOCKET}
OnInfected Reject
OnClean Accept
OnFail Defer
AddHeader Replace
LogSyslog true
LogInfected Full
MaxFileSize 50M
RejectMsg Mensaje rechazado: virus detectado (%v)
"""
    tmp = MILTER_CONF + ".tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.replace(tmp, MILTER_CONF)


def _postfix_get(key: str) -> str:
    try:
        r = subprocess.run(["postconf", "-h", key], capture_output=True,
                           text=True, timeout=8)
        return r.stdout.strip()
    except Exception:
        return ""


def _postfix_set(key: str, value: str) -> None:
    subprocess.run(["postconf", "-e", f"{key}={value}"], check=True, timeout=8)


def _postfix_milters_with(addr: str, present: bool) -> None:
    """Añade o quita `addr` de smtpd_milters y non_smtpd_milters de Postfix,
    preservando el resto (p. ej. el de Rspamd)."""
    for key in ("smtpd_milters", "non_smtpd_milters"):
        cur = _postfix_get(key)
        parts = [p for p in cur.split() if p and p != addr]
        if present:
            parts.append(addr)
        # Si no queda ninguno y antes había Rspamd, dejamos al menos Rspamd.
        _postfix_set(key, " ".join(parts))


def milter_active() -> bool:
    try:
        r = subprocess.run(["systemctl", "is-active", "clamav-milter"],
                           capture_output=True, text=True, timeout=4)
        return r.stdout.strip() == "active"
    except Exception:
        return False


def enable_milter() -> None:
    """Activa el antivirus global vía clamav-milter: config + servicio + lo
    engancha a Postfix."""
    if not _milter_installed():
        subprocess.run(["apt-get", "install", "-y", "-q", "clamav-milter"],
                       check=True, timeout=300)
    write_milter_config()
    subprocess.run(["systemctl", "enable", "clamav-milter"], timeout=15)
    subprocess.run(["systemctl", "restart", "clamav-milter"], check=True, timeout=20)
    _postfix_milters_with(MILTER_POSTFIX_ADDR, present=True)
    subprocess.run(["systemctl", "reload", "postfix"], timeout=15)


def disable_milter() -> None:
    """Desactiva el antivirus global: lo desengancha de Postfix y para el
    servicio."""
    _postfix_milters_with(MILTER_POSTFIX_ADDR, present=False)
    subprocess.run(["systemctl", "reload", "postfix"], timeout=15)
    subprocess.run(["systemctl", "disable", "--now", "clamav-milter"], timeout=15)
    subprocess.run(["systemctl", "stop", "clamav-milter"], timeout=15)


def milter_enabled() -> bool:
    """True si el milter está activo Y enganchado a Postfix."""
    return milter_active() and MILTER_POSTFIX_ADDR in _postfix_get("smtpd_milters")


# ─────────────────────────────────────────────────────────────────────────────
# Firmas de virus (freshclam)
# ─────────────────────────────────────────────────────────────────────────────
def _db_version(path: str):
    """Lee versión, fecha y nº de firmas del HEADER de una base .cvd/.cld.

    El header es una cabecera de texto de 512 bytes con campos separados por ':':
      ClamAV-VDB:<fecha>:<version>:<nsigs>:<flevel>:<md5>:<dsig>:<builder>:<stime>
    Leerlo es instantáneo; evitamos `sigtool --info`, que descomprime y verifica
    el fichero entero (main.cvd ~89 MB → varios segundos).
    """
    if not os.path.exists(path):
        return None
    info = {"version": None, "sigs": None, "built": None}
    try:
        with open(path, "rb") as f:
            header = f.read(512).decode("latin-1", "ignore")
        if header.startswith("ClamAV-VDB:"):
            parts = header.split(":")
            # parts[0]='ClamAV-VDB', [1]=fecha, [2]=version, [3]=nsigs
            if len(parts) > 1:
                info["built"] = parts[1].strip()
            if len(parts) > 2:
                info["version"] = parts[2].strip()
            if len(parts) > 3:
                info["sigs"] = parts[3].strip()
    except Exception:
        pass
    return info


def signatures_status() -> dict:
    """Estado de las firmas: versiones, nº de firmas, fecha del fichero más
    reciente y si el servicio de auto-actualización está activo."""
    dbs = {}
    newest_mtime = 0.0
    for name in ("main", "daily", "bytecode"):
        path = None
        for ext in (".cvd", ".cld"):
            cand = os.path.join(CLAMAV_DB_DIR, name + ext)
            if os.path.exists(cand):
                path = cand
                break
        if path:
            dbs[name] = _db_version(path)
            newest_mtime = max(newest_mtime, os.path.getmtime(path))

    total_sigs = 0
    for d in dbs.values():
        try:
            total_sigs += int((d or {}).get("sigs") or 0)
        except Exception:
            pass

    auto = False
    try:
        r = subprocess.run(["systemctl", "is-active", "clamav-freshclam"],
                           capture_output=True, text=True, timeout=4)
        auto = r.stdout.strip() == "active"
    except Exception:
        pass

    updated_at = None
    if newest_mtime:
        updated_at = datetime.fromtimestamp(newest_mtime, tz=timezone.utc).isoformat()

    return {
        "databases": dbs,
        "total_signatures": total_sigs,
        "updated_at": updated_at,
        "auto_update": auto,
    }


def update_signatures() -> dict:
    """Fuerza una actualización de firmas (freshclam puntual). El servicio
    clamav-freshclam debe pausarse mientras corre un freshclam manual para no
    chocar; lo ejecutamos con --no-warnings y toleramos el caso 'up-to-date'."""
    # freshclam no puede correr a la vez que el daemon; lo paramos un momento.
    daemon_was_active = False
    try:
        r = subprocess.run(["systemctl", "is-active", "clamav-freshclam"],
                           capture_output=True, text=True, timeout=4)
        daemon_was_active = r.stdout.strip() == "active"
        if daemon_was_active:
            subprocess.run(["systemctl", "stop", "clamav-freshclam"], timeout=15)

        proc = subprocess.run(["freshclam", "--quiet", "--no-warnings"],
                             capture_output=True, text=True, timeout=300)
        ok = proc.returncode == 0
        msg = (proc.stdout + proc.stderr).strip()[-500:]
    except subprocess.TimeoutExpired:
        ok, msg = False, "Timeout actualizando firmas (freshclam > 5 min)."
    except Exception as e:
        ok, msg = False, str(e)
    finally:
        if daemon_was_active:
            subprocess.run(["systemctl", "start", "clamav-freshclam"], timeout=15)

    return {"ok": ok, "message": msg or "Firmas actualizadas.",
            "status": signatures_status()}
