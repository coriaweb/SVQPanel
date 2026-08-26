"""Detección de workers y ejecución en paralelo de las copias.

El número NO puede ser fijo: el panel corre desde VPS de 2 cores hasta máquinas
grandes. Y `nproc` por sí solo no basta — en cgroups miente, y la RAM y la carga
mandan tanto como la CPU.
"""

import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import worker_pool as wp  # noqa: E402


# ── El valor configurado manda ────────────────────────────────────────────

def test_el_valor_configurado_gana_a_la_deteccion():
    assert wp.resolve_workers(3) == 3


def test_configurado_se_capa_por_arriba():
    """Un valor absurdo no debe reventar la máquina."""
    assert wp.resolve_workers(9999) == 32


@pytest.mark.parametrize("valor", [None, 0])
def test_sin_valor_configurado_se_autodetecta(valor):
    """0 o None = automático; nunca debe devolver menos de 1."""
    assert wp.resolve_workers(valor) >= 1


def test_nunca_devuelve_menos_de_uno():
    """Con 1 worker el comportamiento es el clásico (secuencial), pero jamás 0:
    un 0 dejaría el backup sin ejecutar nada."""
    with mock.patch.object(wp, "_cpu_count_real", return_value=1), \
         mock.patch.object(wp, "_mem_available_mb", return_value=128), \
         mock.patch.object(wp, "_loadavg", return_value=99.0):
        assert wp.resolve_workers() == 1


# ── Los límites del servidor se respetan ──────────────────────────────────

def test_la_ram_limita_aunque_sobren_cores():
    """16 cores pero 1 GB libre: no caben 15 workers."""
    with mock.patch.object(wp, "_cpu_count_real", return_value=16), \
         mock.patch.object(wp, "_mem_available_mb", return_value=1024), \
         mock.patch.object(wp, "_loadavg", return_value=0.0):
        # 1024/768 = 1
        assert wp.resolve_workers() == 1


def test_la_carga_alta_frena_el_paralelismo():
    """Si la máquina ya está a tope, el backup no debe echar más leña."""
    with mock.patch.object(wp, "_cpu_count_real", return_value=4), \
         mock.patch.object(wp, "_mem_available_mb", return_value=8192), \
         mock.patch.object(wp, "_loadavg", return_value=4.0):
        assert wp.resolve_workers() == 1


def test_se_reserva_un_core_al_sistema():
    """Con 4 cores ociosos se usan 3, no 4: las webs siguen sirviendo."""
    with mock.patch.object(wp, "_cpu_count_real", return_value=4), \
         mock.patch.object(wp, "_mem_available_mb", return_value=64000), \
         mock.patch.object(wp, "_loadavg", return_value=0.0):
        assert wp.resolve_workers() == 3


def test_hay_techo_de_seguridad():
    """Más allá del techo el cuello de botella deja de ser la CPU."""
    with mock.patch.object(wp, "_cpu_count_real", return_value=64), \
         mock.patch.object(wp, "_mem_available_mb", return_value=256000), \
         mock.patch.object(wp, "_loadavg", return_value=0.0):
        assert wp.resolve_workers() == wp.MAX_WORKERS


def test_sin_datos_de_ram_no_revienta():
    """/proc/meminfo puede no existir (contenedor raro, otro SO)."""
    with mock.patch.object(wp, "_cpu_count_real", return_value=4), \
         mock.patch.object(wp, "_mem_available_mb", return_value=None), \
         mock.patch.object(wp, "_loadavg", return_value=None):
        assert wp.resolve_workers() >= 1


# ── cgroups: el caso en que nproc miente ──────────────────────────────────

def test_respeta_el_limite_del_cgroup(tmp_path, monkeypatch):
    """VPS que reporta 16 cores del host pero tiene 2 asignados."""
    fake = tmp_path / "cpu.max"
    fake.write_text("200000 100000")   # = 2 cores
    real_open = open

    def _open(path, *a, **k):
        if str(path) == "/sys/fs/cgroup/cpu.max":
            return real_open(fake, *a, **k)
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", _open)
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    assert wp._cpu_count_real() == 2


def test_cgroup_sin_limite_usa_los_cores_reales(tmp_path, monkeypatch):
    fake = tmp_path / "cpu.max"
    fake.write_text("max 100000")
    real_open = open

    def _open(path, *a, **k):
        if str(path) == "/sys/fs/cgroup/cpu.max":
            return real_open(fake, *a, **k)
        raise FileNotFoundError(path)

    monkeypatch.setattr("builtins.open", _open)
    monkeypatch.setattr(os, "cpu_count", lambda: 8)
    assert wp._cpu_count_real() == 8


# ── run_tasks: paralelo sin perder ni desordenar resultados ───────────────

def _tarea(nombre):
    return {"username": "u", "domain_name": nombre, "files_path": None,
            "mail_path": None, "databases": []}


def _fake_backup(ok=True):
    def _run(job, username, domain, **kw):
        return {"status": "success" if ok else "failed", "log": [f"log de {domain}"],
                "size_bytes": 10, "files_total": 1, "db_count": 1,
                "failed_dumps": [], "repo": "repo", "error": None}
    return _run


def test_devuelve_todos_los_dominios_en_orden():
    """El paralelo termina desordenado; el log debe salir siempre igual."""
    tareas = [_tarea(f"d{i}.com") for i in range(10)]
    with mock.patch("scripts.restic_manager.run_backup", _fake_backup()):
        res = wp.run_tasks({}, tareas, workers=4)
    assert [d for d, _ in res] == [t["domain_name"] for t in tareas]


def test_un_worker_es_equivalente_a_secuencial():
    tareas = [_tarea("a.com"), _tarea("b.com")]
    with mock.patch("scripts.restic_manager.run_backup", _fake_backup()):
        res = wp.run_tasks({}, tareas, workers=1)
    assert [d for d, _ in res] == ["a.com", "b.com"]


def test_un_dominio_que_revienta_no_tumba_a_los_demas():
    """Una excepción en un hilo no puede perder las copias de los otros."""
    def _explota(job, username, domain, **kw):
        if domain == "malo.com":
            raise RuntimeError("boom")
        return _fake_backup()(job, username, domain)

    tareas = [_tarea("bueno1.com"), _tarea("malo.com"), _tarea("bueno2.com")]
    with mock.patch("scripts.restic_manager.run_backup", _explota):
        res = wp.run_tasks({}, tareas, workers=3)

    por_dominio = dict(res)
    assert len(res) == 3
    assert por_dominio["malo.com"]["status"] == "failed"
    assert por_dominio["bueno1.com"]["status"] == "success"
    assert por_dominio["bueno2.com"]["status"] == "success"


def test_lista_vacia_no_falla():
    assert wp.run_tasks({}, [], workers=4) == []


def test_describe_da_los_datos_para_la_ui():
    d = wp.describe()
    for clave in ("cpu_total", "cpu_usable", "auto_workers", "max_workers"):
        assert clave in d
    assert d["auto_workers"] >= 1
