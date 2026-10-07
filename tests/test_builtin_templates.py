"""Plantillas web builtin: aportan valor y no chocan con lo que ya hace el panel.

Antes (oct 2026) varias nunca podían aplicarse (nginx -t: duplicate location "/",
client_max_body_size duplicado, .well-known duplicado, variable $blogid
inexistente) y otras anulaban protecciones del panel (location = /wp-login.php
exacto se saltaba el rate-limit; fastcgi_pass directo se saltaba Apache).
Se genera el vhost REAL con cada plantilla, en los dos modos, y se comprueba.
"""
import re

import pytest

from scripts.template_manager import BUILTIN_TEMPLATES
from scripts.utils import (generate_nginx_config, template_extra_for_mode,
                           template_owns_root_location, upload_mb_from_php)

SLUGS = [t["slug"] for t in BUILTIN_TEMPLATES]
BY_SLUG = {t["slug"]: t for t in BUILTIN_TEMPLATES}


def _render(tpl, proxy, ssl):
    return generate_nginx_config(
        "ejemplo.com", "user1", "8.3", ssl_enabled=ssl, proxy_to_apache=proxy,
        template_nginx_extra=tpl.get("nginx_extra"),
        docroot_subdir=tpl.get("docroot_subdir"),
        xmlrpc_blocked=True, wp_login_ratelimit=3)


def _server_blocks(cfg):
    """Trocea el vhost en bloques server{} (cuenta llaves)."""
    blocks, depth, cur = [], 0, None
    for line in cfg.splitlines():
        s = line.strip()
        if cur is None and re.match(r"^server\s*\{", s):
            cur, depth = [], 0
        if cur is not None:
            cur.append(line)
            depth += line.count("{") - line.count("}")
            if depth == 0:
                blocks.append("\n".join(cur))
                cur = None
    return blocks


@pytest.mark.parametrize("slug", SLUGS)
@pytest.mark.parametrize("proxy", [False, True], ids=["nginx", "apache"])
@pytest.mark.parametrize("ssl", [False, True], ids=["http", "https"])
def test_vhost_con_plantilla_es_coherente(slug, proxy, ssl):
    cfg = _render(BY_SLUG[slug], proxy, ssl)
    blocks = [b for b in _server_blocks(cfg) if "root " in b]
    assert blocks, "debe haber al menos un server con root"
    for b in blocks:
        roots = re.findall(r"^\s*location\s+/\s*\{", b, re.M)
        assert len(roots) == 1, f"{slug}: {len(roots)} 'location /' en un server (duplicate location)"
        exact = re.findall(r"^\s*location\s+=\s+(\S+)", b, re.M)
        assert len(exact) == len(set(exact)), f"{slug}: location = duplicada {exact}"
        assert len(re.findall(r"client_max_body_size", b)) == 1, f"{slug}: client_max_body_size duplicado"
    assert "solo-nginx" not in cfg, "las marcas no deben llegar al vhost"
    assert "$blogid" not in cfg, "variable inexistente en nginx"
    if proxy:
        assert "fastcgi_pass" not in cfg, f"{slug}: en Apache+Nginx no debe saltarse Apache"


@pytest.mark.parametrize("slug", SLUGS)
def test_plantilla_no_repite_ni_anula_lo_del_panel(slug):
    extra = BY_SLUG[slug].get("nginx_extra") or ""
    # Cabeceras generales: las pone la tarjeta "Headers de seguridad"
    for h in ("X-Frame-Options", "X-Content-Type-Options", "Referrer-Policy", "X-XSS-Protection"):
        assert h not in extra, f"{slug}: {h} ya lo da el panel"
    assert "client_max_body_size" not in extra, "sale del PHP del dominio"
    assert ".well-known" not in extra, "el panel ya pone las redirecciones DAV"
    assert not re.search(r"location\s+=\s+/wp-(login|cron)\.php", extra), \
        "un location exacto anula la protección de wp-login / rompe wp-cron"
    # fastcgi_pass solo dentro de bloques solo-nginx
    assert "fastcgi_pass" not in (template_extra_for_mode(extra, True) or "")


def test_solo_ghost_y_spa_sustituyen_location_raiz():
    owners = {s for s in SLUGS if template_owns_root_location(BY_SLUG[s].get("nginx_extra"))}
    assert owners == {"ghost", "static-spa"}


def test_spa_se_sirve_sin_php_ni_apache():
    cfg = generate_nginx_config("ejemplo.com", "u", "8.3", proxy_to_apache=True,
                                template_nginx_extra=BY_SLUG["static-spa"]["nginx_extra"])
    assert "try_files $uri $uri/ /index.html" in cfg
    assert "proxy_pass http://127.0.0.1:8181" not in cfg


def test_wordpress_conserva_las_protecciones_del_panel():
    cfg = _render(BY_SLUG["wordpress"], proxy=True, ssl=False)
    assert "location ~ ^/+wp-login\\.php" in cfg      # rate-limit del panel
    assert "location ~ ^/+xmlrpc\\.php { return 444; }" in cfg
    assert "wp-config" in cfg


def test_solo_nginx_se_quita_en_apache_y_se_conserva_en_nginx():
    extra = "a\n    # >>> solo-nginx\n    b;\n    # <<< solo-nginx\nc\n"
    assert template_extra_for_mode(extra, True) == "a\nc\n"
    assert template_extra_for_mode(extra, False) == "a\n    b;\nc\n"


def test_upload_mb_sigue_al_php_del_dominio():
    assert upload_mb_from_php(None) == 64
    assert upload_mb_from_php('{"upload_max_filesize": "16G", "post_max_size": "16G"}') == 16384
    assert upload_mb_from_php('{"upload_max_filesize": "256M", "post_max_size": "300M"}') == 300
    assert upload_mb_from_php('{"upload_max_filesize": "8M"}') == 64   # nunca baja del default
    assert upload_mb_from_php("no-json") == 64


def test_woocommerce_no_se_cachea():
    cfg = generate_nginx_config("ejemplo.com", "u", "8.3", fastcgi_cache_enabled=True)
    assert "my-account" in cfg and "finalizar-compra" in cfg
