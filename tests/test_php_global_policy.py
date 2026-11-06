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


# ── Límites globales editables por el admin ──────────────────────────────────
def test_gana_la_ultima_activa_como_en_php():
    """PHP (y read_server_ini_value) se quedan con la ÚLTIMA activa: es la que hay que tocar."""
    ini = "upload_max_filesize = 2M\n;upload_max_filesize = 9M\nupload_max_filesize = 8M\n"
    out, _ = pm.set_global_ini_text(ini, {"upload_max_filesize": "512M"})
    assert out == "upload_max_filesize = 2M\n;upload_max_filesize = 9M\nupload_max_filesize = 512M\n"
    out2, _ = pm.apply_global_ini_text(ini)
    assert out2.splitlines()[2] == "upload_max_filesize = 64M"


def test_set_exacto_sube_y_baja():
    out, ch = pm.set_global_ini_text(DEBIAN_INI, {"memory_limit": "64M", "upload_max_filesize": "1G"})
    assert "memory_limit = 64M" in out and "upload_max_filesize = 1G" in out
    assert len(ch) == 2
    assert "post_max_size = 8M" in out                       # lo no enviado no se toca
    assert pm.set_global_ini_text(out, {"memory_limit": "64M"})[1] == []


def test_validacion_de_limites():
    vals, err = pm.validate_global_limits({"memory_limit": "1g", "upload_max_filesize": " 300m ",
                                           "max_execution_time": "300"})
    assert not err and vals == {"memory_limit": "1G", "upload_max_filesize": "300M",
                                "max_execution_time": "300"}
    for bad in ({"memory_limit": "32M"}, {"memory_limit": "-1"}, {"upload_max_filesize": "lots"},
                {"max_execution_time": "5"}, {"max_input_vars": "999999"}, {"disable_functions": ""}):
        assert pm.validate_global_limits(bad)[1], bad
    assert pm.check_limits_coherence({"upload_max_filesize": "512M", "post_max_size": "64M"})
    assert not pm.check_limits_coherence({"upload_max_filesize": "512M", "post_max_size": "520M"})


def test_nginx_hereda_el_global_de_la_version(monkeypatch):
    from scripts import utils, php_ini_manager
    monkeypatch.setattr(php_ini_manager, "read_server_ini_value",
                        lambda v, k: {"upload_max_filesize": "512M", "post_max_size": "520M"}[k])
    # Sin valor propio → el global de la versión
    assert utils.upload_mb_from_php(None, php_version="8.3") == 520
    # Con valor propio → el suyo (aunque sea menor que el global), nunca < 64
    assert utils.upload_mb_from_php('{"upload_max_filesize": "10M", "post_max_size": "10M"}',
                                    php_version="8.3") == 64
    # Sin versión: comportamiento de siempre
    assert utils.upload_mb_from_php(None) == 64


def test_endpoint_limites(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from fastapi import HTTPException
    from api.routes import php as R
    import api.utils.security_audit as audit
    state = {"memory_limit": "512M", "upload_max_filesize": "64M", "post_max_size": "64M",
             "max_execution_time": "120", "max_input_time": "120", "max_input_vars": "1000"}
    written, regen = [], []
    monkeypatch.setattr("os.path.isfile", lambda p: True)          # php.ini "instalado"
    monkeypatch.setattr(pm, "read_global_limits", lambda v: dict(state))
    def fake_set(v, values):
        written.append(values); state.update(values); return [f"{k}: → {x}" for k, x in values.items()]
    monkeypatch.setattr(pm, "set_global_limits", fake_set)
    monkeypatch.setattr(audit, "log_audit", lambda *a, **k: None)
    monkeypatch.setattr(R, "_domains_on", lambda db, v: [SimpleNamespace(
        id=1, domain_name="a.com", php_ini_overrides='{"memory_limit": "1G"}')])
    monkeypatch.setattr(R, "_regen_vhosts_async", lambda v: regen.append(v) or True)
    req = SimpleNamespace(headers={}, client=None)
    run = lambda body: asyncio.run(R.set_php_global_limits("8.3", R.PHPLimitsUpdate(limits=body),
                                                           req, current_user=None, db=None))
    # POST menor que la subida → 400 y no se escribe nada
    try:
        run({"upload_max_filesize": "512M"})
        assert False, "debía fallar"
    except HTTPException as e:
        assert e.status_code == 400 and "POST" in e.detail and not written
    # Subida + POST → se aplica y se regeneran los vhosts de la versión
    r = run({"upload_max_filesize": "512M", "post_max_size": "520M", "memory_limit": "512M"})
    assert written[-1] == {"upload_max_filesize": "512M", "post_max_size": "520M"}   # memory sin cambio
    assert regen == ["8.3"] and r["regenerating_vhosts"]
    # Bajar la memoria por debajo de un dominio con valor propio → aviso
    r = run({"memory_limit": "256M"})
    assert r["domains_above"] == [{"id": 1, "name": "a.com", "values": ["memory_limit=1G"]}]
    assert regen == ["8.3"]                                   # sin cambio de subida, no regenera
