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
    Devuelve {'nginx': [...], 'apache': [...], 'broken_links': [...]} con los
    vhosts huérfanos detectados (sin borrar nada). 'broken_links' son symlinks
    de sites-enabled cuyo destino ya no existe (rompen igualmente el configtest).
    """
    result = {"nginx": [], "apache": [], "broken_links": []}

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

    return result


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
    removed = {"nginx": [], "apache": [], "broken_links": []}
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

    # ── Recargar webservers (solo si borramos algo y no es dry-run) ─────────
    if not dry_run:
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
                  + len(removed["broken_links"])),
        "warnings": warnings,
    }
