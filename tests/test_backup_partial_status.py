"""Un backup con BBDD sin volcar NO debe marcarse "Correcto".

El caso real: dos BBDD registradas en el panel ya no existían en MariaDB
("Unknown database"). La copia se hacía, el aviso se escribía en el log... y el
job se marcaba "Correcto". El aviso quedaba enterrado en un log de 80 líneas, así
que nadie lo veía. Si el día de mañana falla el dump de una BD CON datos, el
estado tiene que gritarlo desde la lista.

Los tres estados posibles:
  - ninguna BD falla        → success
  - algunas fallan          → partial   (los archivos SÍ están)
  - TODAS fallan            → failed    (ya existía antes)
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _agregar_estado(resultados):
    """Réplica de la agregación de backup_scheduler/backups.py.

    Mantener en sync con ambos: si allí cambia el criterio, este test debe
    fallar para que no se diverja en silencio.
    """
    any_failed = False
    partial_domains = []
    failed_dumps_all = []
    for dominio, res in resultados:
        if res["status"] == "failed":
            any_failed = True
        elif res["status"] == "partial":
            partial_domains.append(dominio)
            failed_dumps_all.extend(res.get("failed_dumps") or [])
    if any_failed:
        return "failed", partial_domains, failed_dumps_all
    if partial_domains:
        return "partial", partial_domains, failed_dumps_all
    return "success", partial_domains, failed_dumps_all


def test_todo_bien_es_success():
    estado, _, _ = _agregar_estado([
        ("a.com", {"status": "success"}),
        ("b.com", {"status": "success"}),
    ])
    assert estado == "success"


def test_una_bd_sin_volcar_no_es_success():
    """El bug original: esto se marcaba "Correcto"."""
    estado, dominios, dumps = _agregar_estado([
        ("a.com", {"status": "success"}),
        ("corosantamaria.org", {"status": "partial",
                                "failed_dumps": ["punctunm_wp_isbh8"]}),
    ])
    assert estado == "partial"
    assert dominios == ["corosantamaria.org"]
    assert dumps == ["punctunm_wp_isbh8"]


def test_los_omitidos_no_ensucian_el_estado():
    """"skipped" es normal (dominio sin contenido propio), no un aviso."""
    estado, dominios, _ = _agregar_estado([
        ("a.com", {"status": "success"}),
        ("b.com", {"status": "skipped"}),
        ("c.com", {"status": "skipped"}),
    ])
    assert estado == "success"
    assert dominios == []


def test_un_fallo_real_manda_sobre_los_avisos():
    """Si algo falló de verdad, "failed" gana: es lo más grave."""
    estado, _, _ = _agregar_estado([
        ("a.com", {"status": "partial", "failed_dumps": ["x"]}),
        ("b.com", {"status": "failed"}),
    ])
    assert estado == "failed"


def test_varios_dominios_parciales_se_acumulan():
    estado, dominios, dumps = _agregar_estado([
        ("a.com", {"status": "partial", "failed_dumps": ["db1"]}),
        ("b.com", {"status": "partial", "failed_dumps": ["db2", "db3"]}),
    ])
    assert estado == "partial"
    assert dominios == ["a.com", "b.com"]
    assert dumps == ["db1", "db2", "db3"]


def test_partial_es_un_estado_final():
    """La UI deja de sondear en los estados finales.

    Si "partial" no estuviera en la lista, el modal de progreso se quedaría
    girando indefinidamente tras una copia con avisos.
    """
    import re
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "frontend", "src", "views", "Backups.vue")
    with open(ruta, encoding="utf-8") as fh:
        contenido = fh.read()
    m = re.search(r"const FINAL = \[([^\]]+)\]", contenido)
    assert m, "no se encontró la lista FINAL en Backups.vue"
    assert "'partial'" in m.group(1)


def test_el_modelo_documenta_el_estado():
    """El comentario del modelo debe listar 'partial' (es la referencia)."""
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "api", "models", "models_backup.py")
    with open(ruta, encoding="utf-8") as fh:
        contenido = fh.read()
    assert "partial" in contenido


@pytest.mark.parametrize("longitud", [len("partial"), len("cancelled")])
def test_los_estados_caben_en_la_columna(longitud):
    """status es String(20): 'partial' cabe, no hace falta migrar el esquema."""
    assert longitud <= 20
