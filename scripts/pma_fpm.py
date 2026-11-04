"""
Pool PHP-FPM propio para phpMyAdmin (/pma del panel).

Antes /pma usaba el pool `www` compartido, y el ajuste de webmail
(conf.d/zz-svqpanel-webmail.ini, que es global a esa versión de PHP) le bajaba
el upload a 35 MB: importar un .sql de 80 MB fallaba con "Probablemente intentó
cargar un archivo demasiado grande" aunque el php.ini dijera 64M (Oskarbi,
nov 2026). Con su pool, los php_admin_value de aquí mandan sobre php.ini y
conf.d, así que webmail y phpMyAdmin tienen cada uno sus límites.

Corre como www-data, igual que el pool www (mismas sesiones en
/var/lib/php/sessions, que comparte con signon.php). `ondemand`: sin procesos
mientras nadie usa phpMyAdmin.
"""
import glob
import os
import re
import time
import logging

logger = logging.getLogger(__name__)

POOL_NAME = "svqpanel-pma"
PMA_SOCKET = f"/run/php/{POOL_NAME}.sock"
PMA_DIR = "/var/www/pma"

# Límites de phpMyAdmin. El fastcgi_read_timeout de nginx en /pma es 600s.
UPLOAD_LIMIT = "1G"
EXEC_LIMIT = 600


def pool_content() -> str:
    return f"""; SVQPanel — pool propio de phpMyAdmin (/pma). Generado por scripts/pma_fpm.py:
; no editar a mano (se reescribe). Ver el docstring del módulo.
[{POOL_NAME}]
user = www-data
group = www-data
listen = {PMA_SOCKET}
listen.owner = www-data
listen.group = www-data
listen.mode = 0660

pm = ondemand
pm.max_children = 5
pm.process_idle_timeout = 60s
pm.max_requests = 200
request_terminate_timeout = {EXEC_LIMIT + 60}s

php_admin_value[upload_max_filesize] = {UPLOAD_LIMIT}
php_admin_value[post_max_size] = {UPLOAD_LIMIT}
php_admin_value[max_execution_time] = {EXEC_LIMIT}
php_admin_value[max_input_time] = {EXEC_LIMIT}
php_admin_value[memory_limit] = 1G
"""


def _target_version() -> str | None:
    """Versión del PHP que ya servía /pma: el FPM compartido más alto
    (el mismo criterio que panel_ssl_manager._php_fpm_socket)."""
    socks = sorted(glob.glob("/run/php/php*-fpm.sock"), reverse=True)
    for s in socks:
        m = re.match(r"/run/php/php(\d+\.\d+)-fpm\.sock$", s)
        if m:
            return m.group(1)
    return None


def _existing_pool_paths() -> list:
    return glob.glob(f"/etc/php/*/fpm/pool.d/{POOL_NAME}.conf")


def ensure_pool() -> dict:
    """Crea/actualiza el pool de phpMyAdmin y deja su socket escuchando.
    Idempotente. Si la versión de PHP del pool ya no está, lo mueve a la actual."""
    from scripts.php_ini_manager import _reload_fpm

    if not os.path.isdir(PMA_DIR):
        return {"ok": True, "skipped": "phpMyAdmin no está instalado"}
    version = _target_version()
    if not version:
        return {"ok": False, "error": "No hay ningún PHP-FPM compartido en /run/php"}

    path = f"/etc/php/{version}/fpm/pool.d/{POOL_NAME}.conf"
    content = pool_content()
    old = None
    if os.path.exists(path):
        with open(path) as f:
            old = f.read()
    stale = [p for p in _existing_pool_paths() if p != path]
    if old == content and not stale and os.path.exists(PMA_SOCKET):
        return {"ok": True, "changed": False, "version": version, "socket": PMA_SOCKET}

    # Pool de otra versión (PHP cambiado): retirarlo ANTES, comparten socket.
    for p in stale:
        try:
            os.remove(p)
            _reload_fpm(p.split("/")[3])
        except OSError as e:
            logger.warning("pma_fpm: no se pudo retirar %s: %s", p, e)

    with open(path, "w") as f:
        f.write(content)
    ok, msg = _reload_fpm(version)
    if not ok:
        # Validar antes de destruir: el pool nuevo rompe la config → se retira.
        if old is None:
            os.remove(path)
        else:
            with open(path, "w") as f:
                f.write(old)
        _reload_fpm(version)
        return {"ok": False, "error": msg}

    for _ in range(20):
        if os.path.exists(PMA_SOCKET):
            break
        time.sleep(0.5)
    if not os.path.exists(PMA_SOCKET):
        return {"ok": False, "error": f"php{version}-fpm no ha creado {PMA_SOCKET}"}
    return {"ok": True, "changed": True, "version": version, "socket": PMA_SOCKET}
