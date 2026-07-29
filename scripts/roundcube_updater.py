"""
SVQPanel — Actualizador de Roundcube (webmail).

Roundcube NO viene de apt: el install lo descarga como tarball desde GitHub a
/var/www/roundcube (symlink /var/www/webmail). Por tanto ni `apt upgrade` ni el
`update.sh` del panel lo actualizan nunca: un servidor instalado hace meses se
queda clavado en la versión de aquel día, acumulando CVEs (p.ej. 1.7.2 arregla
CVE-2026-54433, un XSS *zero-click* que se dispara con solo abrir un correo).

Este módulo es el único camino de actualización del webmail. Lo usan:
  • updates/0129-roundcube-security-update.sh  (servidores ya instalados)
  • scripts/component_updater.py               (botón del panel, Sistema →
    Actualizaciones → Componentes gestionados)

Estrategia: usar el actualizador OFICIAL de Roundcube (`bin/installto.sh -y`),
que hace rsync de los ficheros nuevos sobre la instalación existente y luego
ejecuta `bin/update.sh` para migrar la BD. Es el camino soportado por upstream
y preserva config/, plugins/ (incluido nuestro svqpanel_autologin) y skins/.

Salvaguardas: backup de ficheros + dump de BD antes de tocar, verificación HTTP
al final y reversión automática si el webmail deja de responder.
"""

import glob
import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

logger = logging.getLogger(__name__)

RC_DIR = "/var/www/roundcube"          # instalación real
RC_LINK = "/var/www/webmail"           # symlink que usan los vhosts
INISET = "program/include/iniset.php"  # de aquí se lee RCMAIL_VERSION
BACKUP_DIR = "/var/backups/svqpanel/roundcube"
GITHUB_LATEST = "https://api.github.com/repos/roundcube/roundcubemail/releases/latest"
TARBALL_URL = ("https://github.com/roundcube/roundcubemail/releases/download/"
               "{v}/roundcubemail-{v}-complete.tar.gz")

# Cuántos backups conservamos (cada uno ~40 MB)
KEEP_BACKUPS = 3


