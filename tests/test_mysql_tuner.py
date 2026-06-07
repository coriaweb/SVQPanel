"""
Tests del tuner de MariaDB/MySQL (Fase 21).

Validan los parsers de tamaño, la allowlist de directivas (que no se pueda
inyectar cualquier opción en el my.cnf) y la lógica de recomendaciones a partir
de un estado simulado del servidor. No conectan a ninguna BD real.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import mysql_tuner as t


# ── Parsers de tamaño ─────────────────────────────────────────────────────────
def test_parse_size_unidades():
    assert t.parse_size("512K") == 512 * 1024
    assert t.parse_size("256M") == 256 * 1024**2
    assert t.parse_size("2G") == 2 * 1024**3
    assert t.parse_size("1073741824") == 1073741824  # bytes crudos


def test_parse_size_vacio_o_invalido():
    assert t.parse_size(None) == 0
    assert t.parse_size("") == 0
    assert t.parse_size("-1") == 0


def test_human_size():
    assert t.human_size(2 * 1024**3) == "2G"
    assert t.human_size(1610612736) == "1.5G"
    assert t.human_size(512 * 1024**2) == "512M"


def test_human_size_mycnf_siempre_entero():
    # my.cnf NO acepta decimales: las sugerencias deben ser enteros + unidad
    assert t.human_size_mycnf(2 * 1024**3) == "2G"          # exacto en G
    assert t.human_size_mycnf(512 * 1024**2) == "512M"      # exacto en M
    # ~1.9G no es entero en G → cae a M entero (no '1.9G')
    out = t.human_size_mycnf(int(3.8 * 1024**3 * 0.5))
    assert out.endswith("M") and "." not in out


def test_parse_size_acepta_decimales():
    # 1.9G debe parsearse (antes solo aceptaba enteros)
    assert t.parse_size("1.9G") == int(1.9 * 1024**3)


def test_validate_size_normaliza_decimal_a_entero():
    # Regresión: la sugerencia '1.9G' rompía el guardado. Ahora se acepta y
    # se normaliza a un entero válido para my.cnf.
    ok, val = t.validate_directive("innodb_buffer_pool_size", "1.9G")
    assert ok
    assert "." not in val and val[-1] in "KMG"


# ── Allowlist de directivas ───────────────────────────────────────────────────
def test_validate_acepta_directiva_conocida():
    ok, val = t.validate_directive("innodb_buffer_pool_size", "512M")
    assert ok and val == "512M"


def test_validate_rechaza_directiva_no_allowlist():
    ok, err = t.validate_directive("evil_option", "rm -rf")
    assert not ok


def test_validate_size_formato_invalido():
    ok, err = t.validate_directive("innodb_buffer_pool_size", "muchos")
    assert not ok


def test_validate_int_solo_positivos():
    ok, _ = t.validate_directive("max_connections", "200")
    assert ok
    ok2, _ = t.validate_directive("max_connections", "-5")
    assert not ok2


def test_validate_bool_normaliza_on_off():
    ok, val = t.validate_directive("slow_query_log", "ON")
    assert ok and val == "1"
    ok2, val2 = t.validate_directive("slow_query_log", "off")
    assert ok2 and val2 == "0"


# ── Recomendaciones ───────────────────────────────────────────────────────────
def _status(**over):
    base = {
        "Uptime": "7200", "Innodb_buffer_pool_reads": "10",
        "Innodb_buffer_pool_read_requests": "1000000", "Max_used_connections": "10",
        "Created_tmp_disk_tables": "1", "Created_tmp_tables": "1000",
        "Opened_tables": "10", "Slow_queries": "0", "Questions": "100000",
        "Aborted_connects": "0",
    }
    base.update(over)
    return base


def _vars(**over):
    base = {
        "innodb_buffer_pool_size": "4G", "max_connections": "150",
        "query_cache_type": "OFF", "query_cache_size": "0",
        "table_open_cache": "4000", "tmp_table_size": "64M", "version": "10.11.6",
    }
    base.update(over)
    return base


def test_servidor_bien_configurado_da_ok():
    res = t.analyze(_status(), _vars(), 8 * 1024**3)
    assert res["overall"] == "ok"


def test_buffer_pool_pequeno_recomienda_subirlo():
    # 50% miss → hit ratio bajísimo
    st = _status(Innodb_buffer_pool_reads="500000")
    res = t.analyze(st, _vars(innodb_buffer_pool_size="128M"), 8 * 1024**3)
    titles = [r["title"] for r in res["recommendations"]]
    assert any("Buffer pool" in tit for tit in titles)
    rec = next(r for r in res["recommendations"] if r.get("directive") == "innodb_buffer_pool_size")
    assert rec["suggested"]  # propone un tamaño


def test_conexiones_cerca_del_limite():
    st = _status(Max_used_connections="140")  # 140/150 = 93%
    res = t.analyze(st, _vars(), 8 * 1024**3)
    assert any(r.get("directive") == "max_connections" for r in res["recommendations"])


def test_tmp_tables_en_disco():
    st = _status(Created_tmp_disk_tables="600", Created_tmp_tables="2000")  # 30%
    res = t.analyze(st, _vars(), 8 * 1024**3)
    assert any(r.get("directive") == "tmp_table_size" for r in res["recommendations"])


def test_query_cache_activado_se_avisa():
    res = t.analyze(_status(), _vars(query_cache_type="ON", query_cache_size="64M"), 8 * 1024**3)
    assert any(r.get("directive") == "query_cache_type" for r in res["recommendations"])


def test_dropin_filename_es_del_panel():
    # El archivo gestionado por el panel tiene el prefijo svqpanel para no chocar
    assert "svqpanel" in t._DROPIN_FILENAME


# ── Recomendación de buffer pool CONSCIENTE del servidor ──────────────────────
GB = 1024**3
MB = 1024**2


def test_buffer_pool_no_sobredimensiona_dataset_pequeno():
    # dataset 300M en server de 3.8G: NO debe recomendar 1.9G (el viejo 50%),
    # sino ~dataset+30%.
    r = t.recommend_buffer_pool(int(3.8 * GB), dataset_bytes=300 * MB, reserved_bytes=768 * MB)
    assert r < 600 * MB           # nada de 1.9G
    assert r >= 300 * MB          # pero cubre el dataset


def test_buffer_pool_limitado_por_ram_libre():
    # dataset enorme (5G) pero RAM libre escasa: limitado por RAM, no por dataset
    r = t.recommend_buffer_pool(int(3.8 * GB), dataset_bytes=5 * GB,
                                reserved_bytes=int(768 * MB + 800 * MB))
    assert r < int(3.8 * GB * 0.71)   # respeta el techo del 70%
    assert r < 5 * GB                  # no intenta cachear todo el dataset


def test_buffer_pool_respeta_suelo():
    r = t.recommend_buffer_pool(int(3.8 * GB), dataset_bytes=5 * GB, reserved_bytes=int(3.7 * GB))
    assert r >= t._MIN_BUFFER_POOL


def test_buffer_pool_sin_ram_no_recomienda():
    assert t.recommend_buffer_pool(0, 5 * GB, 0) == 0


def test_no_recomienda_subir_si_dataset_cabe():
    # Buffer pool 512M y dataset 300M: aunque el hit sea bajo (BD recién
    # arrancada), el dataset ya cabe → no debe proponer subirlo.
    status = {
        "Uptime": "7200", "Innodb_buffer_pool_reads": "500000",
        "Innodb_buffer_pool_read_requests": "1000000", "Max_used_connections": "5",
        "Created_tmp_tables": "10", "Created_tmp_disk_tables": "0",
        "Opened_tables": "5", "Slow_queries": "0", "Questions": "1000",
    }
    variables = {"innodb_buffer_pool_size": "512M", "max_connections": "150",
                 "query_cache_type": "OFF", "table_open_cache": "4000", "tmp_table_size": "16M"}
    res = t.analyze(status, variables, int(3.8 * GB), dataset_bytes=300 * MB,
                    reserved_bytes=768 * MB)
    bp = next(r for r in res["recommendations"] if "Buffer pool" in r["title"])
    assert bp["level"] == "ok"   # no warn


def test_recomendacion_buffer_pool_explica_el_porque():
    status = {
        "Uptime": "7200", "Innodb_buffer_pool_reads": "300000",
        "Innodb_buffer_pool_read_requests": "1000000", "Max_used_connections": "5",
        "Created_tmp_tables": "10", "Created_tmp_disk_tables": "0",
        "Opened_tables": "5", "Slow_queries": "0", "Questions": "1000",
    }
    variables = {"innodb_buffer_pool_size": "128M", "max_connections": "150",
                 "query_cache_type": "OFF", "table_open_cache": "4000", "tmp_table_size": "16M"}
    res = t.analyze(status, variables, int(3.8 * GB), dataset_bytes=1 * GB,
                    reserved_bytes=int(1.2 * GB))
    bp = next(r for r in res["recommendations"] if r.get("directive") == "innodb_buffer_pool_size")
    # El detalle menciona el dataset y la reserva del stack (no es un 50% a ciegas)
    assert "dataset" in bp["detail"].lower()
    assert "reserv" in bp["detail"].lower()
    # La sugerencia es un entero válido para my.cnf
    assert "." not in bp["suggested"]
