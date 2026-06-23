"""
orphan_vhosts — detección y limpieza de vhosts huérfanos (nginx y Apache).

Un vhost "huérfano" es un fichero de virtual host que apunta a rutas que YA NO
existen (DocumentRoot/root o el directorio de logs del dominio borrado). Estos
ficheros hacían fallar `nginx -t` / `apache2ctl configtest`, lo que a su vez
bloqueaba la recarga del webserver y, por tanto, el alta de CUALQUIER dominio
nuevo.

Causa raíz (ya corregida en el flujo de borrado): al eliminar un dominio o un
usuario solo se borraba el directorio en disco y, en nginx, su vhost; el vhost
de Apache quedaba colgando. Este módulo SANEA instalaciones ya afectadas.

NUNCA toca el vhost del propio panel (nginx: 'svqpanel'; Apache: cualquier
fichero cuyo nombre empiece por 'svqpanel' o '000-').
"""

import os
import re
import glob
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

NGINX_AVAILABLE = "/etc/nginx/sites-available"
NGINX_ENABLED   = "/etc/nginx/sites-enabled"
APACHE_AVAILABLE = "/etc/apache2/sites-available"
APACHE_ENABLED   = "/etc/apache2/sites-enabled"
# Pools PHP-FPM por dominio: /etc/php/{ver}/fpm/pool.d/svqpanel-{dominio}.conf
PHP_POOL_GLOB = "/etc/php/*/fpm/pool.d/svqpanel-*.conf"
# Zonas DNS (BIND): /etc/bind/zones/db.{dominio}
DNS_ZONES_DIR = "/etc/bind/zones"
DNS_ZONE_PREFIX = "db."

# Nombres protegidos (vhosts del sistema/panel que nunca se borran).
_PROTECTED = ("svqpanel", "svqpanel-welcome", "000-default", "default-ssl", "default")


def _is_protected(name: str) -> bool:
    base = os.path.basename(name)
    stem = base[:-5] if base.endswith(".conf") else base
    return stem in _PROTECTED or base in _PROTECTED


def _extract_paths(content: str) -> List[str]:
    """
    Extrae las rutas relevantes (root/DocumentRoot/ErrorLog/AccessLog/access_log/
    error_log) que apuntan al espacio del dominio (/home/.../web/...).
    Solo nos fijamos en rutas bajo /home para no marcar como huérfano un vhost
    que apunte a rutas del sistema.
    """
    paths = []
    patterns = [
        r'^\s*root\s+([^;]+);',                 # nginx: root /home/.../public_html;
        r'^\s*DocumentRoot\s+"?([^"\n]+?)"?\s*$',  # apache: DocumentRoot /home/...
        r'(?:access_log|error_log)\s+([^\s;]+)',   # nginx logs
        r'(?:CustomLog|ErrorLog)\s+"?([^"\s]+)',   # apache logs
    ]
    for line in content.splitlines():
        for pat in patterns:
            m = re.search(pat, line)
            if m:
                p = m.group(1).strip()
                if p.startswith("/home/"):
                    paths.append(p)
    return paths


def _vhost_is_orphan(content: str) -> bool:
    """
    Un vhost es huérfano si tiene al menos una ruta bajo /home/.../web y el
    directorio del dominio (el padre que contiene public_html/logs) NO existe.
    """
    paths = _extract_paths(content)
    if not paths:
        return False  # sin rutas /home → no lo tocamos (puede ser config especial)

    for p in paths:
        # Subir hasta el directorio del dominio: /home/<u>/web/<dominio>/...
        m = re.match(r'(/home/[^/]+/web/[^/]+)/', p + "/")
        domain_dir = m.group(1) if m else os.path.dirname(p)
        if os.path.isdir(domain_dir):
            return False  # alguna ruta válida → no es huérfano
    return True