def _run(cmd, timeout=600, cwd=None):
    """Ejecuta un comando y devuelve (rc, salida combinada)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, cwd=cwd)
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, f"Timeout ejecutando: {' '.join(cmd)}"
    except Exception as e:  # noqa: BLE001
        return 1, str(e)


def is_installed() -> bool:
    return os.path.isfile(os.path.join(RC_DIR, INISET))


def installed_version() -> str:
    """Versión realmente instalada, leída de iniset.php (no de credentials)."""
    try:
        with open(os.path.join(RC_DIR, INISET), "r", errors="replace") as f:
            m = re.search(r"define\(\s*'RCMAIL_VERSION'\s*,\s*'([^']+)'", f.read())
            if m:
                return m.group(1)
    except Exception as e:  # noqa: BLE001
        logger.debug("No se pudo leer RCMAIL_VERSION: %s", e)
    return ""


def latest_version(timeout: int = 15) -> str:
    """Última release estable en GitHub. Cadena vacía si no se puede consultar.

    Descartamos pre-releases (rc/beta): en un servidor de producción solo
    queremos versiones finales.
    """
    try:
        req = urllib.request.Request(
            GITHUB_LATEST, headers={"User-Agent": "SVQPanel"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        tag = (data.get("tag_name") or "").strip()
        if tag and not re.search(r"(rc|beta|alpha)", tag, re.I):
            return tag
    except Exception as e:  # noqa: BLE001
        logger.warning("No se pudo consultar la última versión de Roundcube: %s", e)
    return ""


def _vt(v: str):
    """'1.7.10' → (1,7,10) para comparar. Tolera sufijos."""
    parts = []
    for p in (v or "0").split("."):
        num = ""
        for ch in p:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def check() -> dict:
    """Estado del webmail sin tocar nada (barato, seguro desde la UI)."""
    if not is_installed():
        return {"installed": False, "current": "", "latest": "",
                "update_available": False}
    cur = installed_version()
    lat = latest_version()
    return {
        "installed": True,
        "current": cur,
        "latest": lat or cur,
        "update_available": bool(lat and cur and _vt(lat) > _vt(cur)),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Backup / restauración
# ─────────────────────────────────────────────────────────────────────────────
def _db_dsn() -> str:
    """Lee db_dsnw del config de Roundcube (para el dump previo)."""
    try:
        with open(os.path.join(RC_DIR, "config/config.inc.php"),
                  "r", errors="replace") as f:
            m = re.search(r"\$config\['db_dsnw'\]\s*=\s*'([^']+)'", f.read())
            if m:
                return m.group(1)
    except Exception:  # noqa: BLE001
        pass
    return ""


def _dump_db(dest: str) -> bool:
    """Dump de la BD de Roundcube (PostgreSQL). Best-effort.

    La BD guarda contactos, identidades y preferencias del usuario: no es
    crítica para que el webmail arranque, pero sí para no perder datos del
    cliente si una migración de `bin/update.sh` sale mal.
    """
    dsn = _db_dsn()
    m = re.match(r"pgsql://([^:]+):([^@]+)@([^/]+)/(\S+)", dsn or "")
    if not m:
        logger.warning("No se pudo interpretar db_dsnw; se omite el dump de BD")
        return False
    user, pwd, host, db = m.groups()
    env = dict(os.environ, PGPASSWORD=pwd)
    try:
        with open(dest, "wb") as out:
            r = subprocess.run(
                ["pg_dump", "-h", host.split(":")[0], "-U", user, db],
                stdout=out, stderr=subprocess.PIPE, timeout=300, env=env)
        if r.returncode == 0:
            return True
        logger.warning("pg_dump falló: %s", r.stderr.decode(errors="replace")[:300])
    except Exception as e:  # noqa: BLE001
        logger.warning("pg_dump no disponible o falló: %s", e)
    return False


def _prune_backups():
    """Conserva solo los KEEP_BACKUPS backups más recientes."""
    try:
        dirs = sorted(glob.glob(os.path.join(BACKUP_DIR, "*")),
                      key=os.path.getmtime, reverse=True)
        for old in dirs[KEEP_BACKUPS:]:
            shutil.rmtree(old, ignore_errors=True)
    except Exception as e:  # noqa: BLE001
        logger.debug("No se pudieron limpiar backups antiguos: %s", e)


def _backup(version: str, stamp: str) -> str:
    """Copia /var/www/roundcube + dump de BD. Devuelve la ruta del backup."""
    dest = os.path.join(BACKUP_DIR, f"{stamp}-{version or 'desconocida'}")
    os.makedirs(dest, exist_ok=True)
    files_dir = os.path.join(dest, "files")
    # copytree con symlinks=True: no seguimos enlaces fuera del árbol
    shutil.copytree(RC_DIR, files_dir, symlinks=True, dirs_exist_ok=True)
    _dump_db(os.path.join(dest, "roundcubemail.sql"))
    _prune_backups()
    return dest


def _restore(backup_path: str) -> bool:
    """Revierte los ficheros desde un backup (la BD NO se revierte: ver nota)."""
    files_dir = os.path.join(backup_path, "files")
    if not os.path.isdir(files_dir):
        logger.error("Backup incompleto en %s: no se puede revertir", backup_path)
        return False
    try:
        broken = RC_DIR + ".failed"
        shutil.rmtree(broken, ignore_errors=True)
        os.rename(RC_DIR, broken)
        shutil.copytree(files_dir, RC_DIR, symlinks=True)
        shutil.rmtree(broken, ignore_errors=True)
        _fix_permissions()
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("Fallo al revertir Roundcube: %s", e)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Post-instalación
# ─────────────────────────────────────────────────────────────────────────────
def _patch_php85_bootstrap() -> bool:
    """Reaplica el guard array_first/array_last/array_is_list si hace falta.

    PHP 8.4+ trae esas funciones de forma nativa; si bootstrap.php las declara
    sin guard, PHP aborta con "Cannot redeclare" y el webmail entero cae con
    500. Roundcube 1.7.x ya no las declara, así que normalmente esto es un
    no-op; lo mantenemos porque `installto.sh` sincroniza program/ con --delete
    (borra cualquier parche previo) y porque el updater debe seguir siendo
    correcto si se actualiza desde una rama antigua.
    """
    path = os.path.join(RC_DIR, "program/lib/Roundcube/bootstrap.php")
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "r", errors="replace") as f:
            lines = f.readlines()
        out, i, changed = [], 0, False
        while i < len(lines):
            line = lines[i]
            m = re.search(r"^function (array_first|array_last|array_is_list)\(", line)
            if m:
                fname = m.group(1)
                out.append(f"if (!function_exists('{fname}')) {{\n")
                out.append(line)
                i += 1
                depth = 1
                while i < len(lines) and depth > 0:
                    out.append(lines[i])
                    depth += lines[i].count("{") - lines[i].count("}")
                    i += 1
                out.append("}\n")
                changed = True
                continue
            out.append(line)
            i += 1
        if changed:
            with open(path, "w") as f:
                f.writelines(out)
            logger.info("bootstrap.php: guard PHP 8.4/8.5 reaplicado")
        return changed
    except Exception as e:  # noqa: BLE001
        logger.warning("No se pudo parchear bootstrap.php: %s", e)
        return False


def _fix_permissions():
    """temp/ y logs/ deben ser escribibles por www-data; config/ legible."""
    for d in ("temp", "logs"):
        p = os.path.join(RC_DIR, d)
        os.makedirs(p, exist_ok=True)
        _run(["chown", "-R", "www-data:www-data", p], timeout=120)
        _run(["chmod", "775", p], timeout=30)
    cfg = os.path.join(RC_DIR, "config")
    if os.path.isdir(cfg):
        _run(["chown", "-R", "www-data:www-data", cfg], timeout=60)


def _verify_http() -> tuple:
    """¿Sigue sirviendo el webmail? Prueba contra un vhost real por Host header.

    No usamos el hostname del panel: el webmail se sirve en webmail.{dominio}
    por vhosts dedicados. Probamos contra 127.0.0.1 pasando el Host de uno de
    esos vhosts, que es exactamente la ruta que recorre un cliente.
    """
    hosts = []
    for f in sorted(glob.glob("/etc/nginx/sites-enabled/svqpanel-webmail-*")):
        dom = os.path.basename(f).replace("svqpanel-webmail-", "")
        if dom:
            hosts.append(f"webmail.{dom}")
    # Si no hay ningún dominio con correo, probamos /webmail del panel
    if not hosts:
        rc, out = _run(["curl", "-sk", "-o", "/dev/null", "-w", "%{http_code}",
                        "--max-time", "15", "https://127.0.0.1/webmail/"],
                       timeout=30)
        return (out.strip() in ("200", "302"), f"/webmail → {out.strip()}")

    for host in hosts[:3]:  # con 3 basta para descartar un fallo global
        rc, out = _run(["curl", "-sk", "-o", "/dev/null", "-w", "%{http_code}",
                        "--max-time", "15", "-H", f"Host: {host}",
                        "https://127.0.0.1/"], timeout=30)
        code = out.strip()
        if code in ("200", "302"):
            return True, f"{host} → {code}"
    return False, f"ningún vhost de webmail respondió 200 (probados: {hosts[:3]})"


def _reload_php_fpm():
    """Recarga los PHP-FPM para soltar cachés de opcode del código viejo."""
    rc, out = _run(["bash", "-c",
                    "systemctl list-units --type=service --no-legend "
                    "'php*-fpm.service' | awk '{print $1}'"], timeout=60)
    for svc in [s for s in out.splitlines() if s.strip()]:
        _run(["systemctl", "reload", svc.strip()], timeout=60)


# ─────────────────────────────────────────────────────────────────────────────
# Actualización
# ─────────────────────────────────────────────────────────────────────────────
def update(target: str = "", force: bool = False) -> dict:
    """Actualiza Roundcube a `target` (o a la última estable).

    Devuelve {ok, current, previous, log, skipped, restored}. Idempotente: si
    ya está en la versión objetivo y no se fuerza, no toca nada.
    """
    log = []

    def _log(msg):
        log.append(msg)
        logger.info("roundcube_updater: %s", msg)

    if not is_installed():
        return {"ok": True, "skipped": True, "current": "",
                "log": ["Roundcube no está instalado; nada que hacer"]}

    current = installed_version()
    target = target or latest_version()
    if not target:
        return {"ok": False, "skipped": True, "current": current,
                "log": ["No se pudo determinar la última versión "
                        "(¿sin red o GitHub caído?). Se reintentará luego."]}

    if not force and current and _vt(current) >= _vt(target):
        return {"ok": True, "skipped": True, "current": current,
                "latest": target,
                "log": [f"Roundcube ya está en {current} (última: {target})"]}

    _log(f"Actualizando Roundcube {current or '?'} → {target}")

    # 1) Descargar y extraer el tarball oficial en un temporal
    tmp = tempfile.mkdtemp(prefix="rcupd-")
    try:
        tgz = os.path.join(tmp, f"roundcubemail-{target}-complete.tar.gz")
        url = TARBALL_URL.format(v=target)
        rc, out = _run(["curl", "-fsSL", url, "-o", tgz], timeout=600)
        if rc != 0 or not os.path.isfile(tgz):
            return {"ok": False, "current": current,
                    "log": log + [f"No se pudo descargar {url}: {out[:300]}"]}
        _log(f"Descargado {os.path.getsize(tgz) // 1024} KB")

        try:
            with tarfile.open(tgz) as tf:
                # filter="data" (Python 3.12+): rechaza rutas absolutas, enlaces
                # fuera del destino y metadatos raros. En 3.14 es el default y
                # sin pasarlo salta un DeprecationWarning en el log del cron.
                try:
                    tf.extractall(tmp, filter="data")
                except TypeError:  # Python < 3.12
                    tf.extractall(tmp)  # noqa: S202 — tarball oficial de GitHub
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "current": current,
                    "log": log + [f"Tarball corrupto: {e}"]}

        src = os.path.join(tmp, f"roundcubemail-{target}")
        if not os.path.isdir(src):
            return {"ok": False, "current": current,
                    "log": log + [f"El tarball no contiene {src}"]}

        # 2) Backup (ficheros + BD) ANTES de tocar nada
        stamp = _stamp()
        try:
            backup = _backup(current, stamp)
            _log(f"Backup en {backup}")
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "current": current,
                    "log": log + [f"No se pudo hacer backup, se aborta: {e}"]}

        # 3) Actualizador oficial: rsync de ficheros + migraciones de BD.
        #    -y lo hace no interactivo (imprescindible: esto corre en cron).
        rc, out = _run(["php", os.path.join(src, "bin/installto.sh"), "-y", RC_DIR],
                       timeout=900, cwd=src)
        _log(f"installto.sh rc={rc}")
        if out:
            log.append(out[-4000:])
        if rc != 0:
            _log("installto.sh falló; revirtiendo backup")
            restored = _restore(backup)
            _reload_php_fpm()
            return {"ok": False, "current": installed_version(),
                    "previous": current, "restored": restored, "log": log}

        # 4) Post-instalación: guard PHP 8.5, permisos, recarga de FPM
        _patch_php85_bootstrap()
        _fix_permissions()
        _reload_php_fpm()

        # 5) Verificar que el webmail sigue vivo; si no, revertir
        ok, detail = _verify_http()
        _log(f"Verificación HTTP: {detail}")
        if not ok:
            _log("El webmail no responde tras actualizar; revirtiendo")
            restored = _restore(backup)
            _reload_php_fpm()
            ok2, detail2 = _verify_http()
            _log(f"Tras revertir: {detail2}")
            return {"ok": False, "current": installed_version(),
                    "previous": current, "restored": restored, "log": log}

        new = installed_version()
        _log(f"Roundcube actualizado correctamente a {new}")
        _write_credentials_version(new)
        return {"ok": True, "current": new, "previous": current,
                "backup": backup, "log": log}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _stamp() -> str:
    """Marca de tiempo para el nombre del backup."""
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _write_credentials_version(version: str):
    """Refresca roundcube_version en el fichero de credenciales del install.

    Lo escribe install.sh y se quedaba mintiendo tras cada actualización.
    """
    path = "/opt/svqpanel/.credentials/roundcube.txt"
    if not os.path.isfile(path) or not version:
        return
    try:
        with open(path, "r", errors="replace") as f:
            lines = f.readlines()
        out, found = [], False
        for line in lines:
            if line.startswith("roundcube_version="):
                out.append(f"roundcube_version={version}\n")
                found = True
            else:
                out.append(line)
        if not found:
            out.append(f"roundcube_version={version}\n")
        with open(path, "w") as f:
            f.writelines(out)
    except Exception as e:  # noqa: BLE001
        logger.debug("No se pudo refrescar roundcube.txt: %s", e)


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if "--check" in sys.argv:
        print(json.dumps(check(), indent=2))
    else:
        forced = "--force" in sys.argv
        tgt = ""
        for a in sys.argv[1:]:
            if a.startswith("--version="):
                tgt = a.split("=", 1)[1]
        res = update(target=tgt, force=forced)
        for line in res.get("log", []):
            print(line)
        sys.exit(0 if res.get("ok") else 1)
