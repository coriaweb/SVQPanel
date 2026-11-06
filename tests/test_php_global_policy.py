"""
php.ini GLOBAL de FPM: una versión de PHP instalada desde el panel debe nacer
igual que una del install (hasta 0.275.1 nacía con los 2M/8M de Debian: el
PHP 8.3 del .223 no dejaba subir más de 2 MB a 10 webs).
"""
import re
from pathlib import Path

from scripts import php_manager as pm

ROOT = Path(__file__).resolve().parent.parent

DEBIAN_INI = """[PHP]
; Quick Reference
; post_max_size
;   Default Value: 8M
max_execution_time = 30
max_input_time = 60
memory_limit = 128M
post_max_size = 8M
;upload_tmp_dir =
upload_max_filesize = 2M
disable_functions = pcntl_alarm,pcntl_fork
;mail.add_x_header = Off
"""


def test_misma_politica_que_install_sh():
    """Los techos del panel y los del install no pueden volver a desfasarse."""
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    seds = dict(re.findall(r'sed -i "s\|\^\\s\*([a-z_.]+)\\s\*=\.\*\|\1 = ([^|]*)\|" "\$PHP_INI_FPM"', text))
    assert seds, "no se encuentran los sed del php.ini en install.sh"
    for key, val in pm.GLOBAL_INI_MIN.items():
        assert seds.get(key) == val, f"{key}: install.sh={seds.get(key)} panel={val}"
    assert seds.get("disable_functions", "").strip() == pm.GLOBAL_INI_FIXED["disable_functions"]
    assert "mail.add_x_header = On" in text
    m = re.search(r"99-svqpanel-opcache\.ini\" << 'OPCACHEEOF'\n(.*?)OPCACHEEOF", text, re.S)
    assert m and m.group(1) == pm.OPCACHE_INI
    assert 'echo "apc.enable_cli = 1"' in text and pm.APCU_CLI_INI == "apc.enable_cli = 1\n"


def test_aplica_a_un_php_ini_de_debian():
    out, changes = pm.apply_global_ini_text(DEBIAN_INI)
    for line in ("memory_limit = 512M", "upload_max_filesize = 64M", "post_max_size = 64M",
                 "max_execution_time = 120", "max_input_time = 120",
                 "disable_functions =", "mail.add_x_header = On"):
        assert re.search(rf"^{re.escape(line)}$", out, re.M), line
    # Las líneas de referencia sin "=" no se tocan
    assert "; post_max_size\n;   Default Value: 8M" in out
    assert len(changes) == 7
    again, ch2 = pm.apply_global_ini_text(out)
    assert again == out and ch2 == []


def test_solo_sube_nunca_baja():
    ini = DEBIAN_INI.replace("upload_max_filesize = 2M", "upload_max_filesize = 1G") \
                    .replace("max_execution_time = 30", "max_execution_time = 0") \
                    .replace("memory_limit = 128M", "memory_limit = -1")
    out, _ = pm.apply_global_ini_text(ini)
    assert "upload_max_filesize = 1G" in out
    assert "max_execution_time = 0" in out          # 0 = sin límite
    assert "memory_limit = -1" in out


def test_comentada_antes_que_la_activa():
    ini = ";memory_limit = 1M\nmemory_limit = 128M\n"
    out, _ = pm.apply_global_ini_text(ini)
    assert out.startswith(";memory_limit = 1M\nmemory_limit = 512M\n")


def test_directiva_que_falta_se_anade():
    out, changes = pm.apply_global_ini_text("[PHP]\n")
    assert "post_max_size = 64M" in out and "mail.add_x_header = On" in out
    assert any("no estaba" in c for c in changes)


def test_ficheros_conf_d(tmp_path, monkeypatch):
    real_exists, real_isdir = pm.os.path.exists, pm.os.path.isdir
    base = tmp_path / "etc" / "php" / "8.3"
    (base / "fpm" / "conf.d").mkdir(parents=True)
    (base / "cli" / "conf.d").mkdir(parents=True)
    (base / "fpm" / "php.ini").write_text(DEBIAN_INI)
    remap = lambda p: str(p).replace("/etc/php/", str(tmp_path / "etc" / "php") + "/")
    import builtins
    real_open = builtins.open
    monkeypatch.setattr(pm.os.path, "exists", lambda p: real_exists(remap(p)))
    monkeypatch.setattr(pm.os.path, "isdir", lambda p: real_isdir(remap(p)))
    monkeypatch.setattr(pm.os, "replace", lambda a, b, _r=pm.os.replace: _r(remap(a), remap(b)))
    monkeypatch.setattr(builtins, "open", lambda p, *a, **k: real_open(remap(p), *a, **k))
    changes = pm.apply_global_ini_policy("8.3")
    assert any("99-svqpanel-opcache.ini" in c for c in changes)
    assert (base / "fpm" / "conf.d" / "99-svqpanel-opcache.ini").read_text() == pm.OPCACHE_INI
    assert (base / "cli" / "conf.d" / "99-apcu-cli.ini").exists()
    assert "upload_max_filesize = 64M" in (base / "fpm" / "php.ini").read_text()
    # Segunda vez: nada que hacer (y no pisa un OPcache retocado a mano)
    (base / "fpm" / "conf.d" / "99-svqpanel-opcache.ini").write_text("opcache.enable = 0\n")
    assert pm.apply_global_ini_policy("8.3") == []
    assert (base / "fpm" / "conf.d" / "99-svqpanel-opcache.ini").read_text() == "opcache.enable = 0\n"