def find_orphans() -> Dict[str, List[str]]:
    """
    Devuelve {'nginx', 'apache', 'broken_links', 'php_pools', 'dns_zones'} con
    los recursos huérfanos detectados (sin borrar nada). 'broken_links' son
    symlinks de sites-enabled cuyo destino ya no existe; 'php_pools' son pools
    PHP-FPM por dominio cuyo usuario del sistema ya no existe (rompen `php-fpm -t`
    y, con él, el alta de cualquier dominio nuevo); 'dns_zones' son zone files de
    BIND en disco sin fila correspondiente en la tabla dns_zones.
    """
    result = {"nginx": [], "apache": [], "broken_links": [],
              "php_pools": [], "dns_zones": []}

    for path in glob.glob(os.path.join(NGINX_AVAILABLE, "*")):
        if not os.path.isfile(path) or _is_protected(path):
            continue
        try:
            with open(path, "r", errors="replace") as f:
                if _vhost_is_orphan(f.read()):
                    result["nginx"].append(path)
        except OSError:
            continue

    for path in glob.glob(os.path.join(APACHE_AVAILABLE, "*.conf")):
        if not os.path.isfile(path) or _is_protected(path):
            continue
        try:
            with open(path, "r", errors="replace") as f:
                if _vhost_is_orphan(f.read()):
                    result["apache"].append(path)
        except OSError:
            continue

    # Symlinks rotos en sites-enabled (destino borrado). Es el otro caso real:
    # se borró el .conf de sites-available pero quedó el symlink colgante, que
    # también tumba `nginx -t` / `apache2ctl configtest`.
    result["broken_links"] = _find_broken_symlinks()

    # Pools PHP-FPM cuyo usuario del sistema ya no existe.
    result["php_pools"] = _find_orphan_php_pools()

    # Zone files de BIND sin fila en dns_zones.
    result["dns_zones"] = _find_orphan_dns_zones()

    return result


def _find_orphan_dns_zones() -> List[str]:
    """
    Zone files /etc/bind/zones/db.{dominio} cuyo {dominio} ya no existe en la
    tabla dns_zones (quedaron de borrados antiguos). No suelen romper BIND (no
    están en named.conf.zones), pero son basura en disco.

    Si no se puede consultar la BD, devuelve [] (conservador: no borrar a ciegas).
    """
    if not os.path.isdir(DNS_ZONES_DIR):
        return []
    try:
        from api.models.database import SessionLocal
        from api.models.models_dns import DnsZone
        db = SessionLocal()
        try:
            known = {z.domain_name for z in db.query(DnsZone).all()}
        finally:
            db.close()
    except Exception:
        return []

    orphans = []
    for name in os.listdir(DNS_ZONES_DIR):
        if not name.startswith(DNS_ZONE_PREFIX):
            continue
        domain = name[len(DNS_ZONE_PREFIX):]
        if domain and domain not in known:
            orphans.append(os.path.join(DNS_ZONES_DIR, name))
    return orphans


def _user_exists(username: str) -> bool:
    import pwd
    try:
        pwd.getpwnam(username)
        return True
    except KeyError:
        return False


def _find_orphan_php_pools() -> List[str]:
    """
    Pools PHP-FPM por dominio (svqpanel-*.conf) cuyo `user = X` apunta a un
    usuario del sistema que ya no existe. Esos pools hacen fallar `php-fpm -t`
    y, en cadena, bloquean el alta de nuevos dominios.
    """
    orphans = []
    for path in glob.glob(PHP_POOL_GLOB):
        try:
            with open(path, "r", errors="replace") as f:
                content = f.read()
        except OSError:
            continue
        m = re.search(r'^\s*user\s*=\s*(\S+)', content, re.MULTILINE)
        if not m:
            continue
        owner = m.group(1).strip()
        if not _user_exists(owner):
            orphans.append(path)
    return orphans


def _find_broken_symlinks() -> List[str]:
    """Symlinks colgantes (destino inexistente) en los sites-enabled de nginx y
    Apache, excluyendo los protegidos del panel."""
    broken = []
    for d in (NGINX_ENABLED, APACHE_ENABLED):
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        for name in entries:
            if _is_protected(name):
                continue
            link = os.path.join(d, name)
            # islink + no existe el destino  → symlink roto
            if os.path.islink(link) and not os.path.exists(link):
                broken.append(link)
    return broken


