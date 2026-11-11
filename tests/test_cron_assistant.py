"""
Asistente de crons (scripts/cron_assistant.py): plantillas, explorador acotado a
la carpeta del dominio, excepción de URL en la validación, escape de '%' en el
crontab y cálculo de próximas ejecuciones.
"""
import os
from datetime import datetime

import pytest
from pydantic import ValidationError

from scripts import cron_assistant as A
from api.schemas.cron_schemas import CronJobCreate


@pytest.fixture
def web(tmp_path):
    """/home/u/web/ejemplo.es simulado: public_html + private + una app Laravel."""
    base = tmp_path / "ejemplo.es"
    (base / "public_html" / "public").mkdir(parents=True)
    (base / "private").mkdir()
    (base / "private" / "sincronizar.php").write_text("<?php echo 1;")
    (base / "private" / "backup.sh").write_text("#!/bin/bash\n")
    (base / "private" / "notas.txt").write_text("x")
    (base / "private" / ".oculto.php").write_text("x")
    (base / "public_html" / "artisan").write_text("#!/usr/bin/env php")
    return str(base)


# ── Explorador ────────────────────────────────────────────────────────────────
def test_browse_lista_carpetas_y_solo_scripts(web):
    r = A.browse(web, "private")
    names = [e["name"] for e in r["entries"]]
    assert names == ["backup.sh", "sincronizar.php"]   # ni .txt ni ocultos
    assert r["path"] == "private" and r["parent"] == ""


def test_browse_raiz_muestra_private_fuera_de_public_html(web):
    names = [e["name"] for e in A.browse(web, "")["entries"]]
    assert "private" in names and "public_html" in names


@pytest.mark.parametrize("rel", ["..", "../..", "private/../../", "/../etc"])
def test_browse_no_sale_del_dominio(web, rel):
    with pytest.raises(A.AssistantError):
        A.browse(web, rel)


@pytest.mark.skipif(os.name == "nt", reason="symlinks en Windows requieren privilegios")
def test_browse_ignora_symlinks_que_salen(web, tmp_path):
    fuera = tmp_path / "secreto"
    fuera.mkdir()
    os.symlink(fuera, os.path.join(web, "private", "atajo"))
    names = [e["name"] for e in A.browse(web, "private")["entries"]]
    assert "atajo" not in names
    with pytest.raises(A.AssistantError):
        A.browse(web, "private/atajo")


# ── Plantillas ────────────────────────────────────────────────────────────────
def test_script_php_usa_el_php_del_dominio(web):
    cmd = A.build_script_command(web, "private/sincronizar.php", "8.3")
    assert cmd == f"/usr/bin/php8.3 {os.path.realpath(web)}/private/sincronizar.php"
    assert CronJobCreate(command=cmd).command == cmd   # pasa la validación


def test_script_sh_usa_bash_y_admite_argumentos(web):
    cmd = A.build_script_command(web, "private/backup.sh", "8.3", "--full dias=7")
    assert cmd.startswith("/bin/bash ") and cmd.endswith(" --full dias=7")


@pytest.mark.parametrize("args", ["; rm -rf /", "$(id)", "a|b", "x>y", "`id`"])
def test_argumentos_peligrosos_rechazados(web, args):
    with pytest.raises(A.AssistantError):
        A.build_script_command(web, "private/sincronizar.php", "8.3", args)


def test_solo_scripts_existentes_php_o_sh(web):
    with pytest.raises(A.AssistantError):
        A.build_script_command(web, "private/notas.txt", "8.3")
    with pytest.raises(A.AssistantError):
        A.build_script_command(web, "private/no-existe.php", "8.3")
    with pytest.raises(A.AssistantError):
        A.build_script_command(web, "../../etc/passwd", "8.3")


def test_php_binary():
    assert A.php_binary("8.5") == "/usr/bin/php8.5"
    assert A.php_binary(None) == "/usr/bin/php"
    assert A.php_binary("8.5; id") == "/usr/bin/php"


def test_detecta_laravel_por_encima_del_docroot(web):
    apps = A.detect_apps(web, os.path.join(web, "public_html", "public"), "8.4")
    lv = [a for a in apps if a["key"] == "laravel"]
    assert lv and lv[0]["command"].endswith("artisan schedule:run")
    assert lv[0]["command"].startswith("/usr/bin/php8.4 ")


