"""
Ajustes de WordPress al importar (oct 2026): de 12 webs migradas de Hestia, 5
daban 404 en todas las páginas interiores (venían de nginx, sin reglas en el
.htaccess, y aquí van con Apache) y 3 entraban en bucle de redirección (el
panel forzaba www y su WordPress no lo llevaba). El importador ahora detecta
WordPress y deja el .htaccess y el canónico coherentes.
"""
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scripts.hestia_import as hi


def _wp_site(tmp_path, htaccess=None):
    (tmp_path / "wp-includes").mkdir()
    (tmp_path / "wp-includes" / "version.php").write_text("<?php $wp_version = '6.8.1';")
    (tmp_path / "wp-config.php").write_text("<?php define('DB_NAME', 'x');")
    if htaccess is not None:
        (tmp_path / ".htaccess").write_text(htaccess)
    return tmp_path


# ── .htaccess ─────────────────────────────────────────────────────────────
def test_anade_el_bloque_y_conserva_lo_que_habia(tmp_path):
    lsc = "# BEGIN LSCACHE\n# END LSCACHE\n"
    _wp_site(tmp_path, lsc)
    assert hi.ensure_wp_htaccess(str(tmp_path)) is True
    txt = (tmp_path / ".htaccess").read_text()
    assert txt.startswith(lsc) and "# BEGIN WordPress" in txt and "RewriteRule . /index.php [L]" in txt


def test_sin_htaccess_lo_crea(tmp_path):
    _wp_site(tmp_path)
    assert hi.ensure_wp_htaccess(str(tmp_path)) is True
    assert "# BEGIN WordPress" in (tmp_path / ".htaccess").read_text()


def test_no_duplica_si_ya_tiene_reglas(tmp_path):
    _wp_site(tmp_path, "# BEGIN WordPress\nRewriteEngine On\n# END WordPress\n")
    assert hi.ensure_wp_htaccess(str(tmp_path)) is False
    # Reglas propias equivalentes sin la marca BEGIN WordPress también cuentan
    (tmp_path / ".htaccess").write_text("RewriteEngine On\nRewriteRule . /index.php [L]\n")
    assert hi.ensure_wp_htaccess(str(tmp_path)) is False


# ── canónico ──────────────────────────────────────────────────────────────
def test_canonico_segun_home():
    assert hi.canonical_from_home("https://gruporafaelllano.com", "gruporafaelllano.com") == "non-www"
    assert hi.canonical_from_home("https://www.capsevilla.com/", "capsevilla.com") == "www"
    assert hi.canonical_from_home("http://metodoadictosalavida.com", "metodoadictosalavida.com") == "non-www"
    # home de otro dominio, vacío o raro: no se toca
    assert hi.canonical_from_home("https://otra-web.com", "capsevilla.com") is None
    assert hi.canonical_from_home("", "capsevilla.com") is None


# ── paso completo ─────────────────────────────────────────────────────────
class _DB:
    def __init__(self, domain):
        self.domain, self.commits = domain, 0

    def query(self, _model):
        return self

    def filter(self, *_a):
        return self

    def first(self):
        return self.domain

    def commit(self):
        self.commits += 1


def _domain(root, canonical="www", **kw):
    base = dict(domain_name="afincas4.com", custom_docroot=None, public_html=str(root),
                canonical_domain=canonical, is_subdomain=False, redirect_to=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_wordpress_sin_www_corrige_canonico_y_htaccess(tmp_path):
    _wp_site(tmp_path, "")
    d = _domain(tmp_path)
    report = hi.ImportReport()
    regen = []
    with patch("scripts.wp_manager._wp", return_value=(0, "https://afincas4.com\n", "")), \
         patch("api.routes.domains._regenerate_domain_vhost", side_effect=lambda dom, own: regen.append(dom.canonical_domain)):
        hi._finalize_wordpress("afincas4.com", SimpleNamespace(username="afincas4"), _DB(d), report)
    assert d.canonical_domain == "non-www" and regen == ["non-www"]
    tipos = [c["type"] for c in report.to_dict()["created"]]
    assert "wp-htaccess" in tipos and "wp-canonico" in tipos


def test_si_falla_el_vhost_se_revierte(tmp_path):
    _wp_site(tmp_path, "# BEGIN WordPress\n")
    d = _domain(tmp_path)
    report = hi.ImportReport()
    with patch("scripts.wp_manager._wp", return_value=(0, "https://afincas4.com", "")), \
         patch("api.routes.domains._regenerate_domain_vhost", side_effect=RuntimeError("nginx -t falla")):
        hi._finalize_wordpress("afincas4.com", SimpleNamespace(username="u"), _DB(d), report)
    assert d.canonical_domain == "www"
    assert report.to_dict()["errors"][0]["type"] == "wp-canonico"


def test_no_wordpress_o_ya_coherente_no_toca_nada(tmp_path):
    d = _domain(tmp_path)                       # sin wp-config: no es WordPress
    with patch("scripts.wp_manager._wp") as wp:
        hi._finalize_wordpress("afincas4.com", SimpleNamespace(username="u"), _DB(d), hi.ImportReport())
    wp.assert_not_called()
    assert not (tmp_path / ".htaccess").exists()

    _wp_site(tmp_path, "# BEGIN WordPress\n")
    d = _domain(tmp_path, canonical="www")      # WordPress con www y panel con www
    with patch("scripts.wp_manager._wp", return_value=(0, "https://www.afincas4.com", "")), \
         patch("api.routes.domains._regenerate_domain_vhost") as regen:
        hi._finalize_wordpress("afincas4.com", SimpleNamespace(username="u"), _DB(d), hi.ImportReport())
    regen.assert_not_called()


def test_subdominio_o_redireccion_no_cambia_canonico(tmp_path):
    _wp_site(tmp_path, "# BEGIN WordPress\n")
    for d in (_domain(tmp_path, is_subdomain=True), _domain(tmp_path, redirect_to="https://x.com")):
        with patch("scripts.wp_manager._wp") as wp:
            hi._finalize_wordpress("afincas4.com", SimpleNamespace(username="u"), _DB(d), hi.ImportReport())
        wp.assert_not_called()
