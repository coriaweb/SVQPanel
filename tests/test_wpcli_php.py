"""wp-cli se lanza con el PHP del dominio, no con el PHP CLI por defecto.

Bug: PHP por defecto 8.4 sin mysqli, sitio en 8.5 → wp-cli no conectaba y el
panel decía "No hay un WordPress operativo" con la web funcionando.
"""
from scripts import app_installer as ai


def _patch(monkeypatch, pool_ver, which_ok=True):
    from scripts import php_ini_manager
    monkeypatch.setattr(php_ini_manager, "has_pool", lambda dom: pool_ver)
    monkeypatch.setattr(ai.shutil, "which",
                        lambda b: f"/usr/bin/{b}" if which_ok else None)


def test_usa_el_php_del_pool(monkeypatch):
    _patch(monkeypatch, "8.5")
    cmd = [ai.WPCLI_PATH, "core", "is-installed",
           "--path=/home/obradormarilo/web/obradormarilo.com/public_html"]
    assert ai._wpcli_php(cmd) == "/usr/bin/php8.5"


def test_sin_pool_o_sin_binario_usa_el_del_sistema(monkeypatch):
    cmd = [ai.WPCLI_PATH, "eval", "1;", "--path=/home/u/web/d.com/public_html"]
    _patch(monkeypatch, None)
    assert ai._wpcli_php(cmd) is None
    _patch(monkeypatch, "8.5", which_ok=False)
    assert ai._wpcli_php(cmd) is None


def test_ruta_fuera_de_home_no_se_toca(monkeypatch):
    _patch(monkeypatch, "8.5")
    assert ai._wpcli_php([ai.WPCLI_PATH, "cli", "version"]) is None
    assert ai._wpcli_php([ai.WPCLI_PATH, "core", "is-installed", "--path=/var/www/x"]) is None


def test_run_antepone_php(monkeypatch):
    _patch(monkeypatch, "8.5")
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd

        class R:
            returncode, stdout, stderr = 0, "", ""
        return R()

    monkeypatch.setattr(ai.subprocess, "run", fake_run)
    ai._run([ai.WPCLI_PATH, "core", "is-installed", "--path=/home/u/web/d.com/public_html"],
            as_user="u")
    assert seen["cmd"][:4] == ["sudo", "-u", "u", "-H"]
    assert seen["cmd"][-5:-3] == ["/usr/bin/php8.5", ai.WPCLI_PATH]