def clean_orphans(dry_run: bool = False) -> Dict[str, object]:
    """
    Borra los vhosts huérfanos (nginx + Apache) y recarga cada webserver.

    Si dry_run=True solo informa de lo que haría. Devuelve un dict con la lista
    de ficheros borrados y avisos.
    """
    from scripts.base import SystemManager
    sm = SystemManager(require_root=True)

    orphans = find_orphans()
    removed = {"nginx": [], "apache": [], "broken_links": [],
               "php_pools": [], "dns_zones": []}
    warnings: List[str] = []

    # Saber a qué webserver pertenece cada symlink roto, para recargar el correcto.
    nginx_link_broken = any(l.startswith(NGINX_ENABLED) for l in orphans["broken_links"])
    apache_link_broken = any(l.startswith(APACHE_ENABLED) for l in orphans["broken_links"])

    # ── nginx ─────────────────────────────────────────────────────────────
    for path in orphans["nginx"]:
        name = os.path.basename(path)
        enabled = os.path.join(NGINX_ENABLED, name)
        if dry_run:
            removed["nginx"].append(path)
            continue
        try:
            if os.path.islink(enabled) or os.path.exists(enabled):
                os.remove(enabled)
            os.remove(path)
            removed["nginx"].append(path)
            logger.info(f"Vhost nginx huérfano borrado: {path}")
        except OSError as e:
            warnings.append(f"nginx[{name}]: {e}")

    # ── Apache ────────────────────────────────────────────────────────────
    for path in orphans["apache"]:
        name = os.path.basename(path)          # <dominio>.conf
        stem = name[:-5] if name.endswith(".conf") else name
        if dry_run:
            removed["apache"].append(path)
            continue
        try:
            sm.execute_command(["a2dissite", name], check=False)
            sm.execute_command(["a2dissite", stem], check=False)
            if os.path.exists(path):
                os.remove(path)
            removed["apache"].append(path)
            logger.info(f"Vhost Apache huérfano borrado: {path}")
        except Exception as e:
            warnings.append(f"apache[{name}]: {e}")

    # ── Symlinks rotos en sites-enabled (nginx + Apache) ────────────────────
    for link in orphans["broken_links"]:
        if dry_run:
            removed["broken_links"].append(link)
            continue
        try:
            os.remove(link)   # borrar el symlink colgante (no toca destino)
            removed["broken_links"].append(link)
            logger.info(f"Symlink huérfano borrado: {link}")
        except OSError as e:
            warnings.append(f"link[{os.path.basename(link)}]: {e}")

    # ── Pools PHP-FPM huérfanos (usuario inexistente) ───────────────────────
    fpm_versions_touched = set()
    for path in orphans["php_pools"]:
        # /etc/php/{ver}/fpm/pool.d/...  → extraer la versión para recargar FPM
        m = re.search(r'/etc/php/([^/]+)/fpm/', path)
        ver = m.group(1) if m else None
        if dry_run:
            removed["php_pools"].append(path)
            continue
        try:
            os.remove(path)
            removed["php_pools"].append(path)
            if ver:
                fpm_versions_touched.add(ver)
            logger.info(f"Pool PHP-FPM huérfano borrado: {path}")
        except OSError as e:
            warnings.append(f"php_pool[{os.path.basename(path)}]: {e}")

    # ── Zone files DNS huérfanos (sin fila en dns_zones) ────────────────────
    for path in orphans["dns_zones"]:
        if dry_run:
            removed["dns_zones"].append(path)
            continue
        try:
            os.remove(path)
            removed["dns_zones"].append(path)
            logger.info(f"Zone file DNS huérfano borrado: {path}")
        except OSError as e:
            warnings.append(f"dns_zone[{os.path.basename(path)}]: {e}")

    # ── Recargar webservers (solo si borramos algo y no es dry-run) ─────────
    if not dry_run:
        for ver in fpm_versions_touched:
            try:
                sm.execute_command(["systemctl", "reload", f"php{ver}-fpm"], check=False)
            except Exception as e:
                warnings.append(f"reload php{ver}-fpm: {e}")
        if removed["nginx"] or nginx_link_broken:
            try:
                from scripts.utils import nginx_configtest, reload_nginx
                ok, out = nginx_configtest()
                if ok:
                    reload_nginx()
                else:
                    warnings.append(f"nginx -t sigue fallando tras la limpieza: {out.strip()}")
            except Exception as e:
                warnings.append(f"reload nginx: {e}")
        if removed["apache"] or apache_link_broken:
            rc, _o, err = sm.execute_command(["apache2ctl", "configtest"], check=False)
            if rc == 0:
                sm.execute_command(["systemctl", "reload", "apache2"], check=False)
            else:
                warnings.append(f"apache configtest sigue fallando: {(err or '').strip()}")

    return {
        "dry_run": dry_run,
        "removed": removed,
        "count": (len(removed["nginx"]) + len(removed["apache"])
                  + len(removed["broken_links"]) + len(removed["php_pools"])
                  + len(removed["dns_zones"])),
        "warnings": warnings,
    }
