"""
redis_manager — Redis por dominio + protección del Redis de Rspamd.

Dos responsabilidades:

1. **Instancias Redis dedicadas por dominio** (caché de objetos para WordPress/
   WooCommerce/Laravel/Magento). Cada dominio activado tiene SU PROPIO proceso
   redis-server, aislado del resto:

     - Corre como el USUARIO del dominio (no redis, no www-data) — misma
       filosofía que el pool PHP-FPM dedicado.
     - Escucha SOLO en un socket unix dentro del dominio:
       /home/{user}/web/{dominio}/private/redis.sock (unixsocketperm 700 →
       solo el owner puede conectar; ni otros clientes ni www-data).
     - Sin puerto TCP (port 0): inalcanzable desde otros sitios/procesos.
     - maxmemory acotado (+ MemoryMax en systemd como segunda capa): un sitio
       no puede comerse la RAM del servidor. Política allkeys-lru (es caché).
     - Sin persistencia (save "" / appendonly no): es una caché volátil, no
       hay dump.rdb que pese ni que filtre datos.

   Config en /etc/svqpanel/redis/{dominio}.conf (root; el cliente NO puede
   editarla y subirse el maxmemory) + unidad systemd svqpanel-redis-{dominio}.

2. **secure_rspamd_redis()** — el Redis global (backend de Rspamd: Bayes,
   greylisting, ratelimit de correo) se instala sin contraseña y escucha en
   127.0.0.1. `disable_functions` no bloquea sockets TCP, así que cualquier
   PHP de un cliente podía conectarse y hacer FLUSHALL (borrar el Bayes
   entrenado o vaciar su contador de rate-limit de envío). Se protege con
   `requirepass` (la clave vive en /etc/svqpanel/redis_rspamd.pass, root 600)
   y se propaga a /etc/rspamd/local.d/redis.conf. Idempotente.
"""

import logging
import os
import re
import secrets
import subprocess

from scripts.utils import get_domain_root, validate_domain

logger = logging.getLogger(__name__)

CONF_DIR = "/etc/svqpanel/redis"
REDIS_BIN = "/usr/bin/redis-server"
REDIS_CLI = "/usr/bin/redis-cli"

# maxmemory por dominio (MB). El techo puede subirse vía env en .env.
DEFAULT_MAXMEMORY_MB = 64
MIN_MAXMEMORY_MB = 16
MAXMEMORY_CAP_MB = int(os.getenv("REDIS_DOMAIN_MAXMEMORY_CAP_MB", "256"))

# ── Redis global de Rspamd ───────────────────────────────────────────────────
RSPAMD_REDIS_PASS_FILE = "/etc/svqpanel/redis_rspamd.pass"
GLOBAL_REDIS_CONF = "/etc/redis/redis.conf"
RSPAMD_LOCAL_REDIS = "/etc/rspamd/local.d/redis.conf"
_BLOCK_BEGIN = "# BEGIN SVQPANEL (no editar: gestionado por el panel)"
_BLOCK_END = "# END SVQPANEL"


def _run(cmd, check=False, timeout=30):
    return subprocess.run(cmd, capture_output=True, text=True,
                          check=check, timeout=timeout)


def _atomic_write(path: str, content: str, mode: int = 0o644) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def redis_available() -> bool:
    """True si el binario redis-server está instalado en el servidor."""
    return os.path.exists(REDIS_BIN)


# ─────────────────────────────────────────────────────────────────────────────
# Instancias por dominio
# ─────────────────────────────────────────────────────────────────────────────

def _unit_name(domain: str) -> str:
    return f"svqpanel-redis-{domain}.service"


def _unit_path(domain: str) -> str:
    return f"/etc/systemd/system/{_unit_name(domain)}"


def _conf_path(domain: str) -> str:
    return f"{CONF_DIR}/{domain}.conf"


def socket_path(username: str, domain: str) -> str:
    return f"{get_domain_root(username, domain)}/private/redis.sock"


def clamp_maxmemory(mb) -> int:
    try:
        mb = int(mb)
    except (TypeError, ValueError):
        mb = DEFAULT_MAXMEMORY_MB
    return max(MIN_MAXMEMORY_MB, min(mb, MAXMEMORY_CAP_MB))


def render_instance_conf(username: str, domain: str, maxmemory_mb: int) -> str:
    """Config de la instancia (pura, testeable sin root)."""
    root = get_domain_root(username, domain)
    mb = clamp_maxmemory(maxmemory_mb)
    return f"""# SVQPanel — Redis dedicado del dominio {domain}. Generado automáticamente.
# NO editar a mano: se regenera desde el panel.
port 0
unixsocket {root}/private/redis.sock
unixsocketperm 700
dir {root}/private
maxmemory {mb}mb
maxmemory-policy allkeys-lru
save ""
appendonly no
daemonize no
supervised no
databases 4
pidfile ""
"""


