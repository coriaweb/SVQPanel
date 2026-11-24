"""Tests de scripts/laravel_workers (sin systemd: render, validación, nombres)."""
import os
import pwd

import pytest

from scripts import laravel_workers as lw
from scripts.laravel_workers import WorkerError

ME = pwd.getpwuid(os.getuid()).pw_name


def _cfg(**kw):
    c = dict(lw.DEFAULTS, workers=1)
    c.update(kw)
    return c


def test_validate_ok_y_normaliza():
    c = lw.validate_config({"workers": 2, "queue": "high, default", "memory": 256,
                            "timeout": 120, "tries": 3}, is_admin=False, other_workers=0)
    assert c["queue"] == "high,default" and c["workers"] == 2


@pytest.mark.parametrize("data", [
    {"workers": 3},                                   # > máx. por dominio (cliente)
    {"workers": 1, "memory": 1024},                   # memoria de admin
    {"workers": 1, "memory": 300},                    # no es una opción
    {"workers": 1, "timeout": 45},
    {"workers": 1, "tries": 0},
    {"workers": 1, "queue": "a b;rm -rf /"},
    {"workers": 1, "queue": "default --timeout=0"},
    {"workers": 1, "connection": "redis --x"},
    {"workers": "x"},
])
def test_validate_rechaza_cliente(data):
    with pytest.raises(WorkerError):
        lw.validate_config(data, is_admin=False, other_workers=0)


def test_limite_por_cliente():
    with pytest.raises(WorkerError):
        lw.validate_config({"workers": 2}, is_admin=False, other_workers=3)
    # 0 workers siempre se puede (es quitarlos)
    lw.validate_config({"workers": 0}, is_admin=False, other_workers=9)


def test_admin_limites_mas_altos():
    c = lw.validate_config({"workers": 6, "memory": 1024}, is_admin=True, other_workers=20)
    assert c["workers"] == 6


def test_render_unit():
    u = lw.render_unit("ej.com", 1, ME, "/home/u/web/ej.com/public_html", "/usr/bin/php8.3",
                       _cfg(queue="high,default", connection="database", memory=256, timeout=60))
    assert f"User={ME}" in u
    assert ("ExecStart=/usr/bin/php8.3 /home/u/web/ej.com/public_html/artisan queue:work database "
            "--queue=high,default --sleep=3 --tries=3 --timeout=60 --memory=256") in u
    assert "MemoryMax=384M" in u
    assert "Restart=always" in u and "NoNewPrivileges=true" in u
    assert "StandardOutput=append" not in u      # nunca a un fichero del cliente
    assert "TimeoutStopSec=75" in u


@pytest.mark.parametrize("root", ["/home/u/web/ej.com/mi app", "/home/u/../../etc", "relativa"])
def test_render_rechaza_rutas(root):
    with pytest.raises(WorkerError):
        lw.render_unit("ej.com", 1, ME, root, "/usr/bin/php", _cfg())


@pytest.mark.parametrize("dom", ["ej.com\nExecStartPre=/bin/sh", "ej.com\n", "EJ.com"])
def test_render_rechaza_dominio_raro(dom):
    with pytest.raises(WorkerError):
        lw.render_unit(dom, 1, ME, "/home/u/x", "/usr/bin/php", _cfg())


def test_salto_de_linea_final_rechazado():
    with pytest.raises(WorkerError):
        lw.validate_config({"workers": 1, "queue": "def\nault"}, is_admin=True, other_workers=0)
    with pytest.raises(WorkerError):
        lw.validate_config({"workers": 1, "connection": "redis\nx"}, is_admin=True, other_workers=0)
    with pytest.raises(WorkerError):
        lw.render_unit("ej.com", 1, ME, "/home/u/x\n", "/usr/bin/php", _cfg())


def test_existing_units(tmp_path, monkeypatch):
    monkeypatch.setattr(lw, "UNIT_DIR", str(tmp_path))
    for n in ("svqpanel-laravel-ej.com-2.service", "svqpanel-laravel-ej.com-1.service",
              "svqpanel-laravel-ej.com-shop.es-1.service", "svqpanel-laravel-otro.com-1.service"):
        (tmp_path / n).write_text("x")
    assert lw.existing_units("ej.com") == ["svqpanel-laravel-ej.com-1.service",
                                           "svqpanel-laravel-ej.com-2.service"]
    assert lw.existing_units("ej.com-shop.es") == ["svqpanel-laravel-ej.com-shop.es-1.service"]


def test_get_config_tolera_basura():
    class D:  # noqa: D401
        laravel_queue = "{no json"
    assert lw.get_config(D())["workers"] == 0
