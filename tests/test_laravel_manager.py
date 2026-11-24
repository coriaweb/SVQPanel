"""Tests de scripts/laravel_manager (lógica pura, sin ejecutar artisan)."""
import os
import re

import pytest

from scripts import laravel_manager as lm
from scripts.laravel_manager import LaravelError


# ── .env ─────────────────────────────────────────────────────────────────────
def test_parse_env_basico():
    env = lm.parse_env(
        "# comentario\nAPP_NAME=\"Mi App\"\nAPP_DEBUG=true\nexport APP_ENV=production\n"
        "DB_PASSWORD='p#ss'\nMAIL_FROM=hola@x.com # nota\nVACIA=\n")
    assert env["APP_NAME"] == "Mi App"
    assert env["APP_DEBUG"] == "true"
    assert env["APP_ENV"] == "production"
    assert env["DB_PASSWORD"] == "p#ss"
    assert env["MAIL_FROM"] == "hola@x.com"
    assert env["VACIA"] == ""


def test_validate_env_acepta_validos():
    lm.validate_env("APP_KEY=base64:abc=\n\n# x\nexport A=1\nB=\"multi\nlinea\nfin\"\nC='x'\n")


@pytest.mark.parametrize("txt", [
    "esto no es una clave\n",
    "APP KEY=1\n",
    "A=\"sin cerrar\nB=2\n",
    "A='sin cerrar\n",
    "A=1\x00\n",
])
def test_validate_env_rechaza(txt):
    with pytest.raises(LaravelError):
        lm.validate_env(txt)


def test_set_env_value_sustituye_y_anade():
    t = "APP_DEBUG=true\nAPP_ENV=local\n"
    t = lm.set_env_value(t, "APP_DEBUG", "false")
    assert "APP_DEBUG=false" in t and "APP_DEBUG=true" not in t
    t = lm.set_env_value(t, "APP_URL", "https://ejemplo.com")
    assert t.endswith("APP_URL=https://ejemplo.com\n")
    t = lm.set_env_value(t, "APP_NAME", "Mi App")
    assert 'APP_NAME="Mi App"' in t
    lm.validate_env(t)


def test_set_env_value_no_interpreta_backrefs():
    t = lm.set_env_value("X=1\n", "X", r"a\1b")
    assert t == 'X="a\\\\1b"\n'


# ── PHP requerido ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("c,exp", [
    ("^8.2", (8, 2)), (">=8.1", (8, 1)), ("^7.3|^8.0", (7, 3)),
    ("~8.1.0 || ^8.2", (8, 1)), ("*", None), ("", None),
])
def test_php_min(c, exp):
    assert lm.php_min_from_constraint(c) == exp


# ── Consola ──────────────────────────────────────────────────────────────────
def test_artisan_quita_prefijo():
    assert lm.validate_artisan_command("php artisan route:list --json") == ["route:list", "--json"]
    assert lm.validate_artisan_command("artisan about") == ["about"]
    assert lm.validate_artisan_command("migrate:status") == ["migrate:status"]


@pytest.mark.parametrize("cmd", ["tinker", "php artisan serve", "queue:work", "queue:listen",
                                 "schedule:work", "db", "pail", "", "a\nb", "x 'sin cerrar"])
def test_artisan_bloqueados(cmd):
    with pytest.raises(LaravelError):
        lm.validate_artisan_command(cmd)


# ── Localizar proyecto ───────────────────────────────────────────────────────
def _mk_laravel(d):
    os.makedirs(os.path.join(d, "public"), exist_ok=True)
    for f in ("artisan", "composer.json"):
        open(os.path.join(d, f), "w").close()


def test_find_root(tmp_path):
    root = tmp_path / "web" / "ej.com"
    ph = root / "public_html"
    _mk_laravel(str(ph))
    assert lm.find_root(str(root), str(ph)) == os.path.realpath(ph)
    # docroot personalizado que ya apunta a /public
    assert lm.find_root(str(root), str(ph / "public")) == os.path.realpath(ph)


def test_find_root_fuera_de_bases(tmp_path):
    root = tmp_path / "web" / "ej.com"
    otro = root / "logs"
    _mk_laravel(str(otro))
    (root / "public_html").mkdir(parents=True)
    assert lm.find_root(str(root), str(otro)) is None
    assert lm.find_root(str(root), str(root / "public_html")) is None


# ── Logs ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", ["../x.log", "a/b.log", "laravel.txt", ""])
def test_log_name_invalido(name, tmp_path):
    with pytest.raises(LaravelError):
        lm._log_path(str(tmp_path), name)


def test_log_files_ignora_symlinks(tmp_path):
    logs = tmp_path / "storage" / "logs"
    logs.mkdir(parents=True)
    (logs / "laravel.log").write_text("x")
    (logs / "otro.txt").write_text("x")
    try:
        os.symlink("/etc/passwd", logs / "evil.log")
    except (OSError, NotImplementedError):
        pass
    names = [f["name"] for f in lm._log_files(str(tmp_path))]
    assert names == ["laravel.log"]


# ── Crons ────────────────────────────────────────────────────────────────────
def test_cron_command_y_regex_de_sync():
    cmd = lm.cron_command("scheduler", "/home/u/web/ej.com/public_html", "8.3")
    assert cmd.endswith("/home/u/web/ej.com/public_html/artisan schedule:run")
    assert "php8.3" in cmd or cmd.startswith("/usr/bin/php")
    m = re.search(r"\s('?)(/\S+?)/artisan\1\s", cmd + " ")
    assert m and m.group(2) == "/home/u/web/ej.com/public_html"
    q = lm.cron_command("queue", "/home/u/web/ej.com/public_html", "8.3")
    assert "queue:work --stop-when-empty" in q
    assert lm.cron_comment("queue", "ej.com") == "laravel-queue: ej.com"