def test_sin_apps_no_inventa_nada(tmp_path):
    (tmp_path / "public_html").mkdir()
    assert A.detect_apps(str(tmp_path), str(tmp_path / "public_html"), "8.3") == []


# ── URL: única excepción a los operadores ─────────────────────────────────────
def test_url_con_ampersand_es_valida():
    cmd = A.build_url_cmd("https://ejemplo.es/cron.php?token=abc&tarea=1%202")
    assert CronJobCreate(command=cmd).command == cmd


@pytest.mark.parametrize("url", [
    "https://ejemplo.es/x' ; id ; '",     # cerrar la comilla para inyectar
    "https://ejemplo.es/a b",             # espacio
    "ftp://ejemplo.es/x",
    "javascript:alert(1)",
    "https://ejemplo.es/x\\",
])
def test_url_maliciosa_rechazada(url):
    with pytest.raises(A.AssistantError):
        A.build_url_cmd(url)


def test_curl_a_mano_con_inyeccion_sigue_rechazado():
    """La excepción es SOLO el comando exacto; cualquier otra cosa con & sigue fuera."""
    for cmd in ["/usr/bin/curl -fsS -L --max-time 300 'https://a.es/x' & id",
                "/usr/bin/curl -fsS -L --max-time 300 'https://a.es/'x'' ; id",
                "curl https://a.es/?a=1&b=2"]:
        with pytest.raises(ValidationError):
            CronJobCreate(command=cmd)


# ── '%' en el crontab ─────────────────────────────────────────────────────────
def test_porcentaje_escapado_en_la_linea_del_crontab(monkeypatch):
    from scripts import cron_manager
    monkeypatch.setattr(cron_manager.os.path, "exists", lambda p: True)
    line = cron_manager._cron_line("0", "*", "*", "*", "*",
                                   "/usr/bin/curl -fsS -L --max-time 300 'https://a.es/?q=a%20b'", 7)
    assert "a\\%20b" in line and "a%20b" not in line.replace("\\%", "")


# ── Próximas ejecuciones ──────────────────────────────────────────────────────
NOW = datetime(2026, 11, 11, 10, 7, 30)   # miércoles


def test_cada_hora():
    r = A.next_runs("0", "*", "*", "*", "*", 3, now=NOW)
    assert r == [datetime(2026, 11, 11, h, 0) for h in (11, 12, 13)]


def test_cada_5_min():
    r = A.next_runs("*/5", "*", "*", "*", "*", 3, now=NOW)
    assert [t.minute for t in r] == [10, 15, 20]


def test_diario_a_una_hora_ya_pasada_salta_a_manana():
    r = A.next_runs("30", "3", "*", "*", "*", 2, now=NOW)
    assert r == [datetime(2026, 11, 12, 3, 30), datetime(2026, 11, 13, 3, 30)]


def test_semanal_lunes_y_viernes():
    r = A.next_runs("0", "9", "*", "*", "1,5", 3, now=NOW)
    assert [t.strftime("%a %d") for t in r] == ["Fri 13", "Mon 16", "Fri 20"]


def test_domingo_vale_como_0_y_7():
    a = A.next_runs("0", "0", "*", "*", "0", 1, now=NOW)
    b = A.next_runs("0", "0", "*", "*", "7", 1, now=NOW)
    assert a == b == [datetime(2026, 11, 15, 0, 0)]


def test_mensual_dia_31_salta_los_meses_cortos():
    r = A.next_runs("0", "4", "31", "*", "*", 2, now=NOW)
    assert r == [datetime(2026, 12, 31, 4, 0), datetime(2027, 1, 31, 4, 0)]


def test_dia_y_dia_semana_acotados_es_O():
    """Semántica de cron: '0 0 1 * 1' = el día 1 O cualquier lunes."""
    r = A.next_runs("0", "0", "1", "*", "1", 3, now=NOW)
    assert r == [datetime(2026, 11, 16), datetime(2026, 11, 23), datetime(2026, 11, 30)]


def test_29_febrero_lo_encuentra():
    r = A.next_runs("0", "0", "29", "2", "*", 1, now=NOW)
    assert r == [datetime(2028, 2, 29)]


def test_expresion_imposible_no_cuelga():
    assert A.next_runs("0", "0", "31", "2", "*", 1, now=NOW) == []


def test_fuera_de_rango():
    with pytest.raises(A.AssistantError):
        A.next_runs("60", "*", "*", "*", "*", 1, now=NOW)
