"""Composer en private/ y subcarpetas + bloqueo de PHP en vendor/ y uploads."""
import os
import re

import pytest

from scripts import composer_manager as cm
from scripts.composer_manager import ComposerError
from scripts.utils import generate_nginx_config
from scripts.apache_vhost_generator import generate_apache_vhost


@pytest.fixture
def dom(tmp_path):
    """/home/u/web/d con public_html, private (con composer.json) y logs."""
    root = tmp_path / "d"
    (root / "public_html").mkdir(parents=True)
    (root / "private" / "api").mkdir(parents=True)
    (root / "private" / "composer.json").write_text('{"require":{"phpseclib/phpseclib":"^3.0"}}')
    (root / "private" / "vendor").mkdir()
    (root / "logs").mkdir()
    return root


def test_sin_dir_es_el_docroot(dom):
    pub = str(dom / "public_html")
    assert cm.resolve_workdir(str(dom), pub, None) == os.path.realpath(pub)
    assert cm.resolve_workdir(str(dom), pub, "  ") == os.path.realpath(pub)


def test_private_y_subcarpeta(dom):
    pub = str(dom / "public_html")
    assert cm.resolve_workdir(str(dom), pub, "private") == os.path.realpath(dom / "private")
    assert cm.resolve_workdir(str(dom), pub, "/private/api/") == os.path.realpath(dom / "private" / "api")


@pytest.mark.parametrize("bad", ["..", "private/..", "private/../logs", "logs", ".",
                                 "/etc", "~root", "private\\api", "a\x00b"])
def test_rechaza_rutas_fuera(dom, bad):
    with pytest.raises(ComposerError):
        cm.resolve_workdir(str(dom), str(dom / "public_html"), bad)


def test_rechaza_carpeta_inexistente(dom):
    with pytest.raises(ComposerError):
        cm.resolve_workdir(str(dom), str(dom / "public_html"), "private/nope")


@pytest.mark.skipif(os.name == "nt", reason="symlinks")
def test_symlink_que_sale_se_rechaza(dom, tmp_path):
    fuera = tmp_path / "otro"
    fuera.mkdir()
    os.symlink(fuera, dom / "private" / "escape")
    with pytest.raises(ComposerError):
        cm.resolve_workdir(str(dom), str(dom / "public_html"), "private/escape")


def test_locations_preselecciona_private(dom):
    (dom / "private" / "api" / "composer.json").write_text("{}")
    loc = cm.composer_locations(str(dom), str(dom / "public_html"))
    dirs = {l["dir"]: l for l in loc["locations"]}
    assert set(dirs) == {"public_html", "private", os.path.join("private", "api")}
    assert dirs["public_html"]["public"] is True
    assert dirs["private"]["public"] is False
    assert dirs["private"]["has_json"] and dirs["private"]["has_vendor"]
    assert loc["suggested"] == "private"


def test_locations_prefiere_privada_aunque_public_tenga_json(dom):
    (dom / "public_html" / "composer.json").write_text("{}")
    loc = cm.composer_locations(str(dom), str(dom / "public_html"))
    assert loc["suggested"] == "private"


def test_locations_laravel_raiz_del_docroot(dom):
    app = dom / "private" / "app"
    (app / "public").mkdir(parents=True)
    (app / "composer.json").write_text("{}")
    loc = cm.composer_locations(str(dom), str(app / "public"))
    dirs = {l["dir"]: l for l in loc["locations"]}
    key = os.path.join("private", "app")
    assert key in dirs and dirs[key]["public"] is False
    assert dirs[os.path.join("private", "app", "public")]["public"] is True


def test_php_bin_valida_version():
    assert cm.php_bin_for("8.3; rm -rf /") is None
    assert cm.php_bin_for(None) is None


# ── vhosts: el deny de PHP va ANTES del bloque de PHP-FPM ────────────────────
def _first(cfg, pat):
    m = re.search(pat, cfg)
    assert m, pat
    return m.start()


@pytest.mark.parametrize("ssl", [False, True])
def test_nginx_deny_php_antes_que_fpm(ssl):
    cfg = generate_nginx_config("ejemplo.com", "u", "8.3", ssl_enabled=ssl)
    checked = 0
    for block in cfg.split("server {")[1:]:
        if "location ~ \\.php$" not in block:
            continue
        checked += 1
        php = block.index("location ~ \\.php$")
        assert block.index("location ~* /vendor/.*\\.php$ { deny all; }") < php
        assert block.index("location ~* /wp-content/uploads/.*\\.php$ { deny all; }") < php
    assert checked == (2 if ssl else 1)


def test_nginx_deny_en_modo_apache():
    cfg = generate_nginx_config("ejemplo.com", "u", "8.3", proxy_to_apache=True)
    assert "location ~* /vendor/.*\\.php$ { deny all; }" in cfg


def test_apache_deny_vendor():
    v = generate_apache_vhost("ejemplo.com", "user1", "8.3")
    assert '<LocationMatch "(?i)/vendor/.*\\.php$">' in v