def render_instance_unit(username: str, domain: str, maxmemory_mb: int) -> str:
    """Unidad systemd de la instancia (pura, testeable sin root)."""
    mb = clamp_maxmemory(maxmemory_mb)
    # MemoryMax = maxmemory + margen para el overhead del propio redis
    # (allocator, buffers de cliente): segunda capa por si redis se pasara.
    return f"""# SVQPanel — Redis dedicado del dominio {domain}. Generado automáticamente.
[Unit]
Description=SVQPanel Redis ({domain})
After=network.target

[Service]
Type=simple
User={username}
Group={username}
ExecStart={REDIS_BIN} {_conf_path(domain)}
Restart=on-failure
RestartSec=3
MemoryMax={mb + 64}M
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=read-only
ReadWritePaths={get_domain_root(username, domain)}/private

[Install]
WantedBy=multi-user.target
"""


def enable_instance(username: str, domain: str,
                    maxmemory_mb: int = DEFAULT_MAXMEMORY_MB) -> dict:
    """
    Crea (o reconfigura) y arranca la instancia Redis del dominio. Idempotente:
    reescribe config + unit y reinicia, tanto si existía como si no.
    """
    if not validate_domain(domain):
        raise ValueError(f"Dominio inválido: {domain}")
    if not redis_available():
        raise RuntimeError(
            "redis-server no está instalado en el servidor "
            "(instálalo con: apt-get install redis-server)")

    root = get_domain_root(username, domain)
    private = f"{root}/private"
    if not os.path.isdir(private):
        os.makedirs(private, exist_ok=True)
        _run(["chown", f"{username}:{username}", private])
        os.chmod(private, 0o750)

    os.makedirs(CONF_DIR, exist_ok=True)
    mb = clamp_maxmemory(maxmemory_mb)
    # Config root-owned pero legible: no contiene secretos y el proceso
    # (que corre como el usuario del dominio) tiene que poder leerla.
    _atomic_write(_conf_path(domain), render_instance_conf(username, domain, mb))
    _atomic_write(_unit_path(domain), render_instance_unit(username, domain, mb))

    _run(["systemctl", "daemon-reload"])
    _run(["systemctl", "enable", _unit_name(domain)])
    r = _run(["systemctl", "restart", _unit_name(domain)])
    if r.returncode != 0:
        raise RuntimeError(f"No se pudo arrancar la instancia: {r.stderr.strip()}")
    logger.info(f"Redis del dominio {domain} activo ({mb}MB, socket unix)")
    return instance_status(username, domain)


def disable_instance(username: str, domain: str) -> dict:
    """Para y elimina por completo la instancia Redis del dominio. Idempotente."""
    unit = _unit_name(domain)
    _run(["systemctl", "disable", "--now", unit])
    for path in (_unit_path(domain), _conf_path(domain)):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as e:
            logger.warning(f"No se pudo borrar {path}: {e}")
    try:
        sock = socket_path(username, domain)
        if os.path.exists(sock):
            os.remove(sock)
    except OSError:
        pass
    _run(["systemctl", "daemon-reload"])
    logger.info(f"Redis del dominio {domain} eliminado")
    return {"enabled": False, "active": False}


def remove_instance(domain: str, username: str = None) -> None:
    """
    Limpieza best-effort al borrar el dominio (no lanza excepciones).
    `username` puede faltar (solo evita borrar el socket, que se va con el rm
    -rf del home de todos modos).
    """
    try:
        if os.path.exists(_unit_path(domain)) or os.path.exists(_conf_path(domain)):
            if username:
                disable_instance(username, domain)
            else:
                _run(["systemctl", "disable", "--now", _unit_name(domain)])
                for path in (_unit_path(domain), _conf_path(domain)):
                    if os.path.exists(path):
                        os.remove(path)
                _run(["systemctl", "daemon-reload"])
    except Exception as e:
        logger.warning(f"No se pudo limpiar el Redis de {domain}: {e}")


def instance_status(username: str, domain: str) -> dict:
    """Estado de la instancia del dominio (para la UI)."""
    unit_exists = os.path.exists(_unit_path(domain))
    active = False
    used_mb = None
    maxmemory_mb = None
    sock = socket_path(username, domain)

    if unit_exists:
        active = _run(["systemctl", "is-active", "--quiet",
                       _unit_name(domain)]).returncode == 0
        conf = _conf_path(domain)
        try:
            with open(conf) as f:
                m = re.search(r"^maxmemory\s+(\d+)mb", f.read(), re.M)
                if m:
                    maxmemory_mb = int(m.group(1))
        except OSError:
            pass
        if active and os.path.exists(REDIS_CLI):
            # root puede conectar al socket aunque sea 700 del usuario
            r = _run([REDIS_CLI, "-s", sock, "info", "memory"], timeout=5)
            m = re.search(r"used_memory:(\d+)", r.stdout or "")
            if m:
                used_mb = round(int(m.group(1)) / (1024 * 1024), 1)

    return {
        "available": redis_available(),
        "enabled": unit_exists,
        "active": active,
        "socket": sock,
        "maxmemory_mb": maxmemory_mb,
        "used_memory_mb": used_mb,
        "maxmemory_cap_mb": MAXMEMORY_CAP_MB,
        "default_maxmemory_mb": DEFAULT_MAXMEMORY_MB,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Protección del Redis global (backend de Rspamd)
# ─────────────────────────────────────────────────────────────────────────────

def _get_or_create_password() -> str:
    try:
        with open(RSPAMD_REDIS_PASS_FILE) as f:
            pw = f.read().strip()
            if pw:
                return pw
    except OSError:
        pass
    pw = secrets.token_hex(32)
    os.makedirs(os.path.dirname(RSPAMD_REDIS_PASS_FILE), exist_ok=True)
    _atomic_write(RSPAMD_REDIS_PASS_FILE, pw + "\n", mode=0o600)
    return pw


def _upsert_block(content: str, block_body: str) -> str:
    """Inserta/actualiza el bloque gestionado del panel en redis.conf."""
    block = f"{_BLOCK_BEGIN}\n{block_body}\n{_BLOCK_END}\n"
    pattern = re.compile(
        re.escape(_BLOCK_BEGIN) + r".*?" + re.escape(_BLOCK_END) + r"\n?",
        re.S)
    if pattern.search(content):
        return pattern.sub(block, content)
    if content and not content.endswith("\n"):
        content += "\n"
    return content + "\n" + block


def secure_rspamd_redis() -> dict:
    """
    Pone contraseña al Redis global (backend de Rspamd) y la propaga a Rspamd.
    Idempotente: reutiliza la clave de /etc/svqpanel/redis_rspamd.pass si ya
    existe. Devuelve {'applied': bool, 'reason': str}.
    """
    if not os.path.exists(GLOBAL_REDIS_CONF):
        return {"applied": False, "reason": "sin Redis global (no hay stack de correo)"}
    if not os.path.isdir("/etc/rspamd"):
        return {"applied": False, "reason": "sin Rspamd; no se toca el Redis global"}

    pw = _get_or_create_password()

    with open(GLOBAL_REDIS_CONF) as f:
        conf = f.read()
    new_conf = _upsert_block(conf, f"requirepass {pw}")
    changed = new_conf != conf
    if changed:
        _atomic_write(GLOBAL_REDIS_CONF, new_conf, mode=0o640)
        _run(["chown", "redis:redis", GLOBAL_REDIS_CONF])

    os.makedirs(os.path.dirname(RSPAMD_LOCAL_REDIS), exist_ok=True)
    rspamd_conf = f'servers = "127.0.0.1";\npassword = "{pw}";\n'
    try:
        with open(RSPAMD_LOCAL_REDIS) as f:
            rspamd_changed = f.read() != rspamd_conf
    except OSError:
        rspamd_changed = True
    if rspamd_changed:
        _atomic_write(RSPAMD_LOCAL_REDIS, rspamd_conf, mode=0o640)
        _run(["chown", "root:_rspamd", RSPAMD_LOCAL_REDIS])

    if changed:
        _run(["systemctl", "restart", "redis-server"])
    if rspamd_changed:
        _run(["systemctl", "restart", "rspamd"])

    # Verificación: sin password debe fallar; con password, PONG.
    ok = True
    if os.path.exists(REDIS_CLI):
        unauth = _run([REDIS_CLI, "-h", "127.0.0.1", "ping"], timeout=5)
        auth = _run([REDIS_CLI, "-h", "127.0.0.1", "-a", pw, "--no-auth-warning",
                     "ping"], timeout=5)
        ok = "PONG" not in (unauth.stdout or "") and "PONG" in (auth.stdout or "")

    logger.info(f"Redis de Rspamd protegido (cambios: redis={changed}, "
                f"rspamd={rspamd_changed}, verificado={ok})")
    return {"applied": True, "changed": changed or rspamd_changed, "verified": ok,
            "reason": "requirepass aplicado y propagado a Rspamd"}
